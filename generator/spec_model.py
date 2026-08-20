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
    # SCHEMA.md §2.6: the REAL deploy command for this arm, used ONLY by a
    # multi-step spec whose step declares `pre_invoke.deploy_prior: true`
    # (the harness deploys the previous step's work with staged credentials
    # before this step's agent runs -- DECISIONS.md Amendment 26 §2's
    # DEFAULT). Deliberately spec-declared per arm rather than inferred by
    # the generator from a hardcoded arm->command map: guessing a deploy
    # command is how a harness action silently deploys the wrong tree or the
    # wrong stack. gen.py hard-errors if a step asks for deploy_prior and any
    # enabled arm leaves this unset. `apigw-redeploy` -- the only multi-step
    # spec today -- deliberately does NOT use it (the AGENT deploys in both
    # steps; see docs/prompt-decomposition-audit.md §3), so this field is
    # unset on every arm of every current spec.
    deploy_command: str | None = None
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

    def _tokens_used(self) -> set[str]:
        used: set[str] = set(PLACEHOLDER_TOKEN_RE.findall(self.shared_body))
        for arm_name in ("awscdk", "hcl_raw", "terraconstructs"):
            per_arm = getattr(self.per_arm, arm_name)
            if per_arm is not None:
                used |= set(PLACEHOLDER_TOKEN_RE.findall(per_arm.language_line))
        return used

    @model_validator(mode="after")
    def _placeholder_usage_closes(self) -> "Instruction":
        """Every `{{token}}` used here must be declared.

        NOTE the other half of §2.2's rule -- "every DECLARED placeholder must
        be referenced at least once" -- lives on `Spec` (see
        `Spec._every_declared_placeholder_is_used`), not here: with `steps`
        (§2.6) a placeholder may legitimately be referenced only from a STEP's
        instruction body, which this model cannot see. Keeping the
        undeclared-token half here means an unresolvable `{{...}}` in the
        shared instruction still fails at the narrowest possible scope.
        """
        declared = {p.name for p in self.placeholders}
        if len(declared) != len(self.placeholders):
            raise ValueError("instruction.placeholders has duplicate names")

        unresolvable = self._tokens_used() - declared
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
    # Slice G fix-round-3 addition (DECISIONS.md Slice G amendment,
    # 2026-08-07): False (default) reproduces every pre-existing spec's
    # behavior byte-for-byte -- live_check.py runs (if enabled) purely
    # observationally, its result never affecting /logs/verifier/reward.txt
    # (SCHEMA.md §5's original "non-gating" invariant). `apigw-redeploy` is
    # the first spec to set this `true`: its `triggers-incomplete-hash`
    # catch is a `predicted_tier_caught: "live"` catch BY CONSTRUCTION
    # (docs/apigw-redeploy-mechanics.md §6(c)) -- no static tier can ever
    # observe it, so leaving live_check non-gating for this scenario would
    # mean the one catch that motivates this scenario's existence can never
    # actually cost a real trial any reward. gen.py::build_test_sh reads
    # this to fold live_check.py's own outcome into reward.txt (AND
    # semantics: final reward is 1.0 iff the static tiers say 1.0 AND
    # live_check.py's outcome is "pass" -- "not_verifiable" and
    # "fail_stale" both downgrade to 0.0, fail-closed).
    gating: bool = False

    @model_validator(mode="after")
    def _hand_authored_required_when_enabled(self) -> "LiveCheck":
        if self.enabled and not self.hand_authored:
            raise ValueError(
                "verifier.live_check.enabled=true requires hand_authored=true "
                "-- otherwise gen.py's generated not-implemented stub would "
                "silently ship as this scenario's live check (SCHEMA.md §5)"
            )
        if self.gating and not self.enabled:
            raise ValueError(
                "verifier.live_check.gating=true requires enabled=true -- "
                "a live check that never runs cannot gate reward"
            )
        return self


@_strict
class Verifier(BaseModel):
    budget: VerifierBudget = Field(default_factory=VerifierBudget)
    live_check: LiveCheck


# --------------------------------------------------------------------------
# §2.6 steps -- multi-step decomposition (top-level, sibling of `instruction`)
#
# Added 2026-08-20 by the prompt-decomposition slice
# (docs/prompt-decomposition-audit.md; DECISIONS.md Amendments 26/27). A spec
# with NO `steps` key generates byte-identically to before this field existed
# -- that regression guarantee is the whole reason every branch gen.py grows
# for steps is `if spec.steps:`-guarded rather than a refactor of the
# single-step path.
#
# What a step is FOR: revealing the second intent only when it is due. A
# single prompt that says "build X, then change it to Y" measures day-1
# authoring with perfect foreknowledge, which is the one condition a real
# day-2 change never has -- see the audit doc's §0 for the rule and §2 for
# the worked evidence.
# --------------------------------------------------------------------------

STEP_NAME_RE = re.compile(r"^[0-9]{2}-[a-z][a-z0-9-]*$")


@_strict
class StepPerArm(BaseModel):
    """Per-arm, per-STEP override of `instruction.per_arm.<arm>.language_line`.

    Exists because the spec-level language line can itself foreshadow: this
    scenario's awscdk line named `MockIntegration` -- the day-2 integration
    type -- which would have leaked the step-2 intent into the step-1 prompt
    on exactly ONE arm (an arm-PARITY defect on top of a foreshadowing one).
    See docs/prompt-decomposition-audit.md §2 "Leak 4".
    """

    language_line: str


@_strict
class StepPerArmMap(BaseModel):
    awscdk: StepPerArm | None = None
    hcl_raw: StepPerArm | None = None
    terraconstructs: StepPerArm | None = None


@_strict
class StepInstruction(BaseModel):
    """This step's prompt body. Assembled by gen.py exactly like the
    single-step one (§2.1): shared_body -> language line -> ownership note ->
    live-credentials note -> trailer -> JSON fence, so the shared prefix stays
    identical across arms WITHIN a step and gen.py's parity self-check extends
    to steps unchanged."""

    shared_body: str
    per_arm: StepPerArmMap | None = None

    @model_validator(mode="after")
    def _no_injected_content_in_shared_body(self) -> "StepInstruction":
        # Same ban as Instruction's: the generator injects the trailer, so a
        # spec that also writes it produces it twice.
        banned = ["/logs/agent/agent-output.txt", "IMPORTANT: Write your final"]
        for phrase in banned:
            if phrase in self.shared_body:
                raise ValueError(
                    "steps[].instruction.shared_body must not itself contain "
                    f"the generator-injected trailer text ({phrase!r} found) — "
                    "see SCHEMA.md §2.1/§2.6"
                )
            for arm_name in ("awscdk", "hcl_raw", "terraconstructs"):
                per_arm = getattr(self.per_arm, arm_name, None) if self.per_arm else None
                if per_arm is not None and phrase in per_arm.language_line:
                    raise ValueError(
                        f"steps[].instruction.per_arm.{arm_name}.language_line "
                        f"must not contain the generator-injected trailer text "
                        f"({phrase!r})"
                    )
        return self

    def tokens_used(self) -> set[str]:
        used: set[str] = set(PLACEHOLDER_TOKEN_RE.findall(self.shared_body))
        for arm_name in ("awscdk", "hcl_raw", "terraconstructs"):
            per_arm = getattr(self.per_arm, arm_name, None) if self.per_arm else None
            if per_arm is not None:
                used |= set(PLACEHOLDER_TOKEN_RE.findall(per_arm.language_line))
        return used


@_strict
class StepLiveCheck(BaseModel):
    """Per-step override of `verifier.live_check.{enabled,gating}`.

    Omitted (the default) means "inherit the spec-level values" -- so a
    live-checked scenario's every step is live-checked unless it says
    otherwise. `module`/`hand_authored`/`agent_role_name`/`concurrency_mode`
    are NOT per-step: the role and the concurrency mode are properties of the
    whole trial (one container, one account, one reset), and the module path
    is fixed by the step layout (`steps/<name>/tests/live_check.py`).
    """

    enabled: bool
    gating: bool = False

    @model_validator(mode="after")
    def _gating_requires_enabled(self) -> "StepLiveCheck":
        if self.gating and not self.enabled:
            raise ValueError(
                "steps[].oracle.live_check.gating=true requires enabled=true — "
                "a live check that never runs cannot gate reward"
            )
        return self


@_strict
class StepOracle(BaseModel):
    """Which of the spec's own `oracle.structural_asserts` this step grades.

    `structural_asserts` is a list of assert NAMES -- a projection of the one
    spec-level oracle, never a second, independently-drifting oracle
    definition. Omitted means "every assert", which the LAST step is REQUIRED
    to use (DECISIONS.md Amendment 26: the final step runs the full tier
    suite, so a multi-step task's terminal grading is identical to what the
    single-step form graded).
    """

    structural_asserts: list[str] | None = None
    live_check: StepLiveCheck | None = None

    @model_validator(mode="after")
    def _assert_names_nonempty_and_unique(self) -> "StepOracle":
        if self.structural_asserts is None:
            return self
        if not self.structural_asserts:
            raise ValueError(
                "steps[].oracle.structural_asserts, when present, must be "
                "non-empty — omit the key entirely to mean 'every assert'"
            )
        if len(set(self.structural_asserts)) != len(self.structural_asserts):
            raise ValueError(
                "steps[].oracle.structural_asserts has duplicate names: "
                f"{sorted(self.structural_asserts)}"
            )
        return self


@_strict
class StepPreInvoke(BaseModel):
    """Declarative harness actions run BEFORE this step's agent, with
    `[scenario].pre_invoke_role_name` credentials staged
    (cdktn_bench/trial.py::CdktnMultiStepTrial._run_step_pre_invoke).

    `deploy_prior: true` is DECISIONS.md Amendment 26 §2's DEFAULT shape --
    the harness deploys the previous step's IaC so this step's prompt lands on
    an account that really is in the state the prompt assumes. It emits
    `steps/<name>/pre_invoke/pre_invoke.sh` running the arm's own
    `output_contract.deploy_command` (spec-declared per arm; the generator
    refuses to guess one).

    `apigw-redeploy` deliberately declares NO pre_invoke at all: it opts into
    agent-deploys in both steps because the deploy loop IS the measurement
    (Amendment 26 §2's explicit opt-out; rationale in
    docs/prompt-decomposition-audit.md §3).

    `timeout_sec` is REQUIRED reading of Amendment 26's draft addendum (a):
    the per-step pre_invoke inherits the TASK-level `[pre_invoke].timeout_sec`
    (aws-bench's default is 600 s) and a real deploy comfortably exceeds it,
    so gen.py emits `[pre_invoke] timeout_sec` explicitly, sized to the
    LARGEST value any step declares.
    """

    deploy_prior: bool = False
    timeout_sec: float = 1800.0

    @model_validator(mode="after")
    def _declares_an_action(self) -> "StepPreInvoke":
        if not self.deploy_prior:
            raise ValueError(
                "steps[].pre_invoke declares no action (deploy_prior is false) "
                "— omit the whole `pre_invoke` key instead of emitting an "
                "empty harness script"
            )
        if self.timeout_sec <= 0:
            raise ValueError("steps[].pre_invoke.timeout_sec must be > 0")
        return self


@_strict
class Step(BaseModel):
    name: str
    instruction: StepInstruction
    oracle: StepOracle = Field(default_factory=StepOracle)
    pre_invoke: StepPreInvoke | None = None
    # None -> gen.py's default: 1.0 on every NON-final step (Amendment 26 §3's
    # hard gate: step N+1's prompt never fires unless step N verified green),
    # omitted entirely on the final step (there are no remaining steps for it
    # to gate). An author who genuinely wants an ungated intermediate step
    # writes `min_reward: 0.0`, which is always satisfied -- deliberately
    # explicit, so "no gate" is never the result of forgetting a key.
    min_reward: float | None = None

    @model_validator(mode="after")
    def _name_and_reward_wellformed(self) -> "Step":
        if not STEP_NAME_RE.match(self.name):
            raise ValueError(
                f"steps[].name {self.name!r} must match {STEP_NAME_RE.pattern} "
                "(NN-slug, e.g. '01-deploy-two-route-api') — the NN prefix is "
                "what makes the on-disk steps/ listing order match execution "
                "order (SCHEMA.md §2.6)"
            )
        if self.min_reward is not None and not (0.0 <= self.min_reward <= 1.0):
            raise ValueError(
                f"steps[].min_reward must be within [0.0, 1.0], got {self.min_reward!r}"
            )
        return self


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
    # §0.1, optional. The header comment stamped into the arm SKELETON files
    # (main.tf / lib/scenario-stack.ts / bin/app.ts / main.ts) -- i.e. into
    # `environment/`, which IS the image the agent lives in from step 1
    # onward. Absent = `title` (every single-step spec: byte-identical
    # emission). REQUIRED for a multi-step spec, because a scenario `title`
    # legitimately describes the WHOLE arc ("deploy, confirm, modify,
    # re-deploy (day-2 iteration)") and stamping that arc into the first file
    # the step-1 agent opens foreshadows step 2 just as loudly as the prompt
    # would -- DECISIONS.md Amendment 26 §7 rule 2 /
    # docs/multistep-trial-investigation.md §5 rule 2 ("never place
    # later-step material in environment/").
    workspace_title: str | None = None
    difficulty: Annotated[int, Field(ge=1, le=3)]
    services: Annotated[list[str], Field(min_length=1)]
    arms: Arms
    instruction: Instruction
    seeded_files: list[SeededFile] = Field(default_factory=list)
    catches: Annotated[list[Catch], Field(min_length=1)]
    oracle: Oracle
    verifier: Verifier
    # §2.6, optional. None/absent (every spec but `apigw-redeploy`) = the
    # single-step shape, generated byte-identically to before this field
    # existed. A non-empty list makes this a MULTI-STEP task
    # (`[[steps]]` in task.toml, run by cdktn_bench.trial.CdktnMultiStepTrial).
    steps: list[Step] | None = None
    provenance: Provenance

    def is_multi_step(self) -> bool:
        return bool(self.steps)

    def workspace_header(self) -> str:
        """The one-line title stamped into the arm skeleton files under
        `environment/`. See the `workspace_title` field comment: single-step
        specs keep `title` verbatim (byte-identity), multi-step specs must
        declare a step-1-safe alternative."""
        return self.workspace_title or self.title

    def step_assert_names(self, step: Step) -> list[str]:
        """This step's assert names in the spec's own declaration order.

        Omitting `oracle.structural_asserts` means every assert (the final
        step's required shape), and the spec's own order is preserved rather
        than the step's listing order so the generated tests/static_tiers.sh
        emits its checks in one canonical order regardless of how a step
        happened to list them.
        """
        declared = [a.name for a in self.oracle.structural_asserts]
        if step.oracle.structural_asserts is None:
            return declared
        selected = set(step.oracle.structural_asserts)
        return [name for name in declared if name in selected]

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
    def _every_declared_placeholder_is_used(self) -> "Spec":
        """SCHEMA.md §2.2's "no unused placeholder" half.

        Lives here rather than on `Instruction` because a step's own
        instruction body (§2.6) is a legitimate usage site that `Instruction`
        cannot see. The undeclared-token half stays on `Instruction`.
        """
        declared = {p.name for p in self.instruction.placeholders}
        used = self.instruction._tokens_used()
        for step in self.steps or []:
            used |= step.instruction.tokens_used()
        unused = declared - used
        if unused:
            raise ValueError(
                f"instruction.placeholders declares unused token(s): {sorted(unused)} "
                "— SCHEMA.md §2.2 requires every declared placeholder to be "
                "referenced at least once"
            )
        return self

    @model_validator(mode="after")
    def _steps_wellformed(self) -> "Spec":
        """Everything §2.6 requires of a `steps:` list, checked in one place."""
        if self.steps is None:
            return self
        if len(self.steps) < 2:
            raise ValueError(
                "steps must declare at least 2 entries — a 1-step 'multi-step' "
                "task is pure churn (it moves every task checksum and equipping "
                "hash for no measurement gain; DECISIONS.md Amendment 26 §6 "
                "explicitly refuses normalizing single-step tasks). Omit `steps` "
                "entirely for a single-step scenario."
            )

        names = [s.name for s in self.steps]
        if len(set(names)) != len(names):
            raise ValueError(f"steps have duplicate name(s): {sorted(names)}")
        prefixes = [int(n[:2]) for n in names]
        if prefixes != sorted(prefixes) or prefixes != list(
            range(prefixes[0], prefixes[0] + len(prefixes))
        ):
            raise ValueError(
                f"steps[].name NN prefixes {prefixes} must be consecutive and "
                "ascending in declaration order (01, 02, ...) — the prefix is "
                "the only thing that makes an on-disk `steps/` listing read in "
                "execution order"
            )

        enabled = set(self.arms.enabled_arms())
        declared_asserts = {a.name for a in self.oracle.structural_asserts}
        for index, step in enumerate(self.steps):
            is_final = index == len(self.steps) - 1

            unknown = set(step.oracle.structural_asserts or []) - declared_asserts
            if unknown:
                raise ValueError(
                    f"step {step.name!r}: oracle.structural_asserts names "
                    f"{sorted(unknown)} that oracle.structural_asserts does not "
                    "declare — a step's oracle is a PROJECTION of the one "
                    "spec-level oracle, never a second definition"
                )
            if is_final and step.oracle.structural_asserts is not None:
                raise ValueError(
                    f"final step {step.name!r} must OMIT "
                    "oracle.structural_asserts: the last step runs the FULL "
                    "tier suite, so a multi-step task's terminal grading is "
                    "identical to what the single-step form graded "
                    "(DECISIONS.md Amendment 26 §7 / SCHEMA.md §2.6)"
                )
            if not is_final and step.oracle.structural_asserts is None:
                raise ValueError(
                    f"step {step.name!r} is not the final step and must name "
                    "its own oracle.structural_asserts subset — inheriting the "
                    "full suite would grade an intermediate state against the "
                    "FINAL state's asserts, which no correct intermediate "
                    "solution can satisfy"
                )

            if (
                step.oracle.live_check is not None
                and step.oracle.live_check.enabled
                and not self.verifier.live_check.enabled
            ):
                raise ValueError(
                    f"step {step.name!r}: oracle.live_check.enabled=true but "
                    "verifier.live_check.enabled is false at the spec level. A "
                    "step can only ever narrow the spec-level live check, never "
                    "introduce one — the spec level is what carries "
                    "hand_authored/agent_role_name/concurrency_mode, and a live "
                    "check without those would ship the generated "
                    "not-implemented stub as this step's oracle (SCHEMA.md §5)"
                )

            if step.instruction.per_arm is not None:
                for arm_name in ("awscdk", "hcl_raw", "terraconstructs"):
                    if (
                        getattr(step.instruction.per_arm, arm_name) is not None
                        and arm_name not in enabled
                    ):
                        raise ValueError(
                            f"step {step.name!r}: instruction.per_arm.{arm_name} "
                            "is set but that arm is not enabled"
                        )

            if step.pre_invoke is not None and step.pre_invoke.deploy_prior:
                if index == 0:
                    raise ValueError(
                        f"step {step.name!r} is the FIRST step and cannot "
                        "declare pre_invoke.deploy_prior — there is no prior "
                        "step's work to deploy"
                    )
                missing = [
                    arm
                    for arm in sorted(enabled)
                    if getattr(
                        self.instruction.per_arm, arm
                    ).output_contract.deploy_command
                    is None
                ]
                if missing:
                    raise ValueError(
                        f"step {step.name!r} declares pre_invoke.deploy_prior "
                        f"but arm(s) {missing} leave "
                        "instruction.per_arm.<arm>.output_contract.deploy_command "
                        "unset — the generator refuses to guess a real deploy "
                        "command (SCHEMA.md §2.4/§2.6)"
                    )
        return self

    @model_validator(mode="after")
    def _deploy_command_only_with_steps(self) -> "Spec":
        """`deploy_command` is inert without a `deploy_prior` step — reject it
        rather than let a spec carry a real deploy command nothing ever runs."""
        used_by_a_step = any(
            s.pre_invoke is not None and s.pre_invoke.deploy_prior
            for s in self.steps or []
        )
        if used_by_a_step:
            return self
        declared_on = [
            arm
            for arm in ("awscdk", "hcl_raw", "terraconstructs")
            if getattr(self.instruction.per_arm, arm) is not None
            and getattr(self.instruction.per_arm, arm).output_contract.deploy_command
        ]
        if declared_on:
            raise ValueError(
                f"output_contract.deploy_command is set on arm(s) {declared_on} "
                "but no step declares pre_invoke.deploy_prior — nothing would "
                "ever run it (SCHEMA.md §2.6)"
            )
        return self

    @model_validator(mode="after")
    def _multi_step_requires_workspace_title(self) -> "Spec":
        """A multi-step spec must declare its own `workspace_title` (§0.1).

        `title` describes the whole arc and is stamped into the arm skeletons
        under `environment/` — the image the step-1 agent lives in. Making the
        field required (rather than silently defaulting to `title`, or to
        `id`) forces the spec author to *choose* a step-1-safe header instead
        of inheriting a foreshadowing one by omission. `workspace_title` is
        rejected on a single-step spec so the byte-identity guarantee for
        existing specs can never be quietly traded away for a rename.
        """
        if self.is_multi_step():
            if not (self.workspace_title or "").strip():
                raise ValueError(
                    "a spec with `steps:` must declare `workspace_title` "
                    "(SCHEMA.md §0.1): `title` is stamped into every arm's "
                    "skeleton file under environment/, which the step-1 agent "
                    "reads, so a whole-arc title there foreshadows step 2 "
                    "(Amendment 26 §7 rule 2)"
                )
        elif self.workspace_title is not None:
            raise ValueError(
                "workspace_title is only meaningful on a multi-step spec "
                "(SCHEMA.md §0.1) — a single-step spec stamps `title` "
                "verbatim into its skeletons"
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
