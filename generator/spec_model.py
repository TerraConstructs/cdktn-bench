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

# Same directory; every entry point puts generator/ on sys.path first. Imported
# at spec-LOAD time because SeedLiveAssert's falsifiability rule is about the
# COMPILED jq filter, not the JSONPath text, and because compiling at load
# turns an untranslatable `jsonpath` into a spec error rather than a
# generation-time crash three commands later.
from jsonpath_jq import jsonpath_to_jq

# The two STATIC tiers, and the only tiers a generated tests/static_tiers.sh
# can run: "0" (the arm's own toolchain plus jq-compiled structural asserts)
# and "1" (the hand-authored Rego bundle).
TierStr = Literal["0", "1"]
# "live": a catch whose mistake is invisible to EVERY static tier by
# construction -- the only discriminating signal comes from a real AWS API
# call made by the scenario's hand-authored tests/live_check.py
# (docs/apigw-redeploy-mechanics.md; DECISIONS.md Amendment 34).
# "teardown": a catch whose mistake survives every static tier AND the live
# check, and is discriminated only by the generator-injected destroy of
# `verifier.teardown` -- an agent's configuration that applies green and tears
# down dirty (specs/SCHEMA.md §5.2; DECISIONS.md Amendment 41). Only a GATING
# teardown may be named, which `Spec._teardown_tier_catch_requires_gating_teardown`
# enforces.
CatchTierStr = Literal["0", "1", "live", "teardown"]
# "hcl_modules" is the fourth arm: Terraform composed from `terraform-aws-modules`
# registry modules, gated per spec like terraconstructs (DECISIONS.md Amendment 46,
# which makes module use an ARM rather than a scenario treatment because it changes
# the authoring substrate and must be judged by identical metrics per arm). Its
# image, module delivery and plan normaliser land later; `gen.ARMS_PENDING_IMAGE`
# is what refuses to emit it until then.
Arm = Literal["awscdk", "hcl_raw", "terraconstructs", "hcl_modules"]

ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{([A-Za-z0-9_.\-]+)\}\}")

# --------------------------------------------------------------------------
# §0.1 AGENT-VISIBLE IDENTITY -- the deny-list (identity separation, DECISIONS.md
# Amendment 28 addendum).
#
# THE RULE: the spec `id` is OPERATOR-FACING and may name the pitfall; every
# name the AGENT can see must describe the CURRENT-STEP GOAL only. The leak
# test is one question: does this name reveal more than the step's own prompt
# does? The patterns below are the mechanical half of that question, enforced
# at spec-load time so a leaking `workspace_id`/`workspace_title` is refused
# rather than noticed by a test several regenerations later.
#
# Every separator-bearing pattern matches `-`, `_`, a space, or nothing: an id
# like `apigw-redeploy` reaches the agent when a sweep greps `re-deploy` only.
# Ordinary change-request and domain vocabulary is DELIBERATELY absent
# ("rename", "deploy", "security group", "retention", "route") -- that is what
# a prompt legitimately asks for, and banning it would ban the scenarios.
#
# TWO CLASSES, with genuinely different scopes; collapsing them makes a sweep
# either go blind or cry wolf.
#
#   MECHANISM/META  names the fix, the diagnosis, or the benchmark's own
#                   machinery. Banned on EVERY agent-visible surface at every
#                   point in a scenario's life. Even a multi-step scenario's
#                   last prompt may not say `create_before_destroy`: that is
#                   the answer, not the request.
#
#   FORESHADOWING   names something a LATER step introduces. Banned only on
#                   surfaces the FIRST step can read -- `environment/` and the
#                   first prompt -- and legitimate afterwards: step 02's prompt
#                   IS a change request and does ask for a re-deploy.
AGENT_MECHANISM_DENY_PATTERNS: tuple[str, ...] = (
    # --- mechanism: names the fix instead of the request (brownfield) --------
    r"create[ _-]?before[ _-]?destroy",
    r"\blifecycle\b",
    r"\bperpetual\b",
    r"flip[ _-]?flop",
    r"\breplacements?\b",
    r"\breplaced?\b",
    r"\breplacing\b",
    r"\bre[ _-]?creat(e|es|ed|ing|ion)\b",
    r"\bin[ _-]?use\b",
    r"\bexplicitly[ _-]?named\b",
    r"\bname[ _-]?(collision|conflict)\b",
    r"\balready exists\b",
    r"\bdrift(s|ed|ing)?\b",
    r"\bidempoten(t|ce|cy)\b",
    r"\bstale\b",
    # --- meta: names the benchmark's own machinery to its subject -----------
    r"\bpitfalls?\b",
    r"\bgotchas?\b",
    r"\btraps?\b",
    r"\blatent\b",
    r"\bpoisoned?\b",
    r"\bbrownfield\b",
    r"\bfind the bug\b",
    r"\bfix the (bug|mistake)\b",
    r"\breview this (config|configuration)\b",
    r"\bworkspace[ _-]?seed\b",
    r"\bseed[ _-]?asserts?\b",
    r"\banswer[ _-]?key\b",
)

AGENT_FORESHADOW_DENY_PATTERNS: tuple[str, ...] = (
    # names a LATER step from a surface an EARLIER step's agent can read
    r"\bre[ _-]?deploy(s|ed|ing|ment|ments)?\b",
    r"\bre[ _-]?appl(y|ies|ied)\b",
    r"\bstep[ _-]?(2|two|02)\b",
    r"\bday[ _-]?(2|two)\b",
    r"\bsecond[ _-]?(deploy|apply|pass|step|prompt)\b",
    r"\bnext[ _-]?step\b",
    r"\blater[ _-]?step\b",
    r"\bfollow[ _-]?up\b",
    r"\bsubsequent\b",
    r"\bchange[ _-]?request\b",
    r"\biteration\b",
)

# The union -- what an agent-visible IDENTITY (`workspace_id`,
# `workspace_title`) is validated against. Both are stamped into
# `environment/`, i.e. into the first-step surface, so both classes apply.
AGENT_IDENTITY_DENY_PATTERNS: tuple[str, ...] = (
    AGENT_MECHANISM_DENY_PATTERNS + AGENT_FORESHADOW_DENY_PATTERNS
)


def identity_deny_hits(
    text: str,
    extra_vocab: tuple[str, ...] | list[str] = (),
    *,
    foreshadowing: bool = True,
) -> list[str]:
    """Every deny-list pattern this piece of AGENT-VISIBLE text matches.

    `foreshadowing=False` scans only the MECHANISM/META class -- for a surface
    that no earlier step can reach (a final step's own prompt), where naming
    the work being asked for is not a leak but the point.

    `extra_vocab` carries the scenario's own `agent_deny_vocab` (§0.1): plain
    substrings, matched case-insensitively, that this particular scenario has
    declared must not reach its agent before it gets there on its own. Global
    patterns are regexes; a per-scenario entry is a literal, because a spec
    author writing down "the words that would give my trap away" should not
    have to write a regex. It is scoped with the foreshadowing class, since
    that is what a scenario's own reserved vocabulary always is: material a
    later step (or the agent's own investigation) is supposed to introduce.
    """
    low = text.lower()
    patterns = AGENT_MECHANISM_DENY_PATTERNS + (
        AGENT_FORESHADOW_DENY_PATTERNS if foreshadowing else ()
    )
    hits = [p for p in patterns if re.search(p, low)]
    if foreshadowing:
        hits += [v for v in extra_vocab if v.lower() in low]
    return hits


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


# The reason an `arms.hcl_modules` block carries when a spec never writes one.
# Omitting the block is the corpus-wide default, so the default reason must state
# the gap the same way a hand-written `enabled: false` reason does (SCHEMA.md §1).
HCL_MODULES_DEFAULT_REASON = (
    "no module-based reference or per-catch fixtures authored for this scenario "
    "yet; the arm's module delivery and plan normaliser are unbuilt "
    "(docs/design/tf-modules-arm.md)"
)


@_strict
class HclModulesArm(BaseModel):
    """`arms.hcl_modules`, modelled exactly like `TerraconstructsArm`: a plain
    `enabled` bool and a `reason` required in both directions. The whole block
    may be omitted, which is a disabled arm carrying
    `HCL_MODULES_DEFAULT_REASON` -- terraconstructs has no such default because
    every spec predates it and states its own coverage claim."""

    enabled: bool = False
    reason: str = HCL_MODULES_DEFAULT_REASON

    @model_validator(mode="after")
    def _reason_nonempty(self) -> "HclModulesArm":
        if not self.reason or not self.reason.strip():
            raise ValueError(
                "arms.hcl_modules.reason is required in both directions "
                "(enabled and disabled) — see SCHEMA.md §1"
            )
        return self


@_strict
class Arms(BaseModel):
    awscdk: Literal[True]
    hcl_raw: Literal[True]
    terraconstructs: TerraconstructsArm
    hcl_modules: HclModulesArm = Field(default_factory=HclModulesArm)

    def enabled_arms(self) -> list[Arm]:
        arms: list[Arm] = ["awscdk", "hcl_raw"]
        if self.terraconstructs.enabled:
            arms.append("terraconstructs")
        if self.hcl_modules.enabled:
            arms.append("hcl_modules")
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
    # SCHEMA.md §2.6: the REAL deploy command for this arm, run by the harness
    # under staged credentials for `steps[].pre_invoke.deploy_prior` or
    # `workspace_seed.deploy`. Spec-declared per arm, never inferred from an
    # arm->command map: guessing is how a harness action silently deploys the
    # wrong tree or the wrong stack. gen.py hard-errors if a consumer asks for
    # it and any enabled arm leaves it unset.
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
    hcl_modules: PerArm | None = None


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
        for arm_name in ("awscdk", "hcl_raw", "terraconstructs", "hcl_modules"):
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

# Mirrors generator/gen.py::ARM_BOOTSTRAP_FILE. Duplicated rather than imported
# because gen.py imports THIS module; keep in sync by hand.
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
# §2.7 workspace_seed -- the BROWNFIELD (poisoned-workspace) starting state
# (docs/design/poisoned-workspace-design.md; DECISIONS.md Amendment 28).
#
# A spec with NO `workspace_seed` key generates byte-identically to a spec that
# has no such field; every gen.py branch for it is `if spec.workspace_seed:`-
# guarded to keep that so.
#
# What it IS: the per-arm body shipped AS `output_contract.entry_file`'s
# content, replacing §2.4's empty `TODO(agent)` skeleton -- working, green,
# cross-arm-equivalent IaC already carrying a latent pitfall. AGENT-WRITABLE
# (0o644), because it is the file the agent is asked to change. `seeded_files`
# (§2.5) are the opposite: 0o444 read-only reference inputs. The two blocks
# stay separate because their permissions and semantics are opposites.
#
# What it is NOT: a hint. The seed must synth/plan GREEN (proved per arm by
# `make seed-parity`) and must carry no comment, name or structure that
# signposts the trap. `_SEED_COMMENT_BANNED_TOKENS` below is the mechanical
# half; the real rule is a review-time obligation (SCHEMA.md §2.7).
# --------------------------------------------------------------------------

# Tokens that must never appear in a COMMENT line of a seed body. Two families:
#   (a) editorial markers a real production config would not carry, which tell
#       the agent this file is bench scaffolding and invite meta-reasoning
#       about planted traps -- including the generator's own skeleton banner,
#       so this also enforces "a workspace_seed spec must not ALSO ship the
#       empty stub";
#   (b) the most common way a seed leaks its own answer: naming the Terraform
#       lifecycle meta-argument that fixes it.
# Matched case-insensitively, on comment lines only: a seed legitimately
# carries `description` text, and a reference solution legitimately contains
# `create_before_destroy` in real code (this list never sees one).
_SEED_COMMENT_BANNED_TOKENS = (
    "TODO",
    "FIXME",
    "XXX",
    "HACK",
    "NOTE:",
    "CAREFUL",
    "GOTCHA",
    "CREATE_BEFORE_DESTROY",
    "CREATEBEFOREDESTROY",
    "EMPTY ON PURPOSE",
    "GENERATED SKELETON",
    "GENERATED ENTRYPOINT",
    # The regenerate hint the skeleton banners close with. Bare `MAKE GEN`,
    # not `MAKE GEN SPEC=`: §0.1 keeps the spec filename out of every
    # agent-visible stamp, so the longer token would never match.
    "MAKE GEN",
    "GENERATOR/GEN.PY",
)

# A comment line, for the three languages a seed body can be written in
# (HCL `#`, TS `//`, and the inside of a TS/JSDoc block comment `*` or `/*`).
_COMMENT_LINE_RE = re.compile(r"^\s*(#|//|/\*|\*)")

# Matches the `terraform [<global flags>] plan` SUBCOMMAND, not the literal
# string "terraform plan": terraform accepts global flags between binary and
# subcommand (`terraform -chdir=... plan`), and a substring test would exempt
# that real invocation from `Spec._brownfield_plan_must_not_refresh`.
#
# Must agree with generator/tests/test_seed_deploy.py::_TF_PLAN: this pattern
# speaks for the spec FIELD, that one for the emitted BYTES, and only the
# emitted-bytes test covers arms whose plan command the spec never carries.
_TF_PLAN_RE = re.compile(r"\bterraform\b(?:\s+-\S+)*\s+plan\b")


def _seed_comment_violations(body: str) -> list[str]:
    """Every banned token found in a COMMENT line of `body`, in order."""
    found: list[str] = []
    for line in body.splitlines():
        if not _COMMENT_LINE_RE.match(line):
            continue
        upper = line.upper()
        for token in _SEED_COMMENT_BANNED_TOKENS:
            if token in upper and token not in found:
                found.append(token)
    return found


@_strict
class SeedAssert(BaseModel):
    """One behavioural fact the seed must satisfy on every arm it applies to.

    Reuses `StructuralAssert`'s vocabulary verbatim -- same `op`/`expected`
    table (§4.2), same `{cfn,tf}_jsonpath` split, same
    `generator/jsonpath_jq.py` compilation, resolved by the same `tests/ops.py`
    a real trial's tier-0 runs. A second path language would be a new drift
    surface for zero gain.

    No `tier` field, unlike `StructuralAssert`: a seed assert is never graded
    during a trial. It is a GENERATION-TIME parity gate run by
    `make seed-parity`, never by `tests/static_tiers.sh`.
    """

    name: str
    description: str
    applies_to: list[Arm] = Field(
        default_factory=lambda: ["awscdk", "hcl_raw", "terraconstructs"]
    )
    # Back-reference to `catches[].name`; at least one seed assert per spec must
    # set it (`Spec._workspace_seed_wellformed`). Without it a seed can drift
    # into being NON-poisoned -- still green, still parity-clean, no longer
    # carrying the pitfall the scenario measures -- and nothing would notice.
    pins_catch: str | None = None
    cfn_jsonpath: str | None = None
    tf_jsonpath: str | None = None
    # The same nine ops as `StructuralAssert` at the TYPE level: one table, one
    # translator, one evaluator. Three are rejected in `_wellformed` below with
    # a message explaining why, so an author who copied an op out of
    # `oracle.structural_asserts` (where all nine are legal) is told what
    # differs here rather than handed a bare "input should be one of ...".
    op: Literal[
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
        "absent_or_eq", "not_regex",
    ]
    expected: object = None

    @model_validator(mode="after")
    def _jsonpaths_required_per_applies_to(self) -> "SeedAssert":
        if not self.applies_to:
            raise ValueError(f"seed_assert {self.name!r}: applies_to must be non-empty")
        if "awscdk" in self.applies_to and not self.cfn_jsonpath:
            raise ValueError(
                f"seed_assert {self.name!r}: cfn_jsonpath required because "
                "'awscdk' is in applies_to"
            )
        if (
            "hcl_raw" in self.applies_to or "terraconstructs" in self.applies_to
        ) and not self.tf_jsonpath:
            raise ValueError(
                f"seed_assert {self.name!r}: tf_jsonpath required because a "
                "TF-shaped arm is in applies_to"
            )
        needs_expected = self.op in {
            "eq", "in", "contains", "regex", "set_eq", "absent_or_eq", "not_regex"
        }
        if needs_expected and self.expected is None:
            raise ValueError(
                f"seed_assert {self.name!r}: op={self.op!r} requires 'expected'"
            )
        if not needs_expected and self.expected is not None:
            raise ValueError(
                f"seed_assert {self.name!r}: op={self.op!r} must not set 'expected'"
            )
        return self


@_strict
class SeedExtraFile(BaseModel):
    """An additional WRITABLE (0o644) file the seed ships alongside `entry_file`.

    Same path rules as `SeededFile` (§2.5); the difference is permission and
    ownership. A `seeded_files` entry is a read-only reference input; this is
    part of the existing configuration the agent may legitimately edit. Per-arm,
    because a multi-file layout is an arm-specific authoring choice.
    """

    path: str
    content: str

    @model_validator(mode="after")
    def _path_and_content_sane(self) -> "SeedExtraFile":
        if not self.content.strip():
            raise ValueError(
                f"workspace_seed.extra_files entry {self.path!r}: content must be non-empty"
            )
        if self.path.startswith("/"):
            raise ValueError(
                f"workspace_seed.extra_files entry {self.path!r}: path must be "
                "relative (no leading '/') -- SCHEMA.md §2.7"
            )
        if any(part == ".." for part in self.path.split("/")):
            raise ValueError(
                f"workspace_seed.extra_files entry {self.path!r}: path must not "
                "contain '..' segments (workspace escape) -- SCHEMA.md §2.7"
            )
        if self.path in _KNOWN_BOOTSTRAP_FILES:
            raise ValueError(
                f"workspace_seed.extra_files entry {self.path!r}: collides with a "
                f"known non-agent-owned bootstrap filename "
                f"{sorted(_KNOWN_BOOTSTRAP_FILES)} -- SCHEMA.md §2.7"
            )
        if _seed_comment_violations(self.content):
            raise ValueError(
                f"workspace_seed.extra_files entry {self.path!r}: comment line(s) "
                f"contain {_seed_comment_violations(self.content)} -- a seeded file "
                "is presented to the agent as ordinary existing configuration and "
                "must read like one (SCHEMA.md §2.7)"
            )
        return self


@_strict
class PerArmSeedBodies(BaseModel):
    """`workspace_seed.entry_file` -- one hand-authored body per ENABLED arm.

    A per-arm map, not one document: no derivation path exists between the three
    (no public CDK->TF synthesizer; docs/scenario-candidates.md). Hand-authoring
    per arm is the same discipline `solution/solve.sh` (§8.2 point 8) and
    `generator/tests/fixtures/<id>/<arm>/<entry_file>` already use.

    Each body is written VERBATIM as that arm's `output_contract.entry_file`,
    with no generator header or wrapper, so gen.py::seed_entry_body checks it
    still satisfies its arm's structural contract (`export class ScenarioStack`
    on the TS arms, no second `provider "aws"` block on hcl_raw).
    """

    awscdk: str | None = None
    hcl_raw: str | None = None
    terraconstructs: str | None = None


@_strict
class PerArmSeedExtraFiles(BaseModel):
    awscdk: list[SeedExtraFile] = Field(default_factory=list)
    hcl_raw: list[SeedExtraFile] = Field(default_factory=list)
    terraconstructs: list[SeedExtraFile] = Field(default_factory=list)


# The ops from SCHEMA.md §4.2's nine-op table whose compiled jq filter is TRUE
# on zero resolved nodes -- i.e. the ops that PASS on a completely empty AWS
# account. Legal on a `StructuralAssert`, where "this key is absent from the
# template" is a falsifiable fact about an artifact that definitely exists;
# REJECTED on a `SeedLiveAssert`, where the question is whether the artifact --
# the account state -- exists at all.
#
# REJECTING THESE DOES NOT MAKE A LIVE ASSERT FALSIFIABLE. It closes one of two
# known routes to a free pass; the other, a `jsonpath` that names a collection
# instead of iterating it, is closed in `SeedLiveAssert._wellformed`. Neither
# rule is a decision procedure.
_VACUOUS_ON_AN_EMPTY_ACCOUNT = frozenset({"not_exists", "absent_or_eq", "not_regex"})


@_strict
class SeedLiveAssert(BaseModel):
    """One fact about the REAL AWS ACCOUNT that must hold after the harness has
    deployed the seed and BEFORE the agent's first token (SCHEMA.md §2.7.1).

    The anti-vacuity gate, and a different instrument from `SeedAssert`, which
    never enters a container: a `seed_assert` is a GENERATION-time parity gate
    (`make seed-parity`) against the offline workspace, answering "do the three
    seeds declare the same system?", while this is resolved at TRIAL time inside
    the agent container against a real `aws` CLI response, answering "does the
    account actually hold it?".

    Why it is mandatory: a live oracle can pass for FREE on a never-deployed
    account (docs/brownfield-seed-not-deployed.md -- "no security group named
    `internal-services-ssm-endpoint` remains" is vacuously true of an empty
    account). A contradicted live assert ABORTS the trial in `_prepare`, so
    that vacuous pass is unreachable.

    ARM-AGNOSTIC by design (no `applies_to`): the account does not know which
    arm produced its resources -- the same principle that keeps
    `tests/live_check.py` byte-identical across arms.

    `op`/`expected` reuse `StructuralAssert`'s nine-op table (§4.2) and
    `generator/jsonpath_jq.py` compilation. One `jsonpath`, not a `{cfn,tf}`
    pair: an AWS API response has no arm-shaped dialect.
    """

    name: str
    description: str
    # argv tokens appended to `aws`, as a LIST -- never a shell string; the
    # generator single-quotes each token, so no quoting or word-splitting
    # question arises. --profile, --region and --output are harness-owned and
    # rejected below rather than silently overridden.
    aws: Annotated[list[str], Field(min_length=1)]
    jsonpath: str
    op: Literal[
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
        "absent_or_eq", "not_regex",
    ]
    expected: object = None
    # Back-reference to `catches[].name`, meaning "the named catch's LIVE oracle
    # is vacuous unless this fact holds before the agent starts". At least one
    # live assert per spec must set it (`Spec._workspace_seed_deploy_coverage`);
    # without it these asserts drift into proving that SOMETHING got deployed
    # rather than that the POISONED thing did.
    pins_catch: str | None = None

    @model_validator(mode="after")
    def _wellformed(self) -> "SeedLiveAssert":
        if not self.name.strip():
            raise ValueError("workspace_seed.deploy.live_asserts: name must be non-empty")
        if not self.jsonpath.strip() or not self.jsonpath.startswith("$"):
            raise ValueError(
                f"seed live assert {self.name!r}: jsonpath must be non-empty and "
                "start with '$' -- it is compiled by generator/jsonpath_jq.py, "
                "the same translator oracle.structural_asserts uses (SCHEMA.md "
                "§2.7.1/§4.2)"
            )
        # THE PATH HALF of the falsifiability narrowing: the compiled filter
        # must contain at least one `.[]` stage, so the JSONPath ITERATES a
        # collection rather than naming it. Naming one hands even `exists` a
        # node on an empty account, letting a whole live proof pass with
        # nothing deployed. A conservative SHAPE rule, not a decision
        # procedure, and it rejects some falsifiable paths as collateral --
        # See docs/generator.md#seed-live-assert-falsifiability.
        try:
            compiled = jsonpath_to_jq(self.jsonpath)
        except ValueError as exc:
            raise ValueError(
                f"seed live assert {self.name!r}: jsonpath {self.jsonpath!r} "
                f"cannot be compiled by generator/jsonpath_jq.py ({exc}). It is "
                "baked into the emitted pre_invoke.sh as a jq filter at "
                "generation time, so an untranslatable path is a spec error, "
                "not a generator crash (SCHEMA.md §2.7.1/§4.2)"
            ) from exc
        stages = [s.strip() for s in compiled.split("|")]
        if not any(s == ".[]" for s in stages):
            raise ValueError(
                f"seed live assert {self.name!r}: jsonpath {self.jsonpath!r} "
                f"compiles to {compiled!r}, which never ITERATES a collection "
                "-- it names one. A path that resolves to the CONTAINER gives "
                "even `exists` one node on a completely EMPTY account (jq: "
                "`[ .SecurityGroups ]` on `{\"SecurityGroups\":[]}` is `[[]]`, "
                "length 1), so the whole live proof can pass with nothing "
                "deployed -- the exact vacuity this mechanism exists to close "
                "(docs/brownfield-seed-not-deployed.md). Descend into the "
                "collection: use `[*]` or a `[?(...)]` filter segment, e.g. "
                "`$.SecurityGroups[*].GroupName` rather than `$.SecurityGroups`. "
                "This is a conservative SHAPE rule, not a proof of "
                "falsifiability (SCHEMA.md §2.7.1)"
            )
        for token in self.aws:
            if not token or not token.strip():
                raise ValueError(
                    f"seed live assert {self.name!r}: empty `aws` argv token"
                )
            if "\n" in token or "\r" in token:
                raise ValueError(
                    f"seed live assert {self.name!r}: `aws` argv token {token!r} "
                    "contains a newline -- each token is emitted single-quoted on "
                    "one line of the generated pre_invoke.sh"
                )
            if "'" in token:
                raise ValueError(
                    f"seed live assert {self.name!r}: `aws` argv token {token!r} "
                    "contains a single quote -- the generator emits each token "
                    "single-quoted, and there is no reason for an AWS CLI "
                    "argument to need one (SCHEMA.md §2.7.1)"
                )
        if self.aws[0].startswith("-"):
            raise ValueError(
                f"seed live assert {self.name!r}: the first `aws` argv token "
                f"({self.aws[0]!r}) is a flag -- it must be the SERVICE name "
                "(e.g. 'ec2'), because the generator emits `aws <tokens>`"
            )
        for banned in ("--profile", "--region", "--endpoint-url", "--output"):
            for token in self.aws:
                if token == banned or token.startswith(banned + "="):
                    raise ValueError(
                        f"seed live assert {self.name!r}: `aws` argv token "
                        f"{token!r} is harness-owned. --profile is set by the "
                        "staged credentials file, --region by the generated "
                        "script's own AWS_DEFAULT_REGION export, --output is "
                        "always json (the compiled jq filter assumes it), and "
                        "--endpoint-url would point the proof somewhere other "
                        "than the account under test (SCHEMA.md §2.7.1)"
                    )
        # Same op table and expected-ness rule as
        # SeedAssert._jsonpaths_required_per_applies_to: one rule, three consumers.
        needs_expected = self.op in {
            "eq", "in", "contains", "regex", "set_eq", "absent_or_eq", "not_regex"
        }
        if needs_expected and self.expected is None:
            raise ValueError(
                f"seed live assert {self.name!r}: op={self.op!r} requires 'expected'"
            )
        if not needs_expected and self.expected is not None:
            raise ValueError(
                f"seed live assert {self.name!r}: op={self.op!r} must not set 'expected'"
            )
        # THE OP HALF of the falsifiability narrowing (the PATH half is above).
        # Three of the nine ops, and `set_eq` with an empty `expected`, PASS on
        # zero resolved nodes, so a live proof built from them is satisfied by
        # an empty account. Rejected on EVERY live assert, not only the
        # `pins_catch`-bearing one: an operator reads them all as one proof.
        # See docs/generator.md#seed-live-assert-falsifiability.
        if self.op in _VACUOUS_ON_AN_EMPTY_ACCOUNT:
            raise ValueError(
                f"seed live assert {self.name!r}: op={self.op!r} PASSES on zero "
                "resolved nodes, i.e. on a completely EMPTY account, so it can "
                "never contradict a seed that failed to deploy. A live assert "
                "exists to make the trial ABORT when the account does not hold "
                "the seed; one that cannot fail is the same vacuity "
                "docs/brownfield-seed-not-deployed.md was filed for, moved one "
                "level up. Assert the POSITIVE fact instead (exists / eq / in / "
                "contains / regex / set_eq with a non-empty `expected`) "
                "-- SCHEMA.md §2.7.1"
            )
        if self.op == "set_eq" and isinstance(self.expected, list) and not self.expected:
            raise ValueError(
                f"seed live assert {self.name!r}: op='set_eq' with an EMPTY "
                "`expected` is 'the account holds none of these', which passes "
                "on an empty account exactly as `not_exists` does. Same rule, "
                "same reason (SCHEMA.md §2.7.1)"
            )
        return self


@_strict
class WorkspaceSeedDeploy(BaseModel):
    """`workspace_seed.deploy` -- turn the premise's "it is already deployed in
    this account" from a claim into a fact (SCHEMA.md §2.7.1).

    Presence makes the generator emit `pre_invoke/{pre_invoke.sh,ops.py}`
    into every enabled arm's task dir. `AwsBenchSingleStepTrial._prepare` runs it
    inside the AGENT container, after the container is up and before the agent's
    first token, with `~/.aws/credentials` staged for
    `[scenario].pre_invoke_role_name`. No runner change is needed; a multi-step
    brownfield spec reaches the same `_prepare` through its MRO
    (harbor/trial/multi_step.py overrides `_run`/`_prepare_step`, never
    `_prepare`).

    Omitted, a brownfield spec generates byte-identically to §2.7 without it.
    """

    # Becomes task.toml's TASK-level `[pre_invoke] timeout_sec`. aws-bench's
    # default of 600.0 is far too short for a real apply plus an interface VPC
    # endpoint reaching `available`. NOT scaled by `--timeout-multiplier`
    # (`_run_phase_script` passes it straight to ScriptRunner), so size it for
    # the slowest runner you will ever use: a seed timeout ABORTS the trial.
    timeout_sec: float = 1800.0
    # Overrides `[scenario].pre_invoke_role_name`. Default (None) is the AGENT's
    # own role, `verifier.live_check.agent_role_name`, and that is a rule: a
    # seed the harness can deploy must be a seed the agent can change. Deploying
    # under the broader OrganizationAccountAccessRole fallback can create
    # resources the agent's role cannot modify or delete, turning a harness
    # privilege asymmetry into a fake agent failure (DECISIONS.md Amendment 24).
    role_name: str | None = None
    # THREE rules, none of which proves an assert can fail. min_length=1 is the
    # counting half: there is always at least one live assert. The two in
    # `SeedLiveAssert._wellformed` stop the count being satisfiable for free,
    # each removing one known vacuous shape -- the OP rule (`not_exists` /
    # `absent_or_eq` / `not_regex` / `set_eq: []` pass on zero resolved nodes)
    # and the PATH rule (a `jsonpath` naming a collection rather than iterating
    # it resolves to one node, the empty container, so `exists` passes too).
    # Each is pinned by an executed test in generator/tests/test_seed_deploy.py
    # that runs the REJECTED shape against an empty-account fixture and shows it
    # passing, so no rule outlives its justification.
    live_asserts: Annotated[list[SeedLiveAssert], Field(min_length=1)]

    @model_validator(mode="after")
    def _wellformed(self) -> "WorkspaceSeedDeploy":
        if self.timeout_sec <= 0:
            raise ValueError(
                "workspace_seed.deploy.timeout_sec must be > 0 (SCHEMA.md §2.7.1)"
            )
        names = [a.name for a in self.live_asserts]
        if len(names) != len(set(names)):
            raise ValueError(
                "workspace_seed.deploy.live_asserts has duplicate names"
            )
        return self


@_strict
class WorkspaceSeed(BaseModel):
    premise: str
    entry_file: PerArmSeedBodies
    extra_files: PerArmSeedExtraFiles = Field(default_factory=PerArmSeedExtraFiles)
    seed_asserts: Annotated[list[SeedAssert], Field(min_length=1)]
    # SCHEMA.md §2.7.1. Optional; omitted, generation is byte-identical to a
    # spec without the field. Set, the harness DEPLOYS this seed for real before
    # the agent phase and PROVES it landed
    # (docs/design/single-step-seed-deploy.md).
    deploy: WorkspaceSeedDeploy | None = None

    def body_for(self, arm: Arm) -> str | None:
        return getattr(self.entry_file, arm)

    def extras_for(self, arm: Arm) -> list[SeedExtraFile]:
        return getattr(self.extra_files, arm)

    @model_validator(mode="after")
    def _premise_and_bodies_nonempty(self) -> "WorkspaceSeed":
        if not self.premise.strip():
            raise ValueError(
                "workspace_seed.premise must be non-empty -- it is the "
                "arm-agnostic, human-readable equivalence claim for the three "
                "seeds AND the sentence the agent reads (SCHEMA.md §2.7)"
            )
        for arm in ("awscdk", "hcl_raw", "terraconstructs"):
            body = getattr(self.entry_file, arm)
            if body is None:
                continue
            if not body.strip():
                raise ValueError(
                    f"workspace_seed.entry_file.{arm}: seed body must be non-empty "
                    "-- an empty seed is the greenfield skeleton, which is what "
                    "this block exists to replace (SCHEMA.md §2.7)"
                )
            violations = _seed_comment_violations(body)
            if violations:
                raise ValueError(
                    f"workspace_seed.entry_file.{arm}: comment line(s) contain "
                    f"{violations}. A seed is presented to the agent as ordinary "
                    "existing team configuration: it must carry no editorial "
                    "marker a real production file would not have, no generator "
                    "skeleton banner, and above all no mention of the mechanism "
                    "that fixes the pitfall (SCHEMA.md §2.7, DECISIONS.md "
                    "Amendment 28 §3)"
                )
        names = [a.name for a in self.seed_asserts]
        if len(names) != len(set(names)):
            raise ValueError("workspace_seed.seed_asserts has duplicate names")
        return self


# --------------------------------------------------------------------------
# §3 catches
# --------------------------------------------------------------------------


@_strict
class PredictedTierCaught(BaseModel):
    awscdk: CatchTierStr
    hcl: CatchTierStr
    # Both overrides mean the same thing: `hcl` speaks for the TF-shaped arms as
    # a group, and an override names the tier for one of them when that arm's own
    # substrate decides the catch earlier or later. On hcl_modules the mover is a
    # module default or an unexposed input rather than a typed TS surface
    # (SCHEMA.md §3, DECISIONS.md Amendment 46).
    terraconstructs_override: CatchTierStr | None = None
    hcl_modules_override: CatchTierStr | None = None


@_strict
class Catch(BaseModel):
    name: str
    taxonomy: Literal[
        "typed-value-trap", "graph-dependency", "nested-attribute", "anti-L2"
    ]
    description: str
    predicted_tier_caught: PredictedTierCaught
    # Which enabled arms this catch's mistake is even POSSIBLE on; defaults to
    # all three. gates/oracle_falsifiability.py::check_arm requires a
    # `solution/broken/<name>/solve.sh` fixture only for the arms listed here:
    # some mistakes cannot be reproduced on an L2 arm without a manual escape
    # hatch (hand-omitting a TF `triggers` block has no CDK/terraconstructs L2
    # equivalent -- the L2 always computes one), and demanding a fixture nobody
    # can meaningfully author would make the gate lie.
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
        # A structural assert is compiled into the arm's own
        # tests/static_tiers.sh, so the only tiers it may name are the ones
        # that script can run. Stated here as well as in TierStr so widening
        # that alias for some future host-side tier cannot silently admit it
        # into a generated verifier (SCHEMA.md §4.2).
        if self.tier not in ("0", "1"):
            raise ValueError(
                f"structural_assert {self.name!r}: tier must be '0' or '1' "
                f"(got {self.tier!r}) -- those are the only tiers "
                "tests/static_tiers.sh runs (SCHEMA.md §4.2)"
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
        # The member/set ops are defined over a list and the pattern ops over a
        # string (SCHEMA.md §4.2). jq coerces rather than refusing -- `index`
        # with a string argument silently becomes a SUBSTRING search, so a
        # scalar `expected` on `in` grades as something the author did not
        # write -- and the Rego backend cannot coerce at all: a mistyped
        # `expected` there is an unresolvable assert. Refusing at spec load is
        # the only place the author sees it.
        for ops, wanted, label in (
            ({"in", "set_eq"}, list, "a list"),
            ({"regex", "not_regex"}, str, "a string"),
        ):
            if self.op in ops and not isinstance(self.expected, wanted):
                raise ValueError(
                    f"structural_assert {self.name!r}: op={self.op!r} requires "
                    f"{label} 'expected', got {type(self.expected).__name__}"
                )
        return self


@_strict
class Oracle(BaseModel):
    intent: str
    structural_asserts: list[StructuralAssert]
    rego_hints: list[str] = Field(default_factory=list)
    cfn_guard_hints: list[str] = Field(default_factory=list)
    # Which engine grades tier-"1" on the `awscdk` arm (specs/SCHEMA.md §4.5).
    # "rego" is the only value: `opa eval` over the arm's synthesized
    # CloudFormation template with this scenario's
    # `oracles/rego-cfn/<id>/policy.rego` (CFN-shaped, distinct from the
    # TF-shaped `oracles/rego/<id>/policy.rego` the other arms are graded by).
    # The field is kept so each spec states its grader where its oracle is
    # defined; `validate_awscdk_tier1_engine` below rejects the retired
    # `cfn_guard` value with the reason it was retired.
    awscdk_tier1_engine: Literal["rego"] = "rego"
    # Which engine grades tier-"0" on EVERY arm (specs/SCHEMA.md §4.5.1). The
    # asserts, their paths and their ops are unchanged either way -- the same
    # YAML entries are compiled to jq or to Rego from one grammar.
    #
    #   "jq" (DEFAULT) -- each cfn_jsonpath/tf_jsonpath becomes a jq filter
    #       (generator/jsonpath_jq.py) carried in tests/tier0.py's assert
    #       table and applied by tests/ops.py. The default is the incumbent, so
    #       selecting an engine is never needed to keep a task regenerating
    #       byte-identically.
    #   "rego" -- the same asserts are compiled to tests/tier0.rego
    #       (generator/jsonpath_rego.py) and evaluated by one `opa eval`, the
    #       engine tier-1 already runs. The three-valued outcome (held /
    #       contradicted / unresolvable) and the `== summary:` line are
    #       identical; what changes is that no bash sits between the spec and
    #       the verdict.
    #
    # Flipping this on a spec is only sound while both backends agree on every
    # assert of every fixture, which `make tier0-parity`
    # (gates/tier0_parity.py) checks per spec and `make ci` runs per spec.
    tier0_engine: Literal["jq", "rego"] = "jq"
    # HCL symbol resolution for the hcl_raw arm's tier-1 (specs/SCHEMA.md §4.6;
    # docs/design/conftest-hcl-traversal-spike.md).
    #
    # False (DEFAULT) -- `opa eval` is handed `terraform show -json` plan JSON
    #     and nothing else; every already-generated task regenerates
    #     BYTE-IDENTICALLY.
    # True -- the hcl_raw arm's tests/static_tiers.sh also parses the agent's
    #     own `*.tf` / `*.tf.json` with `hcl2json` (pinned + sha256-verified in
    #     arms/hcl-raw/environment/Dockerfile) and merges them into that plan
    #     document under one reserved key, `_hcl`, before `opa eval`. The engine
    #     does not change and `input` stays byte-identical for every
    #     pre-existing rule -- only new rules read `_hcl`. The resolver library
    #     `oracles/rego/lib/hcl_traversal.rego` is copied into the task's tests/
    #     and loaded with a second `-d`.
    #
    # WHY A SPEC NEEDS IT: `terraform show -json` does not emit `locals`, so a
    # plan's `.configuration...references` dead-ends on `local.x` -- it records
    # that an argument was SET to that symbol, not what the symbol HOLDS. A
    # tier-1 grading a dedicated single-ARN argument slot (an invoke
    # permission's `source_arn`, a topic policy's `arn`) cannot otherwise tell a
    # DRY hoist from a laundered wrong-resource ARN.
    #
    # SCOPE: hcl_raw only. awscdk resolves TS variables at synth and names its
    # referent in an `Fn::GetAtt`; cdktn does the same and emits no `locals`
    # block, so neither arm has anything to resolve. Setting this with hcl_raw
    # disabled is a spec bug, not a no-op, and is rejected below.
    hcl_traversal: bool = False

    @model_validator(mode="before")
    @classmethod
    def _cfn_guard_engine_is_retired(cls, data: object) -> object:
        # cfn-guard 3.2.0 cannot express a cross-resource logical-id join, so
        # every intent that states one had to be proxied, and a proxy grades a
        # byte-equivalent Terraform solution the opposite way. OPA/Rego now
        # grades tier 1 on every arm (ROADMAP.md M8); cfn-guard stays installed
        # in the awscdk image as a capability an agent may run, never as the
        # oracle. Caught here rather than by the Literal so the message says
        # what replaced the value and why.
        if isinstance(data, dict) and data.get("awscdk_tier1_engine") == "cfn_guard":
            raise ValueError(
                "oracle.awscdk_tier1_engine: 'cfn_guard' is retired. OPA/Rego "
                "grades tier 1 on every arm, including awscdk, so that one "
                "policy language and one identity domain (logical ids) make "
                "equal-strictness cross-arm grading structural rather than a "
                "review promise -- ROADMAP.md M8 and DECISIONS.md Amendment 45. "
                "Use 'rego' and hand-author oracles/rego-cfn/<id>/policy.rego."
            )
        return data

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
    enabled: bool
    module: str = "tests/live_check.py"
    # True: `module` (tests/live_check.py) is HAND-AUTHORED, so gen.py's
    # write_tests step is destructive-safe for it -- the same convention
    # solution/solve.sh has (SCHEMA.md §8.2 point 8). Required whenever
    # `enabled`, or the generated not-implemented stub would silently ship as
    # this scenario's live check.
    hand_authored: bool = False
    # Override the generator's defaults for the task's agent role and
    # `[concurrency] mode`. None keeps `QALocalInvocationApplicationRole` /
    # "read-only".
    #
    # A LIVE CHECK DOES NOT IMPLY "mutating", and nothing here couples them.
    # `[concurrency] mode` describes what the TRIAL does to the account, not
    # whether the verifier calls AWS: a live check built only from evaluating
    # APIs -- `stepfunctions test-state`, which creates nothing -- leaves the
    # account exactly as it found it, so "read-only" is the correct and
    # cheaper mode for it (no post-trial account reset, and such trials co-run
    # under the reader-preferring scenario lock). Only `workspace_seed.deploy`
    # forces "mutating", and that rule lives on Spec, where the seed is
    # (Spec._seed_deploy_requires_live_and_mutating).
    agent_role_name: str | None = None
    concurrency_mode: Literal["read-only", "mutating"] | None = None
    # False (default): live_check.py runs observationally and never affects
    # /logs/verifier/reward.txt (SCHEMA.md §5's non-gating invariant). True:
    # gen.py::build_test_sh folds its outcome into reward.txt with AND,
    # fail-closed -- final reward is 1.0 iff the static tiers say 1.0 AND the
    # outcome is "pass"; "not_verifiable" and "fail_stale" both give 0.0.
    # Required by a scenario whose motivating catch is `predicted_tier_caught:
    # "live"`, since no static tier can observe it and a non-gating live check
    # would let it cost a real trial nothing.
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
class Idempotence(BaseModel):
    """§5.1 -- the IDEMPOTENCE tier: "after the agent's solution is green, does
    the agent's own toolchain still report a pending change?"

    A **live** tier, not a static one, and that is a blocking fact rather than a
    design preference: `terraform plan -detailed-exitcode` returns 2 (changes
    present) for ANY plan against empty state, so the generated static tier --
    which plans an empty working directory -- can never produce a meaningful
    second-plan signal offline (docs/design/poisoned-workspace-design.md §5.1).
    Hence `enabled: true` REQUIRES `live_check.enabled: true` (Spec-level
    validator): no apply => no state => nothing to be idempotent about.

    Per-arm commands are injected UNCONDITIONALLY by the generator, never read
    from a spec key -- the same "cannot go missing because a spec author forgot
    a YAML key" discipline `TERRACONSTRUCTS_BUILD_COMMAND` already uses. On the
    awscdk arm the command is `cdk diff --fail` against the DEPLOYED stack, not
    a second synth: CDK synth is deterministic, so a synth/template self-diff is
    vacuous by construction and would silently hand that arm a free pass (memo
    §5.2).

    `gating` copies `live_check.gating`'s contract byte-for-byte: fail-closed AND
    semantics -- final reward is 1.0 iff the static tiers say 1.0 AND the live
    check passes AND this tier's outcome is "converged". `pending_changes` and
    `not_verifiable` both downgrade to 0.0; the tier is never silently skipped
    into a pass (SCHEMA.md §5.1).
    """

    enabled: bool = False
    gating: bool = False

    @model_validator(mode="after")
    def _gating_requires_enabled(self) -> "Idempotence":
        if self.gating and not self.enabled:
            raise ValueError(
                "verifier.idempotence.gating=true requires enabled=true -- a "
                "tier that never runs cannot gate reward"
            )
        return self


@_strict
class Teardown(BaseModel):
    """§5.2 -- the TEARDOWN tier: when the agent's own toolchain is asked to
    destroy what it deployed, does the destroy succeed?

    It GRADES the agent's teardown; it is NOT a cleanup mechanism. aws-bench's
    own post-trial reset returns the account to baseline afterwards whatever
    this tier reports, so turning the tier into the cleanup path would delete
    that reset's independent guarantee (SCHEMA.md §5.2).

    LIVE-ONLY: `enabled: true` requires `live_check.enabled: true`
    (`Spec._teardown_requires_live_check`), because an offline destroy of an
    empty working directory exits 0 having removed nothing.

    Per-arm destroy commands are injected by the generator
    (`gen.py::TEARDOWN_COMMAND`), never read from a spec key, so the tier
    cannot go missing because a spec author forgot a YAML key.
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Run the generator-injected destroy after the live check and after "
            "the idempotence tier, on the final step only, and record "
            "clean/destroy_failed/not_verifiable in "
            "/logs/verifier/teardown-result.json. Requires "
            "verifier.live_check.enabled."
        ),
    )
    gating: bool = Field(
        default=False,
        description=(
            "AND-compose this tier's outcome into the reward, fail-closed: only "
            "'clean' keeps 1.0; destroy_failed and not_verifiable both write "
            "0.0. Requires enabled."
        ),
    )

    @model_validator(mode="after")
    def _gating_requires_enabled(self) -> "Teardown":
        if self.gating and not self.enabled:
            raise ValueError(
                "verifier.teardown.gating=true requires enabled=true -- a "
                "tier that never runs cannot gate reward"
            )
        return self


@_strict
class Verifier(BaseModel):
    budget: VerifierBudget = Field(default_factory=VerifierBudget)
    live_check: LiveCheck
    # Optional, default disabled -> byte-identical generation for every spec
    # that predates this field (SCHEMA.md §5.1).
    idempotence: Idempotence = Field(default_factory=Idempotence)
    # Optional, default disabled -> byte-identical generation for every spec
    # that predates this field (SCHEMA.md §5.2).
    teardown: Teardown = Field(default_factory=Teardown)


# --------------------------------------------------------------------------
# §2.6 steps -- multi-step decomposition (top-level, sibling of `instruction`).
# docs/prompt-decomposition-audit.md; DECISIONS.md Amendments 26/27.
#
# A spec with NO `steps` key generates byte-identically to a spec predating the
# field; every gen.py branch for steps is `if spec.steps:`-guarded, rather than
# a refactor of the single-step path, to keep that so.
#
# What a step is FOR: revealing the second intent only when it is due. A single
# prompt saying "build X, then change it to Y" measures day-1 authoring with
# perfect foreknowledge -- the one condition a real day-2 change never has.
# --------------------------------------------------------------------------

STEP_NAME_RE = re.compile(r"^[0-9]{2}-[a-z][a-z0-9-]*$")


@_strict
class StepPerArm(BaseModel):
    """Per-arm, per-STEP override of `instruction.per_arm.<arm>.language_line`.

    Exists because a spec-level language line can itself foreshadow, and does so
    on ONE arm only -- an arm-parity defect on top of a foreshadowing one. An
    awscdk line naming the day-2 integration type leaks step 2 into step 1's
    prompt for awscdk agents alone (docs/prompt-decomposition-audit.md).
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

    `deploy_prior: true` is the default shape (DECISIONS.md Amendment 26): the
    harness deploys the previous step's IaC so this step's prompt lands on an
    account really in the state it assumes. It emits
    `steps/<name>/pre_invoke/pre_invoke.sh` running the arm's own
    `output_contract.deploy_command`, which the generator refuses to guess.

    Omitting `pre_invoke` entirely is the explicit opt-out, for a scenario
    where the agent's own deploy loop IS the measurement.

    `timeout_sec`: the per-step pre_invoke inherits the TASK-level
    `[pre_invoke].timeout_sec`, whose aws-bench default of 600 s a real deploy
    comfortably exceeds, so gen.py emits it explicitly, sized to the LARGEST
    value any step declares.
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
    # None -> gen.py's default: 1.0 on every NON-final step, so step N+1's
    # prompt never fires unless step N verified green (DECISIONS.md Amendment
    # 26); omitted on the final step, which has nothing left to gate. An
    # ungated intermediate step must say `min_reward: 0.0` explicitly, so "no
    # gate" is never the result of forgetting a key.
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
    # (main.tf / lib/scenario-stack.ts / bin/app.ts / main.ts) under
    # `environment/` -- the image the agent lives in from step 1 onward. Absent
    # = `title`, which every single-step greenfield spec relies on for
    # byte-identical emission. REQUIRED on multi-step and brownfield specs,
    # where a natural `title` describes the whole arc or the change itself and
    # so foreshadows what the agent must not yet know. See
    # `_workspace_title_required_where_header_is_prompt_surface`.
    workspace_title: str | None = None
    # §0.1, optional. The AGENT-VISIBLE scenario identity -- `workspace_title`'s
    # sibling for every place the generator stamps a NAME rather than a
    # sentence: the terraconstructs `ScenarioStack` construct id and `gridUUID`,
    # and therefore `cdktf.out/stacks/<id>/`, which the agent sees in its own
    # `npx cdktn synth` output and in `preflight.sh`.
    #
    # `id` is OPERATOR-FACING and MAY name the pitfall, which is what makes it
    # useful in `specs/`, `oracles/`, `task.toml [metadata]` and a results
    # table. `workspace_id` is what the agent is allowed to know: the workspace
    # it has been asked to work in, named for the CURRENT step's goal.
    #
    # Absent = `id`. REQUIRED on multi-step and brownfield specs, the same two
    # forms `workspace_title` is required on and for the same reason. The
    # deny-list (`_agent_visible_identity_is_deny_list_clean`) runs against the
    # RESOLVED value either way, so a greenfield spec whose id would leak is
    # refused until it declares an explicit `workspace_id`.
    workspace_id: str | None = None
    # §0.1, optional. This scenario's OWN trap/foreshadowing vocabulary on top
    # of the global `AGENT_IDENTITY_DENY_PATTERNS`: plain substrings that must
    # never reach an agent-visible surface. Declared in the spec, not in a test
    # module keyed by scenario id, so the words that would give a trap away are
    # reviewed in the same file as the trap.
    # `generator/tests/test_scenario_identity.py` sweeps the emitted bytes.
    agent_deny_vocab: list[str] = Field(default_factory=list)
    difficulty: Annotated[int, Field(ge=1, le=3)]
    services: Annotated[list[str], Field(min_length=1)]
    arms: Arms
    instruction: Instruction
    seeded_files: list[SeededFile] = Field(default_factory=list)
    # §2.7, optional. Absent = the GREENFIELD shape: `entry_file` ships §2.4's
    # empty `TODO(agent)` skeleton. Set = the BROWNFIELD shape: `entry_file`
    # ships this block's per-arm seed body, writable, and the prompt is a
    # change request on it.
    workspace_seed: WorkspaceSeed | None = None
    catches: Annotated[list[Catch], Field(min_length=1)]
    oracle: Oracle
    verifier: Verifier
    # §2.6, optional. Absent = the single-step shape, byte-identical to a spec
    # predating the field. A non-empty list makes this a MULTI-STEP task
    # (`[[steps]]` in task.toml, run by cdktn_bench.trial.CdktnMultiStepTrial).
    steps: list[Step] | None = None
    provenance: Provenance

    def is_multi_step(self) -> bool:
        return bool(self.steps)

    def is_brownfield(self) -> bool:
        """True iff this scenario's workspace starts from working config that
        already carries a latent pitfall (§2.7), rather than §2.4's empty
        skeleton. Brownfield tokens-to-green is a SEPARATE metric stratum from
        greenfield -- never pooled (DECISIONS.md Amendment 28 §6)."""
        return self.workspace_seed is not None

    def workspace_header(self) -> str:
        """The one-line title stamped into the arm skeleton files under
        `environment/`. See the `workspace_title` field comment: single-step
        greenfield specs keep `title` verbatim (byte-identity); multi-step and
        brownfield specs must declare a safe alternative."""
        return self.workspace_title or self.title

    def workspace_identity(self) -> str:
        """The scenario NAME the agent is allowed to see (§0.1).

        Every generator stamp-site that lands under `environment/` -- or that
        must agree with one, such as the synthesized stack directory the tier-0
        artifact is read from -- uses this. `id` stays operator-facing and is
        free to name the pitfall; nothing derived from it reaches the image.
        """
        return self.workspace_id or self.id

    def identity_leaks(self, text: str, *, foreshadowing: bool = True) -> list[str]:
        """Deny-list hits for a piece of THIS scenario's agent-visible text.

        `foreshadowing=False` for a surface no earlier step can read -- see
        `identity_deny_hits`.
        """
        return identity_deny_hits(
            text, tuple(self.agent_deny_vocab), foreshadowing=foreshadowing
        )

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
    def _hcl_modules_per_arm_required_iff_enabled(self) -> "Spec":
        """The same both-directions rule `_terraconstructs_per_arm_required_iff_enabled`
        applies: an enabled arm with no `per_arm` entry has no language line or
        output contract to generate from, and a `per_arm` entry for a disabled arm
        is authored text nothing reads."""
        hm_enabled = self.arms.hcl_modules.enabled
        hm_per_arm = self.instruction.per_arm.hcl_modules
        if hm_enabled and hm_per_arm is None:
            raise ValueError(
                "arms.hcl_modules.enabled is true but "
                "instruction.per_arm.hcl_modules is missing (SCHEMA.md §2)"
            )
        if not hm_enabled and hm_per_arm is not None:
            raise ValueError(
                "instruction.per_arm.hcl_modules is set but "
                "arms.hcl_modules.enabled is false — remove one or the other"
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
                self.instruction.per_arm.hcl_modules,
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
    def _workspace_seed_wellformed(self) -> "Spec":
        """Everything §2.7 requires of a `workspace_seed:` block, in one place."""
        seed = self.workspace_seed
        if seed is None:
            return self

        enabled = set(self.arms.enabled_arms())
        declared_bodies = {
            arm
            for arm in ("awscdk", "hcl_raw", "terraconstructs")
            if getattr(seed.entry_file, arm) is not None
        }
        if declared_bodies != enabled:
            missing = sorted(enabled - declared_bodies)
            extra = sorted(declared_bodies - enabled)
            raise ValueError(
                "workspace_seed.entry_file must declare exactly one seed body per "
                f"ENABLED arm (enabled={sorted(enabled)}): missing {missing}, "
                f"declared-but-disabled {extra}. A disabled arm carrying a seed is "
                "a spec error, not a silent skip -- and an enabled arm without one "
                "would start from the empty greenfield skeleton while its siblings "
                "start from working config, which is not a comparable trial "
                "(SCHEMA.md §2.7)"
            )

        entry_files = {
            arm: getattr(self.instruction.per_arm, arm).output_contract.entry_file
            for arm in enabled
        }
        seeded_paths = {f.path for f in self.seeded_files}
        for arm in sorted(enabled):
            for extra_file in seed.extras_for(arm):
                if extra_file.path == entry_files[arm]:
                    raise ValueError(
                        f"workspace_seed.extra_files.{arm} entry {extra_file.path!r} "
                        "is that arm's own output_contract.entry_file -- the seed "
                        "body already owns it (SCHEMA.md §2.7)"
                    )
                if extra_file.path in seeded_paths:
                    raise ValueError(
                        f"workspace_seed.extra_files.{arm} entry {extra_file.path!r} "
                        "collides with a seeded_files path: one is written 0o644 "
                        "(writable task content) and the other 0o444 (read-only "
                        "reference input), so a collision is a silent permission "
                        "fight (SCHEMA.md §2.7)"
                    )
        for arm in ("awscdk", "hcl_raw", "terraconstructs"):
            if arm not in enabled and seed.extras_for(arm):
                raise ValueError(
                    f"workspace_seed.extra_files.{arm} is set but that arm is not enabled"
                )
            paths = [f.path for f in seed.extras_for(arm)]
            if len(paths) != len(set(paths)):
                raise ValueError(
                    f"workspace_seed.extra_files.{arm} has duplicate path values"
                )

        catch_names = {c.name for c in self.catches}
        pinned: set[str] = set()
        for a in seed.seed_asserts:
            unknown_arms = set(a.applies_to) - enabled
            if unknown_arms:
                raise ValueError(
                    f"seed_assert {a.name!r}: applies_to includes disabled/unknown "
                    f"arm(s) {sorted(unknown_arms)}"
                )
            if a.pins_catch is not None:
                if a.pins_catch not in catch_names:
                    raise ValueError(
                        f"seed_assert {a.name!r}: pins_catch={a.pins_catch!r} names "
                        f"no declared catch (have {sorted(catch_names)})"
                    )
                pinned.add(a.pins_catch)
        if not pinned:
            raise ValueError(
                "workspace_seed.seed_asserts: at least one entry must set "
                "`pins_catch` naming the catch whose MECHANISM lives in the seed. "
                "Without that back-reference the seed can drift into being "
                "non-poisoned -- still green, still parity-clean, no longer "
                "carrying the pitfall the scenario exists to measure -- and no "
                "gate would notice (SCHEMA.md §2.7, design memo §4.1 point 3)"
            )
        return self

    @model_validator(mode="after")
    def _workspace_seed_deploy_coverage(self) -> "Spec":
        """`workspace_seed.deploy.live_asserts` must PIN a catch (§2.7.1).

        Same shape and same reason as `seed_asserts[].pins_catch`, one phase
        later. A live assert without a back-reference can drift into proving
        that SOMETHING got deployed -- a VPC exists, an apply exited 0 -- rather
        than that the POISONED thing got deployed. That is the same vacuity this
        entire mechanism exists to close, moved one level up, and it would look
        exactly as green.
        """
        seed = self.workspace_seed
        if seed is None or seed.deploy is None:
            return self

        catch_names = {c.name for c in self.catches}
        pinned: set[str] = set()
        for a in seed.deploy.live_asserts:
            if a.pins_catch is None:
                continue
            if a.pins_catch not in catch_names:
                raise ValueError(
                    f"seed live assert {a.name!r}: pins_catch={a.pins_catch!r} "
                    f"names no declared catch (have {sorted(catch_names)})"
                )
            pinned.add(a.pins_catch)
        if not pinned:
            raise ValueError(
                "workspace_seed.deploy.live_asserts: at least one entry must "
                "set `pins_catch`, naming the catch whose LIVE oracle is "
                "VACUOUS unless that fact holds before the agent starts. "
                "Without the back-reference these asserts drift into proving "
                "that something got deployed rather than that the poisoned "
                "thing got deployed -- the same vacuity "
                "docs/brownfield-seed-not-deployed.md recorded, one level up "
                "(SCHEMA.md §2.7.1)"
            )
        return self

    @model_validator(mode="after")
    def _hcl_traversal_requires_hcl_raw(self) -> "Spec":
        """`oracle.hcl_traversal` is an hcl_raw-only capability.

        The merge step it turns on is emitted into the hcl_raw arm's
        tests/static_tiers.sh and nowhere else, so setting it on a spec that
        does not enable hcl_raw is a spec bug that would silently do nothing
        -- not a harmless flag. Rejected loudly rather than ignored, the same
        way `terraconstructs_per_arm_required_iff_enabled` treats its own
        arm-conditional field.
        """
        if self.oracle.hcl_traversal and not self.arms.hcl_raw:
            raise ValueError(
                "oracle.hcl_traversal is true but arms.hcl_raw is disabled — "
                "the HCL pre-parse is emitted only into the hcl_raw arm's "
                "generated tests/static_tiers.sh (specs/SCHEMA.md §4.6), so "
                "this flag would do nothing at all on this spec"
            )
        return self

    @model_validator(mode="after")
    def _idempotence_requires_live_check(self) -> "Spec":
        """§5.1: no apply => no state => nothing to be idempotent about.

        `terraform plan -detailed-exitcode` is 2 against empty state, always, so
        an idempotence tier on a synth/plan-only spec could only ever report
        `pending_changes` -- i.e. fail every trial, including a perfect one.
        """
        if self.verifier.idempotence.enabled and not self.verifier.live_check.enabled:
            raise ValueError(
                "verifier.idempotence.enabled=true requires "
                "verifier.live_check.enabled=true -- the idempotence tier reads "
                "the state the agent's own deploy left behind, and a spec with no "
                "live phase never produces one (SCHEMA.md §5.1)"
            )
        return self

    @model_validator(mode="after")
    def _teardown_requires_live_check(self) -> "Spec":
        """§5.2: no apply => nothing to destroy.

        An offline `terraform destroy` / `cdk destroy` against an empty working
        directory exits 0 having removed nothing, which would report `clean` for
        a trial that deployed nothing at all.
        """
        if self.verifier.teardown.enabled and not self.verifier.live_check.enabled:
            raise ValueError(
                "verifier.teardown.enabled=true requires "
                "verifier.live_check.enabled=true -- the teardown tier destroys "
                "what the agent's own deploy left behind, and a spec with no "
                "live phase never produces one (SCHEMA.md §5.2)"
            )
        return self

    @model_validator(mode="after")
    def _teardown_tier_catch_requires_gating_teardown(self) -> "Spec":
        """A catch may name the teardown tier only where that tier can cost a
        reward.

        `predicted_tier_caught: "teardown"` says: every static tier passes this
        mistake, the live check passes it, and only the destroy separates it
        from a correct solution. With the tier disabled nothing runs that
        destroy; with it enabled but observational the verdict is written to
        /logs/verifier/teardown-result.json and the trial still scores 1.0 --
        so the catch would be recorded as graded while costing nothing, which
        is the "grades the proxy" failure the tier exists to end (SCHEMA.md
        §5.2).
        """
        td = self.verifier.teardown
        named = sorted(
            c.name
            for c in self.catches
            if "teardown"
            in {
                c.predicted_tier_caught.awscdk,
                c.predicted_tier_caught.hcl,
                c.predicted_tier_caught.terraconstructs_override,
                c.predicted_tier_caught.hcl_modules_override,
            }
        )
        if named and not (td.enabled and td.gating):
            raise ValueError(
                f"catches {named} declare predicted_tier_caught 'teardown', "
                "which requires verifier.teardown.enabled=true AND "
                "verifier.teardown.gating=true -- a tier that does not run, or "
                "runs without gating, cannot cost a trial any reward, so it "
                "cannot be the tier that catches anything (SCHEMA.md §5.2)"
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
            if is_final and step.min_reward is not None:
                raise ValueError(
                    f"final step {step.name!r} must OMIT min_reward — the "
                    "trial-level oracle is the gate. `min_reward` gates the "
                    "NEXT step's prompt (Amendment 26 §3), and the last step "
                    "has no successor to gate, so gen.py's emitter drops the "
                    "value silently (build_steps_toml only writes min_reward "
                    "for non-final steps). Rejected here rather than dropped, "
                    "for the same reason oracle.structural_asserts is "
                    "rejected on the final step: a schema-accepted key with "
                    "no effect reads as a gate that exists "
                    "(DECISIONS.md Amendment 26 §3 / SCHEMA.md §2.6)"
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
    def _deploy_command_has_a_consumer(self) -> "Spec":
        """`deploy_command` is inert without a consumer — reject it rather than
        let a spec carry a real deploy command nothing ever runs.

        There are exactly TWO legal consumers, and they mean the same thing:
        "run this arm's deploy command against /app/project under staged
        credentials". They differ only in WHEN.

          * `steps[].pre_invoke.deploy_prior` (§2.6) — before a LATER step's
            agent, deploying the PRIOR step's work.
          * `workspace_seed.deploy` (§2.7.1) — before the agent phase of a
            brownfield trial, deploying the SEED, so the premise "it is already
            deployed in this account" is a fact rather than a claim.

        Reusing one per-arm field for both is deliberate: inventing a second
        `seed_deploy_command` would give a spec two places to say the same thing
        and one place for them to drift apart.
        """
        used_by_a_step = any(
            s.pre_invoke is not None and s.pre_invoke.deploy_prior
            for s in self.steps or []
        )
        used_by_the_seed = (
            self.workspace_seed is not None and self.workspace_seed.deploy is not None
        )
        if used_by_a_step or used_by_the_seed:
            return self
        declared_on = [
            arm
            for arm in ("awscdk", "hcl_raw", "terraconstructs", "hcl_modules")
            if getattr(self.instruction.per_arm, arm) is not None
            and getattr(self.instruction.per_arm, arm).output_contract.deploy_command
        ]
        if declared_on:
            raise ValueError(
                f"output_contract.deploy_command is set on arm(s) {declared_on} "
                "but no step declares pre_invoke.deploy_prior and "
                "workspace_seed.deploy is not set — nothing would ever run it "
                "(SCHEMA.md §2.6 / §2.7.1)"
            )
        return self

    @model_validator(mode="after")
    def _seed_deploy_requires_deploy_command(self) -> "Spec":
        """The generator must never GUESS a real deploy command.

        Same rule, same message shape as `_steps_wellformed`'s existing
        `deploy_prior` check: guessing is how a harness action silently deploys
        the wrong tree, the wrong stack, or the wrong app definition.
        """
        if self.workspace_seed is None or self.workspace_seed.deploy is None:
            return self
        missing = [
            arm
            for arm in sorted(self.arms.enabled_arms())
            if getattr(self.instruction.per_arm, arm).output_contract.deploy_command
            is None
        ]
        if missing:
            raise ValueError(
                "workspace_seed.deploy is set but arm(s) "
                f"{missing} leave "
                "instruction.per_arm.<arm>.output_contract.deploy_command "
                "unset — the generator refuses to guess a real deploy "
                "command (SCHEMA.md §2.4/§2.6/§2.7.1)"
            )
        return self

    @model_validator(mode="after")
    def _seed_deploy_requires_live_and_mutating(self) -> "Spec":
        """THREE account-level hazards, each one YAML key away from being
        forgotten, and none with any other gate.

        All three are hard errors because the failure is invisible at
        generation time and expensive at run time. `gating` matters most: it is
        the same "spend with no measurement" as `enabled: false`, and unlike
        `enabled` it is FALSE by default, so it is reached by omission.
        """
        if self.workspace_seed is None or self.workspace_seed.deploy is None:
            return self
        live = self.verifier.live_check
        if not live.enabled:
            raise ValueError(
                "workspace_seed.deploy is set but verifier.live_check.enabled "
                "is false — a seed deployed into a real account with no live "
                "oracle is spend with no measurement. The whole reason to make "
                "the brownfield premise TRUE is that the live oracle's "
                "discriminating assertion stops being satisfiable vacuously "
                "(docs/brownfield-seed-not-deployed.md, SCHEMA.md §2.7.1)"
            )
        if not live.gating:
            raise ValueError(
                "workspace_seed.deploy is set but verifier.live_check.gating "
                "is false -- the live oracle's verdict never reaches "
                "reward.txt (gen.py::build_test_sh folds `.outcome` in only "
                "under SPEC_LIVE_CHECK_GATING=true), so this is the same "
                "'spend with no measurement' as enabled=false, reached by "
                "omission rather than by decision (gating defaults to false). "
                "A seed worth deploying into a real account is a seed whose "
                "live proof is allowed to change the score "
                "(SCHEMA.md §2.7.1/§5)"
            )
        if live.concurrency_mode != "mutating":
            raise ValueError(
                "workspace_seed.deploy is set but "
                f"verifier.live_check.concurrency_mode is "
                f"{live.concurrency_mode!r} — a seed deployed into an account "
                "with no post-trial reset contaminates it for every later "
                "trial. aws_bench/task/aws_trial.py calls "
                "_reset_scenario_account() only for ConcurrencyMode.MUTATING, "
                "so 'mutating' is what tears the seed's own VPC/subnet/SG/"
                "endpoint back down (SCHEMA.md §2.7.1, design §7)"
            )
        return self

    @model_validator(mode="after")
    def _brownfield_plan_must_not_refresh(self) -> "Spec":
        """A brownfield arm's `terraform plan` MUST carry `-refresh=false`.

        The seed is already deployed when the verifier plans, so a refreshing
        plan re-contacts AWS to reconcile EVERY seeded resource. Two ways that
        costs a perfect solution its 1.0: the refresh can report pending
        changes for reasons that have nothing to do with the agent's change,
        and it dies outright wherever an arbitrary AWS read cannot be answered
        -- the credential-free host gates run this identical `static_tiers.sh`
        against gates/aws_stub.py, which answers exactly two operations
        (`sts:GetCallerIdentity`, `states:ValidateStateMachineDefinition`).
        Either way the verifier fails on state the agent's own SUCCESSFUL apply
        created, and `workspace_seed.deploy` puts that state there on purpose,
        on every trial.

        Enforced on every `workspace_seed` spec, not only on the ones that
        declare `deploy`: a brownfield agent is asked to roll its change out,
        so its own apply produces the same state file the seed would have.

        Grading is unaffected. `-refresh=false` changes only whether the plan
        re-reads remote objects; `planned_values` still carries the full desired
        end state of every resource, unchanged ones included -- it is not a
        changeset.
        """
        if self.workspace_seed is None:
            return self
        offenders = []
        for arm in sorted(self.arms.enabled_arms()):
            plan_command = getattr(
                self.instruction.per_arm, arm
            ).output_contract.plan_command
            # Match the SUBCOMMAND, not the literal two words: gen.py splices
            # `plan_command` verbatim into hcl_raw's static_tiers.sh, and a
            # substring test lets `terraform -chdir=. plan ...` through in
            # silence, scoring every hcl-raw brownfield trial 0.0 before the
            # agent is judged.
            if not plan_command or not _TF_PLAN_RE.search(plan_command):
                continue
            if "-refresh=false" not in plan_command:
                offenders.append(arm)
        if offenders:
            raise ValueError(
                f"BROWNFIELD (§2.7) arm(s) {offenders} declare a "
                "`terraform plan` in output_contract.plan_command WITHOUT "
                "`-refresh=false`. With deploy state present in /app/project "
                "the verifier's plan re-contacts AWS to reconcile every seeded "
                "resource: it can report pending changes for reasons unrelated "
                "to the agent's change, and it dies outright under the "
                "credential-free host gates, whose gates/aws_stub.py answers "
                "two operations and no arbitrary refresh -- either way scoring "
                "a PERFECT solution 0.0. Grading is unaffected: every "
                "tf_jsonpath reads $.planned_values / $.configuration, which "
                "carry the full desired end state, not a changeset "
                "(SCHEMA.md §2.7.1/§5.1)"
            )
        return self

    @model_validator(mode="after")
    def _workspace_title_required_where_header_is_prompt_surface(self) -> "Spec":
        """`workspace_title` is REQUIRED on a multi-step spec AND on a
        brownfield one; forbidden on a plain single-step greenfield spec (§0.1).

        Both required cases are the same failure with two causes: `title` is
        stamped into the arm skeletons under `environment/` — the image the
        agent lives in from turn one — and in both forms a natural `title`
        describes something the agent is not supposed to already know.

          * MULTI-STEP: `title` describes the whole arc, so it foreshadows
            step 2 (Amendment 26 §7 rule 2, Amendment 27 §5.1).
          * BROWNFIELD (§2.7): `title` describes the CHANGE and in practice
            names the trapped property of the existing config. It reaches
            `bin/app.ts`'s CFN `description` and `main.ts`'s header on the two
            arms whose entry file is NOT the seed, leaving the third clean —
            an arm-asymmetric hint inside the very comparison the scenario
            measures. A brownfield header must describe only what the workspace
            ALREADY IS ("Internal services network"), never what is about to
            change about it or why it is interesting.

        Making the field required rather than silently defaulting to `title`
        forces the author to *choose* a safe header instead of inheriting a
        leaking one by omission. It stays rejected on a plain single-step
        greenfield spec so the byte-identity guarantee for the existing corpus
        can never be quietly traded away for a rename.
        """
        if self.is_multi_step() or self.is_brownfield():
            if not (self.workspace_title or "").strip():
                why = (
                    "`title` is stamped into every arm's skeleton file under "
                    "environment/, which the step-1 agent reads, so a "
                    "whole-arc title there foreshadows step 2 "
                    "(Amendment 26 §7 rule 2)"
                    if self.is_multi_step()
                    else "`title` is stamped into every arm's non-seed skeleton "
                    "file under environment/ (bin/app.ts's CFN description, "
                    "main.ts's header), which the agent reads on turn one, and "
                    "a brownfield title names the change — and usually the "
                    "trapped property with it (Amendment 28 §3.3)"
                )
                kind = "`steps:`" if self.is_multi_step() else "`workspace_seed:`"
                raise ValueError(
                    f"a spec with {kind} must declare `workspace_title` "
                    f"(SCHEMA.md §0.1): {why}"
                )
        elif self.workspace_title is not None:
            raise ValueError(
                "workspace_title is only meaningful on a multi-step or "
                "brownfield spec (SCHEMA.md §0.1) — a single-step greenfield "
                "spec stamps `title` verbatim into its skeletons"
            )
        return self

    @model_validator(mode="after")
    def _workspace_id_required_where_identity_is_prompt_surface(self) -> "Spec":
        """`workspace_id` is REQUIRED on a multi-step spec AND on a brownfield
        one; optional (defaulting to `id`) on a plain single-step greenfield
        spec (§0.1).

        Exactly the `workspace_title` rule, one field over, and for the same
        reason: on those two forms the scenario `id` is chosen to name the
        thing being MEASURED, and the thing being measured is what the agent
        must not be told.

          * MULTI-STEP: an id like `apigw-redeploy` IS step 2's verb, and it
            reaches `environment/app/main.ts` as the `ScenarioStack` construct
            id and `gridUUID`.
          * BROWNFIELD (§2.7): an id like `named-resource-replacement` is not
            the change request ("rename the security group to X"), it is the
            DIAGNOSIS the agent is supposed to derive from the configuration.
            It reaches two of three arms and not the third, biasing the
            cross-arm comparison the scenario exists to produce.

        Required rather than defaulted on these forms for the same reason
        `workspace_title` is: an author must CHOOSE a safe name, not inherit a
        leaking one by omission. Unlike `workspace_title` it is not REFUSED on
        a greenfield spec -- an explicit, deny-list-clean `workspace_id` is a
        legitimate thing to want anywhere -- but the deny-list below runs on
        the resolved value in every form, so a greenfield id that leaks cannot
        stay the default.
        """
        if (self.is_multi_step() or self.is_brownfield()) and not (
            self.workspace_id or ""
        ).strip():
            kind = "`steps:`" if self.is_multi_step() else "`workspace_seed:`"
            raise ValueError(
                f"a spec with {kind} must declare `workspace_id` (SCHEMA.md "
                "§0.1): the scenario `id` is stamped into the agent's own "
                "workspace (the terraconstructs ScenarioStack id/gridUUID and "
                "therefore cdktf.out/stacks/<id>/), and on these two forms the "
                "id names the pitfall — step 2's verb, or the diagnosis the "
                "agent is meant to reach on its own"
            )
        return self

    @model_validator(mode="after")
    def _workspace_id_format(self) -> "Spec":
        if self.workspace_id is not None and not ID_RE.match(self.workspace_id):
            raise ValueError(
                f"workspace_id {self.workspace_id!r} must match "
                "^[a-z][a-z0-9-]*$ (SCHEMA.md §0.1) — it becomes a construct "
                "id and a synthesized stack DIRECTORY name"
            )
        return self

    @model_validator(mode="after")
    def _agent_visible_identity_is_deny_list_clean(self) -> "Spec":
        """The RESOLVED agent-visible identity and header must both survive the
        deny-list (§0.1, `AGENT_IDENTITY_DENY_PATTERNS` + this spec's own
        `agent_deny_vocab`).

        Run on the resolved values, not on the declared ones, so that the
        DEFAULT is checked too: a single-step greenfield spec whose `id` names
        its own trap is refused here and must declare an explicit
        `workspace_id`. This is the validator that turns the old exemption
        ("scrub the spec id before scanning, it's just the id") into an
        assertion.
        """
        for field, value in (
            ("workspace_id", self.workspace_identity()),
            ("workspace_title", self.workspace_header()),
        ):
            leaked = self.identity_leaks(value)
            if leaked:
                declared = getattr(self, field) is not None
                how = (
                    f"declared `{field}`"
                    if declared
                    else f"`{field}` defaulted from `{'id' if field == 'workspace_id' else 'title'}`"
                )
                raise ValueError(
                    f"{how} is {value!r}, which matches the agent-visible "
                    f"identity deny-list {leaked} (SCHEMA.md §0.1). This value "
                    "is stamped into `environment/`, which the agent reads on "
                    "turn one — name the CURRENT step's goal, not the pitfall. "
                    f"Keep the leaking name as the operator-facing "
                    f"`{'id' if field == 'workspace_id' else 'title'}` and "
                    f"declare a neutral `{field}`."
                )
        return self

    @model_validator(mode="after")
    def _terraconstructs_artifact_path_matches_workspace_identity(self) -> "Spec":
        """The terraconstructs `artifact_path` names the SYNTHESIZED STACK
        DIRECTORY, which is named by the construct id
        `gen.py::terraconstructs_main_ts` stamps -- `workspace_identity()`,
        not `id` (§0.1).

        Checked here because a mismatch does not fail loudly: it makes every
        tier-0 assert resolve against a nonexistent plan.json and score a
        constant 0.0, INCLUDING for the reference solution.
        """
        per_arm = self.instruction.per_arm.terraconstructs
        if per_arm is None:
            return self
        expected_dir = f"cdktf.out/stacks/{self.workspace_identity()}/"
        path = per_arm.output_contract.artifact_path
        if path.startswith("cdktf.out/stacks/") and not path.startswith(expected_dir):
            raise ValueError(
                "instruction.per_arm.terraconstructs.output_contract."
                f"artifact_path is {path!r}, but the generator synthesizes this "
                f"stack into {expected_dir!r} (SCHEMA.md §0.1: the stack "
                "directory is named by `workspace_id`, falling back to `id`)"
            )
        return self

    @model_validator(mode="after")
    def _catches_taxonomy_diversity_note(self) -> "Spec":
        # Advisory only. Real seed scenarios should carry an anti-L2 catch
        # (SCHEMA.md §3), but enforcing it here would invalidate the toy
        # fixture, which SCHEMA.md §7 requires stay valid.
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
