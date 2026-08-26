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

# Same directory, and every entry point puts generator/ on sys.path before it
# imports this module (gen.py, check_reference_paths.py, gates/*, the test
# suites). Imported HERE, at spec-LOAD time, because SeedLiveAssert's
# falsifiability rule (finding A, adversarial review round 3, 2026-08-25) is a
# rule about the COMPILED jq filter, not about the JSONPath text -- and
# because compiling at load turns an untranslatable `jsonpath` into a spec
# error instead of a generation-time crash three commands later.
from jsonpath_jq import jsonpath_to_jq

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

# --------------------------------------------------------------------------
# §0.1 AGENT-VISIBLE IDENTITY — the deny-list (DECISIONS.md Amendment 28
# addendum, "identity separation").
#
# THE RULE: the spec `id` is OPERATOR-FACING and may name the pitfall; every
# name the AGENT can see must be named for the CURRENT-STEP GOAL only. The
# leak test is one question: *does this name reveal more than the step's own
# prompt does?*
#
# These patterns are the mechanical half of that question. They are the union
# of two deny-lists that used to live only in test modules -- the BROWNFIELD
# mechanism vocabulary (test_workspace_seed.py::MECHANISM_PATTERNS, Amendment
# 28 §3) and the MULTI-STEP foreshadowing grammar
# (test_multistep_emission.py::TEMPORAL_TOKENS, Amendment 27 §5.1) -- promoted
# here so a VALIDATOR can refuse a leaking `workspace_id`/`workspace_title` at
# spec-load time instead of a test noticing it three regenerations later.
#
# UNHYPHENATED VARIANTS ARE DELIBERATE. Amendment 27's sweep grepped
# `re-deploy` only, so `apigw-redeploy` -- whose id IS the step-2 trap verb --
# was stamped into every step-1 skeleton header and into the terraconstructs
# arm's `ScenarioStack` id and `gridUUID` without any test seeing it. Every
# separator-bearing pattern below therefore matches `-`, `_`, a space, or
# nothing at all.
#
# WHAT IS DELIBERATELY ABSENT: ordinary change-request and domain vocabulary --
# "rename", "deploy", "security group", "retention", "route". Those are what a
# prompt legitimately asks for. Banning them would ban the scenarios.
#
# TWO CLASSES, because they have genuinely different SCOPES -- and collapsing
# them is how a sweep either goes blind or cries wolf.
#
#   MECHANISM/META  names the fix, the diagnosis, or the benchmark's own
#                   machinery. Banned on EVERY agent-visible surface, at every
#                   point in a scenario's life. Even the last prompt of a
#                   multi-step scenario may not say `create_before_destroy`:
#                   that is the answer, not the request.
#
#   FORESHADOWING   names something a LATER step introduces. Banned on the
#                   surfaces the FIRST step can read -- `environment/` (the
#                   image, present from turn one) and the first prompt -- and
#                   legitimate afterwards. Step 02's own prompt IS a change
#                   request and does ask for a re-deploy; banning those words
#                   there would ban the scenario, and a sweep that has to be
#                   switched off for the file where the words are correct is a
#                   sweep nobody keeps running.
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
# §2.7 workspace_seed -- the BROWNFIELD (poisoned-workspace) starting state
#
# Added 2026-08-20 (task #15, docs/design/poisoned-workspace-design.md;
# DECISIONS.md Amendment 28). A spec with NO `workspace_seed` key generates
# byte-identically to before this field existed -- that regression guarantee is
# why every branch gen.py grows for it is `if spec.workspace_seed:`-guarded.
#
# What it IS: the per-arm body shipped **as** `output_contract.entry_file`'s
# content, replacing §2.4's empty `TODO(agent)` skeleton. Working, green,
# semantically-equivalent-across-arms IaC that already carries a latent
# pitfall. AGENT-WRITABLE (0o644) -- it is the file the agent is being asked to
# change. That is the exact opposite of `seeded_files` (§2.5), which are 0o444
# read-only reference inputs; the two blocks stay separate because their
# permissions and semantics are opposites.
#
# What it is NOT: a hint. The seed must synth/plan GREEN (proved per arm by
# `make seed-parity`, generator/check_reference_paths.py --seed) and must carry
# no comment, name or structure that signposts the trap. The mechanical half of
# that rule is `_SEED_COMMENT_BANNED_TOKENS` below; the real rule is a
# review-time obligation (SCHEMA.md §2.7, Amendment 28 §3).
# --------------------------------------------------------------------------

# Tokens that must never appear in a COMMENT line of a seed body. Two families:
#   (a) editorial markers a real production config would not carry and that
#       tell the agent this file is bench scaffolding, inviting meta-reasoning
#       about planted traps ("TODO", "FIXME", ... ) -- including the
#       generator's own skeleton banner text, which is also how this validator
#       enforces "a workspace_seed spec must not ALSO ship the empty stub";
#   (b) the generator-side tripwire for the most common way a seed leaks its
#       own answer: naming the Terraform lifecycle meta-argument that fixes it.
# Matched case-insensitively, comment lines only -- a seed legitimately
# contains e.g. `description` text, and a REFERENCE SOLUTION legitimately
# contains `create_before_destroy` in real code (this list never sees one).
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
    # The regenerate hint the skeleton banners close with. Kept as the bare
    # `MAKE GEN` rather than the old `MAKE GEN SPEC=`: §0.1 dropped the spec
    # filename from every agent-visible stamp, so a seed copied from a skeleton
    # would now carry the shorter form and the longer token would miss it.
    "MAKE GEN",
    "GENERATOR/GEN.PY",
)

# A comment line, for the three languages a seed body can be written in
# (HCL `#`, TS `//`, and the inside of a TS/JSDoc block comment `*` or `/*`).
_COMMENT_LINE_RE = re.compile(r"^\s*(#|//|/\*|\*)")

# `terraform [<global flags>] plan` -- the PLAN SUBCOMMAND, not the literal
# string "terraform plan" (finding G, adversarial review round 3, 2026-08-25).
# terraform accepts its global flags between the binary and the subcommand
# (`terraform -chdir=... plan`), so a substring test silently exempted a real,
# documented invocation from `Spec._brownfield_plan_must_not_refresh`.
#
# ONE owner, TWO consumers: this pattern and the one in
# generator/tests/test_seed_deploy.py::_TF_PLAN must agree, because the
# validator speaks for the spec FIELD and the test speaks for the emitted
# BYTES -- the emitted-bytes test is the only thing that covers the arms whose
# plan command the spec does not carry at all.
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

    Deliberately reuses `StructuralAssert`'s vocabulary verbatim -- same
    `op`/`expected` table (§4.2), same `{cfn,tf}_jsonpath` split, same
    `generator/jsonpath_jq.py` compilation, resolved by the SAME
    `_assert_lib.sh::assert_check` bash function a real trial's tier-0 runs. A
    second, differently-behaving path language would be a new drift surface for
    zero gain. The one field `StructuralAssert` has that this does not is
    `tier`: a seed assert is never graded during a trial -- it is a
    GENERATION-TIME parity gate (§4 of the design memo), run by
    `make seed-parity`, never by `tests/static_tiers.sh`.
    """

    name: str
    description: str
    applies_to: list[Arm] = Field(
        default_factory=lambda: ["awscdk", "hcl_raw", "terraconstructs"]
    )
    # Back-reference to `catches[].name`. At least one seed assert per spec must
    # set it (see `Spec._workspace_seed_wellformed`): without it a seed could
    # silently drift into being NON-poisoned -- still green, still parity-clean,
    # but no longer carrying the pitfall the scenario exists to measure -- and
    # nothing would notice.
    pins_catch: str | None = None
    cfn_jsonpath: str | None = None
    tf_jsonpath: str | None = None
    # SAME nine-op vocabulary as `StructuralAssert`/`SeedAssert` at the TYPE
    # level, deliberately: one table, one translator, one evaluator. Three of
    # the nine are then rejected in `_wellformed` below with a message that
    # explains WHY -- a spec author who copies an op straight out of
    # `oracle.structural_asserts` (where all nine are legal) has to be told
    # what is different HERE, not handed a bare "input should be one of ...".
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

    Same path rules as `SeededFile` (§2.5) -- the difference is only the
    permission and the ownership story: a `seeded_files` entry is a read-only
    reference input, a `workspace_seed.extra_files` entry is part of the
    existing configuration the agent may legitimately edit. Per-arm, because a
    multi-file layout is an arm-specific authoring choice (a `variables.tf`
    exists only on hcl_raw).
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

    A per-arm map, not one document: there is no derivation path between the
    three (docs/scenario-candidates.md:169-176 -- aws-cdk-rfcs #217 closed
    `not_planned`, `hashicorp/terraform-cdk` archived, no public CDK->TF
    synthesizer exists). Hand-authoring per arm is the SAME discipline this repo
    already applies to `solution/solve.sh` (§8.2 point 8) and to
    `generator/tests/fixtures/<id>/<arm>/<entry_file>`.

    Each body is written VERBATIM as that arm's `output_contract.entry_file` --
    no generator header, no wrapper. The generator therefore checks the body
    still satisfies its arm's structural contract (`export class ScenarioStack`
    on the TS arms, no second `provider "aws"` block on hcl_raw) at generation
    time; see gen.py::seed_entry_body.
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
# when the path resolves to zero nodes -- i.e. the ops that PASS on a
# completely empty AWS account. Legal on a `StructuralAssert` (where "this key
# is absent from the template" is a real, falsifiable fact about an artifact
# that definitely exists) and REJECTED on a `SeedLiveAssert`, where the whole
# question is whether the artifact -- the account state -- exists at all.
#
# REJECTING THESE DOES NOT MAKE A LIVE ASSERT FALSIFIABLE. It closes one of
# two known routes to a free pass; the other is a `jsonpath` that names a
# collection instead of iterating it, closed separately in
# `SeedLiveAssert._wellformed` (finding A, round 3, 2026-08-25). Neither rule
# is a decision procedure and this comment does not claim one.
_VACUOUS_ON_AN_EMPTY_ACCOUNT = frozenset({"not_exists", "absent_or_eq", "not_regex"})


@_strict
class SeedLiveAssert(BaseModel):
    """One fact about the REAL AWS ACCOUNT that must hold after the harness has
    deployed the seed and BEFORE the agent's first token (SCHEMA.md §2.7.1).

    This is the anti-vacuity gate, and it is a different instrument from
    `SeedAssert` -- which never enters a container at all. A `seed_assert` is a
    GENERATION-time parity gate (`make seed-parity`) resolved against the
    offline, never-deployed workspace: it answers "do the three seeds declare
    the same system?". A `SeedLiveAssert` is resolved at TRIAL time, inside the
    agent container, against a real `aws` CLI response, and answers "does the
    account actually hold it?".

    Why both are mandatory: the defect this whole mechanism exists to fix
    (docs/brownfield-seed-not-deployed.md) is an oracle that passed for FREE.
    `tests/live_check.py`'s discriminating assertion for
    named-resource-replacement is "no security group named
    `internal-services-ssm-endpoint` remains" -- which a never-deployed account
    satisfies vacuously. A contradicted live assert ABORTS the trial in
    `_prepare`, so that vacuous pass is unreachable.

    Deliberately ARM-AGNOSTIC (no `applies_to`): the account does not know which
    arm produced its resources, which is the same principle that makes
    `tests/live_check.py` byte-identical across all three arms.

    `op`/`expected` reuse `StructuralAssert`/`SeedAssert`'s vocabulary verbatim
    -- same nine-op table (§4.2), same `generator/jsonpath_jq.py` compilation,
    resolved by the SAME `_assert_lib.sh::assert_check` bash function a real
    trial's tier-0 runs. One `jsonpath`, not a `{cfn,tf}` pair: the artifact is
    an AWS API response, which has no arm-shaped dialect.
    """

    name: str
    description: str
    # argv tokens appended to `aws`, as a LIST -- never a shell string. The
    # generator single-quotes each token when it emits the call, so no quoting
    # or word-splitting question exists at any point. The harness owns
    # --profile (staged credentials), --region (the script's own export) and
    # --output (always json, because the compiled jq filter assumes it), so
    # those are rejected rather than silently overridden.
    aws: Annotated[list[str], Field(min_length=1)]
    jsonpath: str
    op: Literal[
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
        "absent_or_eq", "not_regex",
    ]
    expected: object = None
    # Back-reference to `catches[].name`. At least one live assert per spec must
    # set it (see `Spec._workspace_seed_deploy_coverage`). Meaning: "the named
    # catch's LIVE oracle is vacuous unless this fact holds before the agent
    # starts." Without it the live asserts drift into proving that SOMETHING got
    # deployed rather than that the POISONED thing got deployed -- which is the
    # same vacuity this mechanism exists to close, one level up. Mirrors
    # `SeedAssert.pins_catch` exactly.
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
        # VACUITY IS REACHABLE THROUGH THE PATH, NOT ONLY THROUGH THE OP
        # (finding A, adversarial review round 3, 2026-08-25, REPRODUCED).
        # `_VACUOUS_ON_AN_EMPTY_ACCOUNT` below rejects the three ops that pass
        # on zero resolved nodes. It does NOT make the live proof falsifiable,
        # because a `jsonpath` that stops at the CONTAINER instead of
        # descending INTO it hands even `exists` one node on an empty account:
        #
        #     $ echo '{"SecurityGroups":[]}' > /tmp/empty.json
        #     $ assert_check probe '.SecurityGroups' exists '' /tmp/empty.json
        #       PASS [probe]                                          # rc=0
        #
        # `[ .SecurityGroups ]` is `[[]]` -- length 1, and `map(select(. !=
        # null))` does not drop an empty ARRAY. So a `workspace_seed.deploy`
        # whose ENTIRE live proof passed on a completely empty account was
        # still expressible, accepted at load, emitted, and reported
        # `seed_deployed`. That is the same defect M1 was filed for, reached
        # through the other half of the assert.
        #
        # THE RULE, EXACTLY: the compiled filter must contain at least one
        # `.[]` stage -- i.e. the JSONPath must carry a `[*]` or a `[?(...)]`
        # segment and therefore ITERATE a collection rather than name it. On an
        # empty collection an iterating filter resolves to ZERO nodes, which is
        # what every accepted op needs in order to be contradictable.
        #
        # THIS IS A NARROWING, NOT A DECISION PROCEDURE, and the distinction is
        # the whole reason M1's own comment was a defect: nothing here proves a
        # path is falsifiable in general. It is a conservative SHAPE rule that
        # makes the known-vacuous shape unexpressible and rejects some
        # falsifiable paths as collateral -- notably recursive descent
        # (`$..GroupName`), which compiles to `.. | objects | .GroupName?` and
        # iterates nothing. A live assert that genuinely needs one of those
        # should widen this rule deliberately, with its own executed
        # empty-account proof, rather than have the rule quietly bent.
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
        # Copied verbatim from SeedAssert._jsonpaths_required_per_applies_to's
        # tail: one op table, one expected-ness rule, three consumers.
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
        # THE OP HALF of the falsifiability narrowing (finding M1, adversarial
        # review 2026-08-25). The PATH half is enforced above; NEITHER is a
        # decision procedure, and saying so is the point -- M1 was filed
        # against a comment that claimed a property the code did not enforce,
        # and finding A (round 3) was filed against M1's own fix for doing it
        # again. What is enforced here, exactly: three of the nine ops PASS on
        # ZERO resolved nodes (verified against gen.py::ASSERT_LIB_SH and
        # pinned by an EXECUTED test -- generator/tests/test_seed_deploy.py::
        # test_the_rejected_ops_really_do_pass_on_an_empty_account), so a spec
        # could declare a deploy whose ENTIRE live proof was satisfied by a
        # completely empty account. This rule removes that route and the path
        # rule removes the other known one; together they do not prove that an
        # accepted assert can fail. min_length=1 and `pins_catch` are counting
        # rules, not falsifiability rules.
        #
        #   not_exists   -> `($v | length) == 0`                  -- true on []
        #   absent_or_eq -> `($v | length) == 0 or ...`            -- true on []
        #   not_regex    -> `$v | all(...)`; jq's all/1 over []    -- true on []
        #
        # So they are rejected HERE, on every live assert, not merely on the
        # `pins_catch`-bearing one. Narrowing it to the pinning assert was the
        # other option and is weaker for a reason worth writing down: the
        # non-pinning entries are read by an operator as part of the same
        # proof, and one that cannot fail dilutes the verdict rather than
        # strengthening it -- "3 live asserts held" must mean three facts about
        # the account, not two facts and a tautology.
        #
        # `set_eq` needs the same treatment for a different reason: its filter
        # compares SETS, so `expected: []` is "the account holds none of these",
        # which is also true on []. Every other accepted op requires >=1
        # resolved node by construction (`exists`: length > 0; `eq`: length ==
        # 1; `in`: flattened length > 0; `contains`/`regex`: length >= 1).
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

    Presence makes the generator emit `pre_invoke/{pre_invoke.sh,_assert_lib.sh}`
    into every enabled arm's task dir. `AwsBenchSingleStepTrial._prepare` runs
    that script inside the AGENT container, after the container is up and before
    the agent's first token, with `~/.aws/credentials` staged for
    `[scenario].pre_invoke_role_name`. No runner change is needed: that code path
    already exists for every task carrying the file, and a multi-step brownfield
    spec reaches the same `_prepare` through its MRO (harbor/trial/multi_step.py
    overrides `_run`/`_prepare_step`, never `_prepare`).

    OMITTED, a brownfield spec generates exactly as it did before this field
    existed -- §2.7's byte-identity regression guarantee extends to it.
    """

    # Becomes task.toml's TASK-level `[pre_invoke] timeout_sec`. aws-bench's own
    # default is 600.0 (aws_bench/dataset/task_config.py), far too short for a
    # real apply plus an interface VPC endpoint reaching `available`.
    #
    # NOT scaled by `--timeout-multiplier`: `_run_phase_script` passes
    # `phase.timeout_sec` straight to ScriptRunner, unlike the agent/verifier
    # timeouts which go through `Trial._resolve_timeout_sec`. Size it for the
    # slowest runner you will ever use; a seed timeout ABORTS the trial.
    timeout_sec: float = 1800.0
    # Overrides `[scenario].pre_invoke_role_name`. Default (None) is
    # `verifier.live_check.agent_role_name` -- the AGENT's own role, and that is
    # a rule, not a convenience. Deploying the seed with the broader
    # OrganizationAccountAccessRole fallback could create resources the agent's
    # role cannot subsequently modify or delete, turning a harness privilege
    # asymmetry into a fake agent failure -- precisely the failure mode
    # DECISIONS.md Amendment 24 retired QADeployApplicationRole to avoid.
    # A seed the harness can deploy must be a seed the agent can change.
    role_name: str | None = None
    # THREE rules, and none of them proves an assert can fail. min_length=1 is
    # the counting half: there is always at least one live assert. The two in
    # `SeedLiveAssert._wellformed` are what stop the count being satisfiable for
    # free, each by removing ONE known vacuous shape:
    #   * the OP rule -- `not_exists` / `absent_or_eq` / `not_regex` (and
    #     `set_eq: []`) pass on zero resolved nodes (finding M1, adversarial
    #     review 2026-08-25);
    #   * the PATH rule -- a `jsonpath` that names a collection instead of
    #     iterating it resolves to ONE node, the empty container, on an empty
    #     account, so `exists` passes there too (finding A, round 3, same day).
    # What this field does NOT say, deliberately: that a live assert accepted by
    # all three is falsifiable. The comment that used to sit here claimed the
    # coupling was "structural, not a review-time convention" while the op table
    # made it a convention (M1), and M1's own replacement claimed the op rule
    # settled it while the path did not (A). Every rule above is pinned by an
    # executed test in generator/tests/test_seed_deploy.py that runs the
    # REJECTED shape against an empty-account fixture and shows it passing --
    # so no rule can outlive its justification.
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
    # SCHEMA.md §2.7.1. Optional; omitted, this spec generates byte-identically
    # to how it did before the field existed. Set, the harness DEPLOYS this seed
    # for real before the agent phase and PROVES it landed -- see
    # docs/design/single-step-seed-deploy.md.
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
    # Which engine grades tier-"1" on the `awscdk` arm (specs/SCHEMA.md §4.5;
    # ROADMAP.md M8, DECISIONS.md Amendment 29 §4). The TF-shaped arms are
    # ALWAYS graded by OPA/Rego over `terraform show -json`; this field only
    # picks what runs against awscdk's synthesized CloudFormation template.
    #
    #   "cfn_guard" (DEFAULT) -- `cfn-guard validate --data <template.json>
    #       --rules oracles/cfn-guard/<id>/policy.guard`. The default is
    #       deliberately the incumbent so every already-generated spec keeps
    #       regenerating BYTE-IDENTICALLY; nothing about an existing task dir
    #       changes by adding this field.
    #   "rego" -- `opa eval` over the SAME template, using this scenario's
    #       `oracles/rego-cfn/<id>/policy.rego` (a CFN-shaped policy, distinct
    #       from the TF-shaped `oracles/rego/<id>/policy.rego`). Chosen when
    #       the scenario's intent needs something cfn-guard 3.2.0 cannot
    #       express -- notably a cross-resource logical-id join -- or when
    #       cross-arm equal-strictness grading (Amendment 29 §4) requires one
    #       policy language across all three arms.
    awscdk_tier1_engine: Literal["cfn_guard", "rego"] = "cfn_guard"
    # HCL symbol resolution for the hcl_raw arm's tier-1 (specs/SCHEMA.md
    # §4.6; docs/design/conftest-hcl-traversal-spike.md).
    #
    # False (DEFAULT) -- unchanged, and deliberately the default so every
    #     already-generated task regenerates BYTE-IDENTICALLY. `opa eval` is
    #     handed `terraform show -json` plan JSON and nothing else.
    # True -- the hcl_raw arm's generated tests/static_tiers.sh additionally
    #     parses the agent's own `*.tf` / `*.tf.json` files with `hcl2json`
    #     (pinned + sha256-verified in arms/hcl-raw/environment/Dockerfile)
    #     and merges them into that same plan document under ONE reserved key,
    #     `_hcl`, before `opa eval` runs. The ENGINE does not change and
    #     `input` stays byte-identical for every pre-existing rule -- only new
    #     rules read `_hcl`. The shared resolver library
    #     `oracles/rego/lib/hcl_traversal.rego` is copied into the task's
    #     tests/ and loaded with a second `-d`.
    #
    # WHY A SPEC NEEDS THIS: `terraform show -json` does not emit `locals`, so
    # a plan's `.configuration...references` list dead-ends on `local.x` -- it
    # records that an argument was SET to that symbol and nothing about what
    # the symbol HOLDS. A scenario whose tier-1 grades a DEDICATED SINGLE-ARN
    # ARGUMENT SLOT (an invoke permission's `source_arn`, a topic policy's
    # `arn`) cannot tell an ordinary DRY hoist from a laundered wrong-resource
    # ARN without it; both directions of that error have been reproduced by
    # execution on a real scenario.
    #
    # SCOPE: hcl_raw only. Confirmed by synthesis on the other two arms
    # (spike memo §9) -- awscdk resolves TS variables at synth and the
    # template names its referent in an `Fn::GetAtt`, and cdktn does the same
    # and emits no `locals` block at all, so neither arm has anything to
    # resolve. Setting this true with hcl_raw disabled is therefore a spec
    # bug, not a no-op, and is rejected below.
    hcl_traversal: bool = False
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
class Verifier(BaseModel):
    budget: VerifierBudget = Field(default_factory=VerifierBudget)
    live_check: LiveCheck
    # Optional, default disabled -> byte-identical generation for every spec
    # that predates this field (SCHEMA.md §5.1).
    idempotence: Idempotence = Field(default_factory=Idempotence)


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
    # onward. Absent = `title` (every single-step GREENFIELD spec:
    # byte-identical emission). REQUIRED for a multi-step spec, because a
    # scenario `title` legitimately describes the WHOLE arc ("deploy, confirm,
    # modify, re-deploy (day-2 iteration)") and stamping that arc into the
    # first file the step-1 agent opens foreshadows step 2 just as loudly as
    # the prompt would -- DECISIONS.md Amendment 26 §7 rule 2 /
    # docs/multistep-trial-investigation.md §5 rule 2 ("never place
    # later-step material in environment/"). ALSO REQUIRED for a BROWNFIELD
    # spec (§2.7) for the same reason with a different cause: a brownfield
    # `title` describes the CHANGE and typically names the trapped property of
    # the existing config, and on the arms whose entry file is NOT the seed
    # (awscdk's bin/app.ts, terraconstructs' main.ts) it still reaches the
    # agent -- arm-asymmetrically, which is worse than uniformly. See
    # `_workspace_title_required_where_header_is_prompt_surface`.
    workspace_title: str | None = None
    # §0.1, optional. The AGENT-VISIBLE scenario identity -- the sibling of
    # `workspace_title` for every place the generator stamps a NAME rather than
    # a sentence: the terraconstructs `ScenarioStack` construct id and
    # `gridUUID` (and therefore `cdktf.out/stacks/<id>/`, which the agent sees
    # in its own `npx cdktn synth` output and in `preflight.sh`).
    #
    # `id` is OPERATOR-FACING and MAY name the pitfall -- that is what makes it
    # a useful name in `specs/`, `oracles/`, `task.toml [metadata]` and a
    # results table. `workspace_id` is what the agent is allowed to know: the
    # name of the workspace it has been asked to work in, describing the
    # CURRENT step's goal and nothing beyond it.
    #
    # Absent = `id` (every scenario whose id names only the open goal of its
    # own prompt: byte-identical emission). REQUIRED for a multi-step spec and
    # for a brownfield one -- the same two forms `workspace_title` is required
    # on, for the same reason and after the same failure: `apigw-redeploy`'s id
    # is the step-2 trap verb and `named-resource-replacement`'s id is the
    # diagnosis the agent is supposed to reach from the configuration, and both
    # were stamped into `environment/`. The deny-list
    # (`_agent_visible_identity_is_deny_list_clean`) runs against the RESOLVED
    # value either way, so a greenfield spec whose id would leak is refused
    # until it declares an explicit `workspace_id`.
    workspace_id: str | None = None
    # §0.1, optional. This scenario's OWN trap/foreshadowing vocabulary, on top
    # of the global `AGENT_IDENTITY_DENY_PATTERNS`: plain substrings that must
    # never appear on an agent-visible surface of this scenario, and which
    # `workspace_id`/`workspace_title` are validated against. Declared HERE, in
    # the spec, rather than in a test module keyed by scenario id, so the words
    # that would give a trap away are reviewed in the same file as the trap.
    # `generator/tests/test_scenario_identity.py` sweeps the real emitted bytes
    # with it.
    agent_deny_vocab: list[str] = Field(default_factory=list)
    difficulty: Annotated[int, Field(ge=1, le=3)]
    services: Annotated[list[str], Field(min_length=1)]
    arms: Arms
    instruction: Instruction
    seeded_files: list[SeededFile] = Field(default_factory=list)
    # §2.7, optional. None/absent (every spec but `named-resource-replacement`)
    # = the GREENFIELD shape: `entry_file` ships §2.4's empty `TODO(agent)`
    # skeleton, generated byte-identically to before this field existed. Set =
    # the BROWNFIELD shape: `entry_file` ships this block's per-arm seed body,
    # writable, and the prompt is a change request against it.
    workspace_seed: WorkspaceSeed | None = None
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
            for arm in ("awscdk", "hcl_raw", "terraconstructs")
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
        generation time and expensive at run time. `gating` was added by
        finding m1 (adversarial review, 2026-08-25) -- it is the same "spend
        with no measurement" as `enabled: false`, and unlike `enabled` it is
        FALSE by default, so it is reached by omission.
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
            # Finding m1 (adversarial review, 2026-08-25). `gating: false` is
            # the SAME condition `enabled: false` is rejected for above, and it
            # is the DEFAULT, so it is the one an author reaches by omission
            # rather than by decision. Non-gating, live_check.py's `.outcome`
            # never reaches reward.txt (gen.py::build_test_sh only folds it in
            # under SPEC_LIVE_CHECK_GATING=true), so the oracle whose vacuity
            # this deploy exists to close cannot change any published number:
            # the account is mutated, the money is spent, and the measurement
            # is still decorative.
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

        MEASURED, not predicted (2026-08-25). With a state file present in
        /app/project, `terraform plan` refreshes; the verifier runs OFFLINE, so
        provider.tf is in dummy-credential mode; the refresh signs a real EC2
        call with a fake key and the plan dies. Observed verbatim in
        jobs/rerun-named-resource-replacement/2026-08-25__01-43-17/
        named-resource-replacement-hcl-r__rtmpCyN/verifier/test-stdout.txt:42-46:

            aws_vpc.internal_services: Refreshing state... [id=vpc-05c33a26cbf19bef8]
            Planning failed. Terraform encountered an error while generating this plan.
            PLAN FAILED

        That row's 0.0 was read as "the agent's config is bad". It was the
        VERIFIER failing on state the agent's own SUCCESSFUL apply created.
        Once `workspace_seed.deploy` seeds state deliberately this fires on
        EVERY brownfield trial on that arm, including a perfect one.

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
            # MATCH THE SUBCOMMAND, NOT THE LITERAL TWO WORDS (finding G,
            # adversarial review round 3, 2026-08-25). This was
            # `"terraform plan" not in plan_command`, so an ordinary
            # `terraform -chdir=. plan -input=false ...` -- a form the CLI has
            # documented since 0.14 -- passed spec load in SILENCE, and gen.py
            # splices `plan_command` verbatim into hcl_raw's static_tiers.sh.
            # The consequence is the exact one this validator's docstring
            # measures: with the seed's state present, the OFFLINE verifier
            # plan refreshes through provider.tf's dummy credentials and dies,
            # scoring every hcl-raw brownfield trial 0.0 before the agent is
            # judged. `_TF_PLAN_RE` allows any run of global flags between the
            # binary and the subcommand, which is the only place terraform
            # accepts them.
            if not plan_command or not _TF_PLAN_RE.search(plan_command):
                continue
            if "-refresh=false" not in plan_command:
                offenders.append(arm)
        if offenders:
            raise ValueError(
                f"BROWNFIELD (§2.7) arm(s) {offenders} declare a "
                "`terraform plan` in output_contract.plan_command WITHOUT "
                "`-refresh=false`. With deploy state present in /app/project "
                "the OFFLINE verifier's plan refreshes through provider.tf's "
                "dummy credentials and dies -- measured, "
                "jobs/rerun-named-resource-replacement/2026-08-25__01-43-17/"
                "named-resource-replacement-hcl-r__rtmpCyN/verifier/"
                "test-stdout.txt:42-46 ('Refreshing state... "
                "[id=vpc-05c33a26cbf19bef8]' then 'PLAN FAILED'), scoring a "
                "PERFECT solution 0.0. Grading is unaffected: every "
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
          * BROWNFIELD (§2.7): `title` describes the CHANGE and, in practice,
            names the very property of the existing config that carries the
            pitfall — the pilot's own first draft, "Rename an explicitly-named,
            in-use security group and roll it out", stamped *both* halves of
            its poison ("explicitly-named", "in-use") into
            `bin/app.ts`'s CFN `description` and `main.ts`'s header comment on
            two of three arms, while the third arm's workspace (whose entry
            file IS the seed) stayed clean — an arm-asymmetric hint inside the
            comparison the scenario exists to measure. A brownfield header must
            therefore describe only what the workspace ALREADY IS (e.g.
            "Internal services network"), never what is about to change about
            it or why it is interesting.

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

          * MULTI-STEP: `apigw-redeploy` -- the id IS step 2's verb. It reached
            `environment/app/main.ts` as the `ScenarioStack` construct id and
            `gridUUID`, and every arm's skeleton header cited
            `specs/apigw-redeploy.yaml`. Amendment 27's sweep grepped the
            hyphenated `re-deploy` only and saw none of it.
          * BROWNFIELD (§2.7): `named-resource-replacement` -- the id is not
            the change request ("rename the security group to X"), it is the
            DIAGNOSIS the agent is supposed to derive from the configuration.
            It reached two of three arms and not the third, which biases the
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
        DIRECTORY, and that directory is named by the construct id
        `gen.py::terraconstructs_main_ts` stamps -- which is now
        `workspace_identity()`, not `id` (§0.1).

        Checked here rather than left to a runtime surprise: a mismatch does
        not fail loudly, it makes every tier-0 assert resolve against a
        nonexistent plan.json and score a constant 0.0, INCLUDING for the
        reference solution.
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
