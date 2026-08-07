"""Pydantic model for the intent-spec YAML schema.

Field-by-field contract: ../specs/SCHEMA.md. This module is the single
executable source of truth for "is this spec well-formed" — gen.py imports
`load_spec()` and does no ad hoc validation of its own; every rule mentioned
in SCHEMA.md that can be checked without filesystem access (a spec's own
internal consistency) lives here as a pydantic validator. The one rule that
needs the filesystem (§0: "id must equal the spec's own filename stem") is
checked by `load_spec()` itself, since only the caller knows the path.

Run standalone for a human-readable validation report:
    uv run python generator/spec_model.py specs/_toy/toy-ssm-parameter.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TierStr = Literal["0", "0.5", "1"]
# "live" added by Slice G (apigw-redeploy, 2026-08-06): a catch whose
# mistake is invisible to EVERY static tier by construction (the only
# discriminating signal is a live apply -> modify -> re-apply -> curl loop,
# docs/apigw-redeploy-mechanics.md §6(c)) -- distinct from "0.5"
# (tier05_jsonata, which IS a static/offline check, just host-side and
# non-gating). Backward compatible: no pre-Slice-G spec uses it.
CatchTierStr = Literal["0", "0.5", "1", "live"]
Arm = Literal["awscdk", "hcl_raw", "terraconstructs"]

ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{([A-Za-z0-9_.\-]+)\}\}")


def _strict(cls):
    """Shared model_config: unknown fields are a spec bug, not silently ignored."""
    cls.model_config = ConfigDict(extra="forbid")
    return cls


# --------------------------------------------------------------------------
# §1 arms
# --------------------------------------------------------------------------


@_strict
class TerraconstructsArm(BaseModel):
    enabled: bool
    reason: str

    @model_validator(mode="after")
    def _reason_nonempty(self) -> "TerraconstructsArm":
        if not self.reason or not self.reason.strip():
            raise ValueError(
                "arms.terraconstructs.reason is required in both directions "
                "(enabled and disabled) — see SCHEMA.md §1"
            )
        return self


@_strict
class Arms(BaseModel):
    awscdk: Literal[True]
    hcl_raw: Literal[True]
    terraconstructs: TerraconstructsArm

    def enabled_arms(self) -> list[Arm]:
        arms: list[Arm] = ["awscdk", "hcl_raw"]
        if self.terraconstructs.enabled:
            arms.append("terraconstructs")
        return arms


# --------------------------------------------------------------------------
# §2 instruction
# --------------------------------------------------------------------------


@_strict
class Placeholder(BaseModel):
    name: str
    source: Literal["literal", "scenario_export", "pre_invoke_random"]
    value: str | None = None

    @model_validator(mode="after")
    def _value_required_iff_literal(self) -> "Placeholder":
        if self.source == "literal" and not self.value:
            raise ValueError(
                f"placeholder {self.name!r}: value is required when source == 'literal'"
            )
        if self.source != "literal" and self.value is not None:
            raise ValueError(
                f"placeholder {self.name!r}: value is only meaningful when "
                f"source == 'literal' (got source={self.source!r})"
            )
        return self


@_strict
class OutputContract(BaseModel):
    entry_file: str
    artifact_path: str
    build_command: str | None = None
    synth_command: str | None = None
    plan_command: str | None = None
    json_fields: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_of_synth_or_plan(self) -> "OutputContract":
        if bool(self.synth_command) == bool(self.plan_command):
            raise ValueError(
                "output_contract needs exactly one of synth_command / plan_command"
            )
        for jf in self.json_fields:
            if set(jf) - {"name", "description"} or "name" not in jf:
                raise ValueError(
                    f"json_fields entry {jf!r} must be {{name, description}}"
                )
        return self


@_strict
class PerArm(BaseModel):
    language_line: str
    output_contract: OutputContract


@_strict
class PerArmMap(BaseModel):
    awscdk: PerArm
    hcl_raw: PerArm
    terraconstructs: PerArm | None = None


@_strict
class Instruction(BaseModel):
    shared_body: str
    placeholders: list[Placeholder] = Field(default_factory=list)
    per_arm: PerArmMap

    @model_validator(mode="after")
    def _no_injected_content_in_shared_body(self) -> "Instruction":
        banned = [
            "/logs/agent/agent-output.txt",
            "IMPORTANT: Write your final",
        ]
        for phrase in banned:
            if phrase in self.shared_body:
                raise ValueError(
                    "instruction.shared_body must not itself contain the "
                    f"generator-injected trailer text ({phrase!r} found) — "
                    "see SCHEMA.md §2.1"
                )
        for arm_name in ("awscdk", "hcl_raw"):
            per_arm = getattr(self.per_arm, arm_name)
            for phrase in banned:
                if phrase in per_arm.language_line:
                    raise ValueError(
                        f"per_arm.{arm_name}.language_line must not contain "
                        f"the generator-injected trailer text ({phrase!r})"
                    )
        return self

    @model_validator(mode="after")
    def _placeholder_usage_closes(self) -> "Instruction":
        declared = {p.name for p in self.placeholders}
        if len(declared) != len(self.placeholders):
            raise ValueError("instruction.placeholders has duplicate names")

        used: set[str] = set()
        used |= set(PLACEHOLDER_TOKEN_RE.findall(self.shared_body))
        for arm_name in ("awscdk", "hcl_raw", "terraconstructs"):
            per_arm = getattr(self.per_arm, arm_name)
            if per_arm is not None:
                used |= set(PLACEHOLDER_TOKEN_RE.findall(per_arm.language_line))

        unused = declared - used
        if unused:
            raise ValueError(
                f"instruction.placeholders declares unused token(s): {sorted(unused)} "
                "— SCHEMA.md §2.2 requires every declared placeholder to be "
                "referenced at least once"
            )
        unresolvable = used - declared
        if unresolvable:
            raise ValueError(
                f"shared_body/language_line references undeclared {{token}}(s): "
                f"{sorted(unresolvable)} — add a matching instruction.placeholders entry"
            )
        return self


# --------------------------------------------------------------------------
# §2.5 seeded_files
# --------------------------------------------------------------------------

# Mirrors generator/gen.py::ARM_BOOTSTRAP_FILE -- duplicated here (not
# imported) because gen.py imports THIS module, not the other way around.
# Keep in sync by hand if a new arm's bootstrap filename ever changes.
_KNOWN_BOOTSTRAP_FILES = {"bin/app.ts", "provider.tf", "main.ts"}


@_strict
class SeededFile(BaseModel):
    path: str
    content: str

    @model_validator(mode="after")
    def _path_and_content_sane(self) -> "SeededFile":
        if not self.content:
            raise ValueError(f"seeded_files entry {self.path!r}: content must be non-empty")
        if self.path.startswith("/"):
            raise ValueError(
                f"seeded_files entry {self.path!r}: path must be relative "
                "(no leading '/') -- SCHEMA.md §2.5"
            )
        if any(part == ".." for part in self.path.split("/")):
            raise ValueError(
                f"seeded_files entry {self.path!r}: path must not contain "
                "'..' segments (workspace escape) -- SCHEMA.md §2.5"
            )
        if self.path in _KNOWN_BOOTSTRAP_FILES:
            raise ValueError(
                f"seeded_files entry {self.path!r}: collides with a known "
                f"non-agent-owned bootstrap filename {sorted(_KNOWN_BOOTSTRAP_FILES)} "
                "-- SCHEMA.md §2.5"
            )
        return self


# --------------------------------------------------------------------------
# §3 catches
# --------------------------------------------------------------------------


@_strict
class PredictedTierCaught(BaseModel):
    awscdk: CatchTierStr
    hcl: CatchTierStr
    terraconstructs_override: CatchTierStr | None = None


@_strict
class Catch(BaseModel):
    name: str
    taxonomy: Literal[
        "typed-value-trap", "graph-dependency", "nested-attribute", "anti-L2"
    ]
    description: str
    predicted_tier_caught: PredictedTierCaught
    # Slice G addition (apigw-redeploy, 2026-08-06): which enabled arms this
    # catch's mistake is even POSSIBLE on. Defaults to all three (matching
    # every pre-Slice-G spec's implicit assumption -- apigw-openapi's own
    # catches never set this and every one of its declared mistakes reproduces
    # identically on all 3 arms) so this is 100% backward compatible: no
    # existing spec's generated output or gate verdict changes.
    # gates/oracle_falsifiability.py::check_arm only requires a
    # `solution/broken/<name>/solve.sh` fixture for arms listed here -- some
    # mistakes are structurally IMPOSSIBLE to reproduce on an L2 arm without
    # dropping to a manual escape hatch (e.g. hand-omitting a TF `triggers`
    # block has no direct CDK/terraconstructs L2 equivalent; the L2 always
    # computes one), and requiring a fixture nothing can meaningfully author
    # for that arm was previously not even expressible.
    applies_to: list[Arm] = Field(
        default_factory=lambda: ["awscdk", "hcl_raw", "terraconstructs"]
    )


# --------------------------------------------------------------------------
# §4 oracle
# --------------------------------------------------------------------------


@_strict
class StructuralAssert(BaseModel):
    name: str
    description: str
    tier: TierStr
    applies_to: list[Arm] = Field(
        default_factory=lambda: ["awscdk", "hcl_raw", "terraconstructs"]
    )
    cfn_jsonpath: str | None = None
    tf_jsonpath: str | None = None
    op: Literal[
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq", "absent_or_eq", "not_regex"
    ]
    expected: object = None

    @model_validator(mode="after")
    def _jsonpaths_required_per_applies_to(self) -> "StructuralAssert":
        if self.tier == "0.5":
            raise ValueError(
                f"structural_assert {self.name!r}: tier '0.5' is invalid here "
                "— that tier is tier05_jsonata-only (SCHEMA.md §4.2)"
            )
        if "awscdk" in self.applies_to and not self.cfn_jsonpath:
            raise ValueError(
                f"structural_assert {self.name!r}: cfn_jsonpath required "
                "because 'awscdk' is in applies_to"
            )
        if (
            "hcl_raw" in self.applies_to or "terraconstructs" in self.applies_to
        ) and not self.tf_jsonpath:
            raise ValueError(
                f"structural_assert {self.name!r}: tf_jsonpath required "
                "because a TF-shaped arm is in applies_to"
            )
        needs_expected = self.op in {
            "eq", "in", "contains", "regex", "set_eq", "absent_or_eq", "not_regex"
        }
        if needs_expected and self.expected is None:
            raise ValueError(
                f"structural_assert {self.name!r}: op={self.op!r} requires 'expected'"
            )
        if not needs_expected and self.expected is not None:
            raise ValueError(
                f"structural_assert {self.name!r}: op={self.op!r} must not set 'expected'"
            )
        return self


@_strict
class Tier05Case(BaseModel):
    # `expression_path` pins this case to ONE specific `{% ... %}`
    # expression -- the exact path oracles.lib.tier05_jsonata.
    # jsonata_expressions() reports it found that expression at (e.g.
    # "$.States.G.Parameters.foo"). Without this, run_tier05 used to
    # evaluate EVERY expression against EVERY case's sample_input and
    # compare each to that case's single expected_output -- a cartesian
    # product that rejects a fully-correct multi-expression state machine
    # the moment it has more than one embedded expression (state A's
    # expression evaluated against state B's sample input, compared to
    # state B's expected output, fails despite both A and B individually
    # being correct). Keying each case to its own expression_path also
    # fixes real Step-Functions-input-binding fidelity as a side effect:
    # each case now supplies exactly the input ITS expression should see
    # (the real predecessor state's output, or whatever `$states.input`
    # resolves to at that point in a real execution) instead of one global
    # workflow input auto-bound to every expression uniformly.
    #
    # MULTIPLE cases MAY share the same `expression_path` (relaxed
    # 2026-08-06, suspenders half of the fix for benchmark-integrity review
    # finding "tier05_jsonata materialize() container fallback accepts a
    # fully-hardcoded literal"): the container-fallback path in
    # `run_tier05` (case 2 of its own docstring) compares a materialized
    # value against ONE sample's `expected_output`, and with exactly one
    # sample per expression a fully hardcoded literal tuned to that one
    # sample compares equal by construction. A second, independently-input
    # sample against the SAME expression_path closes that gap without any
    # oracle-side special-casing -- `run_tier05` already evaluates every
    # case independently (see above), so two cases naming the same
    # expression are just two more (sample_index, input, expected_output)
    # rows through the exact same per-case loop, each checked on its own.
    expression_path: str
    input: dict
    expected_output: object


@_strict
class Tier05Jsonata(BaseModel):
    # str: one JSONPath used against every arm's own artifact (only usable
    # when a scenario is checked against a single artifact family). dict:
    # {"cfn": <path>, "tf": <path>} -- the normal case for a real cross-arm
    # scenario, since CFN template JSON and Terraform plan JSON have
    # structurally different root shapes (`$.Resources[...]` vs.
    # `$.planned_values.root_module.resources[...]`) -- one path literally
    # cannot resolve against both. `oracles.lib.tier05_jsonata.run_tier05`
    # auto-detects which family a given artifact document is (top-level
    # `Resources` key vs. `planned_values` key) and selects the matching
    # path; `hcl_raw`/`terraconstructs` share the `tf` path (SCHEMA.md §4.4).
    expressions_from: str | dict[str, str]
    cases: Annotated[list[Tier05Case], Field(min_length=1)]

    @model_validator(mode="after")
    def _expressions_from_dict_keys_valid(self) -> "Tier05Jsonata":
        if isinstance(self.expressions_from, dict):
            allowed = {"cfn", "tf"}
            keys = set(self.expressions_from)
            if not keys or keys - allowed:
                raise ValueError(
                    "oracle.tier05_jsonata.expressions_from (dict form) keys "
                    f"must be a non-empty subset of {sorted(allowed)}, got "
                    f"{sorted(keys)} (SCHEMA.md §4.4)"
                )
        return self

    # NOTE: this used to reject duplicate `expression_path` values outright
    # ("each declared expression should have exactly one case"). Relaxed
    # 2026-08-06 (see Tier05Case's own docstring) -- multiple cases MAY
    # legitimately share an `expression_path`, each supplying an
    # independent (input, expected_output) sample against that same
    # expression, so a single hardcoded-literal container can't satisfy
    # every sample at once. `run_tier05` (oracles/lib/tier05_jsonata.py)
    # already evaluates every case independently regardless of path
    # collisions, so no oracle-side change was needed to support this --
    # only this now-removed over-strict validator stood in the way.


@_strict
class Oracle(BaseModel):
    intent: str
    structural_asserts: list[StructuralAssert]
    rego_hints: list[str] = Field(default_factory=list)
    cfn_guard_hints: list[str] = Field(default_factory=list)
    tier05_jsonata: Tier05Jsonata | None = None

    @model_validator(mode="after")
    def _names_unique(self) -> "Oracle":
        names = [a.name for a in self.structural_asserts]
        if len(names) != len(set(names)):
            raise ValueError("oracle.structural_asserts has duplicate names")
        return self


# --------------------------------------------------------------------------
# §5 verifier
# --------------------------------------------------------------------------


@_strict
class VerifierBudget(BaseModel):
    max_iters: int = 8

    @model_validator(mode="after")
    def _never_raise_above_prereg_default(self) -> "VerifierBudget":
        if self.max_iters > 8:
            raise ValueError(
                "verifier.budget.max_iters may only lower the pre-registered "
                "default of 8, never raise it without a logged amendment "
                "(SCHEMA.md §5)"
            )
        if self.max_iters < 1:
            raise ValueError("verifier.budget.max_iters must be >= 1")
        return self


@_strict
class LiveCheck(BaseModel):
    # Relaxed from `Literal[False]` by Slice G (apigw-redeploy, 2026-08-06;
    # docs/slice-g-recon.md gap 1, DECISIONS.md "Slice G" amendment). Every
    # v1 spec still sets this false (unchanged behavior); `true` is now a
    # legal, gen.py-honored value.
    enabled: bool
    module: str = "tests/live_check.py"
    # When true, `module` (tests/live_check.py) is HAND-AUTHORED, not
    # generated -- gen.py's write_tests step becomes destructive-safe for
    # this one file, the same "never touch existing hand-authored content"
    # convention solution/solve.sh already has (SCHEMA.md §8.2 point 8).
    # Must be true whenever enabled is true: a spec that turns live_check on
    # but leaves the generated not-implemented stub in place would silently
    # ship a scenario whose live behavioral facts are never actually
    # checked (docs/slice-g-recon.md gap 5).
    hand_authored: bool = False
    # Spec-driven override of the previously hardcoded
    # `agent_role_name = "QALocalInvocationApplicationRole"` /
    # `[concurrency] mode = "read-only"` (generator/gen.py:655,662 before
    # this fix; docs/slice-g-recon.md gap 2). None (the default) preserves
    # the old hardcoded values byte-for-byte -- required for every
    # live_check.enabled=false spec, and legal (though unusual) for one that
    # somehow needs live_check without mutation.
    agent_role_name: str | None = None
    concurrency_mode: Literal["read-only", "mutating"] | None = None

    @model_validator(mode="after")
    def _hand_authored_required_when_enabled(self) -> "LiveCheck":
        if self.enabled and not self.hand_authored:
            raise ValueError(
                "verifier.live_check.enabled=true requires hand_authored=true "
                "-- otherwise gen.py's generated not-implemented stub would "
                "silently ship as this scenario's live check (SCHEMA.md §5)"
            )
        return self


@_strict
class Verifier(BaseModel):
    budget: VerifierBudget = Field(default_factory=VerifierBudget)
    live_check: LiveCheck


# --------------------------------------------------------------------------
# §6 provenance
# --------------------------------------------------------------------------


@_strict
class Provenance(BaseModel):
    author: str
    date: str
    prereg_section_refs: list[str]

    @model_validator(mode="after")
    def _nonempty(self) -> "Provenance":
        if not self.author.strip():
            raise ValueError("provenance.author must be non-empty")
        if not self.prereg_section_refs:
            raise ValueError("provenance.prereg_section_refs must be non-empty")
        return self


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------


@_strict
class Spec(BaseModel):
    id: str
    title: str
    difficulty: Annotated[int, Field(ge=1, le=3)]
    services: Annotated[list[str], Field(min_length=1)]
    arms: Arms
    instruction: Instruction
    seeded_files: list[SeededFile] = Field(default_factory=list)
    catches: Annotated[list[Catch], Field(min_length=1)]
    oracle: Oracle
    verifier: Verifier
    provenance: Provenance

    @model_validator(mode="after")
    def _id_format(self) -> "Spec":
        if not ID_RE.match(self.id):
            raise ValueError(
                f"id {self.id!r} must match ^[a-z][a-z0-9-]*$ (SCHEMA.md §0)"
            )
        return self

    @model_validator(mode="after")
    def _terraconstructs_per_arm_required_iff_enabled(self) -> "Spec":
        tc_enabled = self.arms.terraconstructs.enabled
        tc_per_arm = self.instruction.per_arm.terraconstructs
        if tc_enabled and tc_per_arm is None:
            raise ValueError(
                "arms.terraconstructs.enabled is true but "
                "instruction.per_arm.terraconstructs is missing (SCHEMA.md §2)"
            )
        if not tc_enabled and tc_per_arm is not None:
            raise ValueError(
                "instruction.per_arm.terraconstructs is set but "
                "arms.terraconstructs.enabled is false — remove one or the other"
            )
        return self

    @model_validator(mode="after")
    def _seeded_files_unique_and_no_entry_file_collision(self) -> "Spec":
        paths = [f.path for f in self.seeded_files]
        if len(paths) != len(set(paths)):
            raise ValueError("seeded_files has duplicate path values -- SCHEMA.md §2.5")
        entry_files = {
            per_arm.output_contract.entry_file
            for per_arm in (
                self.instruction.per_arm.awscdk,
                self.instruction.per_arm.hcl_raw,
                self.instruction.per_arm.terraconstructs,
            )
            if per_arm is not None
        }
        collisions = set(paths) & entry_files
        if collisions:
            raise ValueError(
                f"seeded_files path(s) {sorted(collisions)} collide with an "
                "enabled arm's output_contract.entry_file -- SCHEMA.md §2.5"
            )
        return self

    @model_validator(mode="after")
    def _structural_asserts_applies_to_enabled_arms(self) -> "Spec":
        enabled = set(self.arms.enabled_arms())
        for a in self.oracle.structural_asserts:
            extra = set(a.applies_to) - enabled
            if extra:
                raise ValueError(
                    f"structural_assert {a.name!r}: applies_to includes "
                    f"disabled/unknown arm(s) {sorted(extra)}"
                )
        return self

    @model_validator(mode="after")
    def _catches_taxonomy_diversity_note(self) -> "Spec":
        # Real seed scenarios should carry an anti-L2 catch (SCHEMA.md §3);
        # the toy fixture is explicitly exempt (its own header says so) and
        # this is therefore advisory, not enforced here — enforcing it would
        # make the toy fixture itself invalid, which SCHEMA.md §7 explicitly
        # says must not happen.
        return self

    def complexity(self) -> str:
        return {1: "Atomic", 2: "Sequential", 3: "Orchestrated"}[self.difficulty]


def load_spec(path: Path) -> Spec:
    """Load + validate a spec YAML file. Enforces the one filesystem-dependent
    rule pydantic can't see on its own: id must equal the file's own stem
    (SCHEMA.md §0)."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    spec = Spec.model_validate(raw)
    if spec.id != path.stem:
        raise ValueError(
            f"{path}: spec id {spec.id!r} does not match filename stem "
            f"{path.stem!r} — the generator refuses to run against a "
            "renamed-but-not-moved file (SCHEMA.md §0)"
        )
    return spec


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <spec.yaml>", file=sys.stderr)
        raise SystemExit(2)
    s = load_spec(Path(sys.argv[1]))
    print(f"OK: {s.id!r} validated — {len(s.catches)} catch(es), "
          f"arms={s.arms.enabled_arms()}, "
          f"{len(s.oracle.structural_asserts)} structural_assert(s)")
