"""oracles/emit.py

Stable interface the generator (`generator/gen.py`, Slice C) imports to
produce a scenario's oracle-side files from its parsed intent spec
(`specs/SCHEMA.md` §4, §8):

    from oracles.emit import emit_oracles
    files = emit_oracles(spec)   # spec = yaml.safe_load(Path("specs/<id>.yaml").read_text())

`emit_oracles` writes (or, for the two hand-authored files, scaffolds-once):

    oracles/<id>/intent.md                — oracle.intent, verbatim, ALWAYS
                                             regenerated (§8.2 rule 7).
    oracles/rego/<id>/policy.rego         — scaffolded ONLY if it doesn't
                                             exist yet; a header keyed to
                                             the spec's tier-"1" structural
                                             asserts + rego_hints, never
                                             synthesized policy logic
                                             (§8.2 rule 7).
    oracles/cfn-guard/<id>/policy.guard   — same, for cfn_guard_hints.
                                             Written ONLY when the spec's
                                             `oracle.awscdk_tier1_engine`
                                             is "cfn_guard" (the default).
    oracles/rego-cfn/<id>/policy.rego     — same, but Rego over the awscdk
                                             arm's synthesized CloudFormation
                                             template. Written ONLY when
                                             `oracle.awscdk_tier1_engine`
                                             is "rego" (specs/SCHEMA.md §4.5,
                                             ROADMAP.md M8).

Exactly THREE files are written per call: intent.md, the TF-shaped
`oracles/rego/<id>/policy.rego`, and whichever awscdk-side bundle the spec's
`oracle.awscdk_tier1_engine` selects. `oracles/rego/` and `oracles/rego-cfn/`
are deliberately different trees holding same-named files because their
`input` documents are structurally unrelated (`terraform show -json` plan JSON
vs a CloudFormation template) — one policy body cannot serve both, and pretending
otherwise is how a cross-arm strictness gap gets hidden (DECISIONS.md Amendment
29 §4).

and returns `{repo-relative path: final on-disk content}` for every one of
those three files, so a caller (the generator's own tests, this module's
own tests) can assert on both "what got written" and "what it says" without
a second filesystem read.

Directory grouping matches `specs/SCHEMA.md` §8/§8.1's explicitly-flagged
decision (policy files stay under the already-scaffolded
`oracles/rego/<id>/` and `oracles/cfn-guard/<id>/`, NOT a flat
`oracles/<id>/{policy.rego,policy.guard}` layout) — see that section if this
needs to be revisited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

__all__ = ["REPO_ROOT", "emit_oracles"]


# --------------------------------------------------------------------------
# Path helpers (§8's generated layout)
# --------------------------------------------------------------------------


def _intent_path(scenario_id: str, root: Path) -> Path:
    return root / "oracles" / scenario_id / "intent.md"


def _rego_path(scenario_id: str, root: Path) -> Path:
    return root / "oracles" / "rego" / scenario_id / "policy.rego"


def _cfn_guard_path(scenario_id: str, root: Path) -> Path:
    return root / "oracles" / "cfn-guard" / scenario_id / "policy.guard"


def _rego_cfn_path(scenario_id: str, root: Path) -> Path:
    return root / "oracles" / "rego-cfn" / scenario_id / "policy.rego"


def _awscdk_tier1_engine(spec: dict[str, Any]) -> str:
    """`oracle.awscdk_tier1_engine`, defaulting to the incumbent.

    Defaulted HERE as well as in `generator/spec_model.py` because
    `emit_oracles` takes a raw parsed-YAML dict (its documented contract), so
    it must tolerate a spec dict that predates the field entirely — which is
    every spec written before ROADMAP.md M8.
    """
    return spec.get("oracle", {}).get("awscdk_tier1_engine") or "cfn_guard"


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------


def _render_intent_md(spec: dict[str, Any]) -> str:
    scenario_id = spec["id"]
    title = spec.get("title", scenario_id)
    intent = spec["oracle"]["intent"].strip()
    # The awscdk-side bundle this scenario is actually graded by (§4.5). Named
    # explicitly because intent.md's whole job is to be the reference both
    # bundles are checked against — pointing at a policy.guard that a
    # rego-engine scenario never runs would send a reviewer to a dead file.
    if _awscdk_tier1_engine(spec) == "rego":
        awscdk_bundle = f"`../rego-cfn/{scenario_id}/policy.rego`"
    else:
        awscdk_bundle = f"`../cfn-guard/{scenario_id}/policy.guard`"
    return (
        f"# Oracle intent: {title}\n\n"
        f"`{scenario_id}` — generated verbatim from `specs/{scenario_id}.yaml`'s "
        f"`oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single "
        f"natural-language source of truth that both "
        f"`../rego/{scenario_id}/policy.rego` and "
        f"{awscdk_bundle} must encode at the same "
        f"strictness — the oracle-equivalence CI (Slice E) uses this file as "
        f"the human-reviewable reference when checking that.\n\n"
        f"**Do not hand-edit this file.** It is regenerated from the spec on "
        f"every `emit_oracles` call; edit `oracle.intent` in "
        f"`specs/{scenario_id}.yaml` instead.\n\n"
        f"---\n\n"
        f"{intent}\n"
    )


def _rego_package_name(scenario_id: str) -> str:
    return "cdktn_bench." + scenario_id.replace("-", "_")


def _tier1_asserts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in spec.get("oracle", {}).get("structural_asserts", []) if a.get("tier") == "1"]


def _render_rego_skeleton(spec: dict[str, Any]) -> str:
    scenario_id = spec["id"]
    tier1 = _tier1_asserts(spec)
    hints = spec.get("oracle", {}).get("rego_hints", [])

    lines: list[str] = [
        "# GENERATOR-STUB — auto-scaffolded by oracles/emit.py, hand-author the",
        "# real rules below and then DELETE this GENERATOR-STUB line. The generated",
        "# tests/_assert_lib.sh::is_stub_policy() greps this exact file for the",
        "# literal string \"GENERATOR-STUB\" to decide whether tier-1 should run for",
        "# real or report SKIPPED_STUB — leaving this marker in place after you've",
        "# added real rules would silently disable grading, and removing it from a",
        "# still-unauthored file would make an empty policy start gating trials.",
        "# emit_oracles() never overwrites this file once it exists (specs/SCHEMA.md",
        "# §8.2 rule 7), so edits here are safe across regeneration.",
        "#",
        f"# Scenario:      {scenario_id} (specs/{scenario_id}.yaml)",
        f"# Intent doc:    oracles/{scenario_id}/intent.md",
        "# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms",
        "# (hcl_raw and, when enabled, terraconstructs) — specs/SCHEMA.md §4.2/§8.",
        "# `input` at policy-evaluation time is that plan JSON document.",
        "#",
        "# Tier-\"1\" structural_asserts this policy must encode (from the spec):",
    ]
    if tier1:
        for a in tier1:
            lines.append(f"#   - {a['name']}: {a.get('description', '').strip()}")
            lines.append(f"#     tf_jsonpath: {a.get('tf_jsonpath', '<none>')}")
            lines.append(f"#     op={a['op']} expected={a.get('expected')!r}")
    else:
        lines.append("#   (none declared in this spec — this scenario has no tier-\"1\" asserts)")

    lines.append("#")
    lines.append("# rego_hints (free-form prose from the spec, not executable — guidance only):")
    if hints:
        for hint in hints:
            lines.append(f"#   - {hint}")
    else:
        lines.append("#   (none declared)")

    lines += [
        "",
        f"package {_rego_package_name(scenario_id)}",
        "",
        "import rego.v1",
        "",
        "# TODO(Slice D): replace this placeholder with `deny`/`allow` rules that",
        "# encode every tier-\"1\" assert and hint listed above. A generated",
        "# static_tiers.sh runs `opa eval -d policy.rego -i plan.json",
        "# 'data.<package>.deny'` (or equivalent) and fails the tier iff that set is",
        "# non-empty — see oracles/rego/README.md.",
        "",
        "default allow := false",
        "",
        "# Placeholder: always non-compliant until hand-authored, so a forgotten",
        "# scaffold can never silently pass a real trial.",
        "allow if {",
        "\tfalse",
        "}",
        "",
        "# TODO(Slice D, optional): if any tier-\"1\" assert above targets a",
        "# plan-time-unknown attribute (specs/SCHEMA.md §4.2.1 -- an IAM policy or",
        "# similar value-content check whose encoded value can go `(known after",
        "# apply)` when a correct solution references another resource's",
        "# provider-computed output), replace this placeholder with a real",
        "# `not_verifiable` set alongside `deny`/`allow`: fires exactly when the",
        "# graph-edge check already passed but the value-content check cannot be",
        "# evaluated from plan JSON alone. A generated tests/static_tiers.sh",
        "# (generator/gen.py::build_static_tiers_sh) evaluates",
        "# `data.<package>.not_verifiable` after `deny` and, when non-empty, tees",
        "# it to /logs/verifier/tier1-not-verifiable -- non-gating, never affects",
        "# tier1_status/reward, purely a \"this could not be checked\" record (see",
        "# SCHEMA.md §4.2.1's option-3 bullet and",
        "# oracles/rego/toy-ssm-parameter/policy.rego's own not_verifiable rule for",
        "# the worked example). Leave this empty placeholder in place (it always",
        "# evaluates to an empty set, so no marker is ever written) for a scenario",
        "# with no such gap.",
        "not_verifiable contains msg if {",
        "\tfalse",
        "\tmsg := \"\"",
        "}",
        "",
    ]
    return "\n".join(lines)


def _render_rego_cfn_skeleton(spec: dict[str, Any]) -> str:
    """The awscdk-side Rego skeleton (`oracles/rego-cfn/<id>/policy.rego`).

    Same package name and same `deny`/`not_verifiable` contract as the
    TF-shaped skeleton above — the generated `tests/static_tiers.sh` runs the
    identical `opa eval ... 'data.<pkg>.deny'` line for both — but the `input`
    document is a synthesized CloudFormation template, so it lists each tier-1
    assert's `cfn_jsonpath` (not `tf_jsonpath`) and the spec's
    `cfn_guard_hints` (the CFN-side hints; `rego_hints` describe the plan-JSON
    shape and would mislead here). Sharing the package name is safe precisely
    because the two files never load into one OPA instance: each is copied
    into its own arm's `tests/` directory as the only policy there.
    """
    scenario_id = spec["id"]
    tier1 = _tier1_asserts(spec)
    hints = spec.get("oracle", {}).get("cfn_guard_hints", [])

    lines: list[str] = [
        "# GENERATOR-STUB — auto-scaffolded by oracles/emit.py, hand-author the",
        "# real rules below and then DELETE this GENERATOR-STUB line. The generated",
        "# tests/_assert_lib.sh::is_stub_policy() greps this exact file for the",
        "# literal string \"GENERATOR-STUB\" to decide whether tier-1 should run for",
        "# real or report SKIPPED_STUB — leaving this marker in place after you've",
        "# added real rules would silently disable grading, and removing it from a",
        "# still-unauthored file would make an empty policy start gating trials.",
        "# emit_oracles() never overwrites this file once it exists (specs/SCHEMA.md",
        "# §8.2 rule 7), so edits here are safe across regeneration.",
        "#",
        f"# Scenario:      {scenario_id} (specs/{scenario_id}.yaml)",
        f"# Intent doc:    oracles/{scenario_id}/intent.md",
        "# Graded against the awscdk arm's synthesized CloudFormation template",
        "# (cdk.out/ScenarioStack.template.json) — specs/SCHEMA.md §4.5/§8. `input`",
        "# at policy-evaluation time is that TEMPLATE document, NOT the",
        "# `terraform show -json` plan JSON that oracles/rego/<id>/policy.rego sees:",
        "# resources live under `input.Resources[<LogicalId>]` with `.Type` and",
        "# `.Properties`, and cross-resource references appear as `{\"Ref\": ...}` /",
        "# `{\"Fn::GetAtt\": [...]}` objects naming a LOGICAL ID. That logical-id join",
        "# is the whole reason this engine exists (ROADMAP.md M8): cfn-guard 3.2.0",
        "# cannot express it, and approximating it with a count-equality proxy is",
        "# unsound in both directions.",
        "#",
        "# Amendment 29 §4 is BINDING here: never key identity on a physical name",
        "# (Properties.RoleName, BucketName, ...). Grade existence + type +",
        "# properties, joined on LOGICAL ID.",
        "#",
        "# Tier-\"1\" structural_asserts this policy must encode (from the spec):",
    ]
    if tier1:
        for a in tier1:
            lines.append(f"#   - {a['name']}: {a.get('description', '').strip()}")
            lines.append(f"#     cfn_jsonpath: {a.get('cfn_jsonpath', '<none>')}")
            lines.append(f"#     op={a['op']} expected={a.get('expected')!r}")
    else:
        lines.append("#   (none declared in this spec — this scenario has no tier-\"1\" asserts)")

    lines.append("#")
    lines.append("# cfn_guard_hints (free-form prose from the spec, not executable — guidance only;")
    lines.append("# these are the CFN-shape hints, and they apply to this file whichever engine")
    lines.append("# reads them):")
    if hints:
        for hint in hints:
            lines.append(f"#   - {hint}")
    else:
        lines.append("#   (none declared)")

    lines += [
        "",
        f"package {_rego_package_name(scenario_id)}",
        "",
        "import rego.v1",
        "",
        "# TODO: replace this placeholder with `deny` rules that encode every",
        "# tier-\"1\" assert and hint listed above, against the CloudFormation",
        "# template shape. The generated tests/static_tiers.sh runs",
        "# `opa eval -f raw -I -d policy.rego 'data.<package>.deny' < template.json`",
        "# and fails tier-1 iff that set is non-empty — see oracles/rego-cfn/README.md.",
        "",
        "default allow := false",
        "",
        "# Placeholder: always non-compliant until hand-authored, so a forgotten",
        "# scaffold can never silently pass a real trial.",
        "allow if {",
        "\tfalse",
        "}",
        "",
        "# `not_verifiable` (optional, non-gating) is evaluated by the same generated",
        "# static_tiers.sh block the TF arms use, so the rule name is available here",
        "# too. It is normally left as this empty placeholder on the awscdk arm:",
        "# CFN synth is fully static, so there is no plan-time-unknown gap of the kind",
        "# specs/SCHEMA.md §4.2.1 describes. Leaving it empty writes no marker.",
        "not_verifiable contains msg if {",
        "\tfalse",
        "\tmsg := \"\"",
        "}",
        "",
    ]
    return "\n".join(lines)


def _render_guard_skeleton(spec: dict[str, Any]) -> str:
    scenario_id = spec["id"]
    tier1 = _tier1_asserts(spec)
    hints = spec.get("oracle", {}).get("cfn_guard_hints", [])

    lines: list[str] = [
        "#",
        "# GENERATOR-STUB — auto-scaffolded by oracles/emit.py, hand-author the",
        "# real rules below and then DELETE this GENERATOR-STUB line. The generated",
        "# tests/_assert_lib.sh::is_stub_policy() greps this exact file for the",
        "# literal string \"GENERATOR-STUB\" to decide whether tier-1 should run for",
        "# real or report SKIPPED_STUB — leaving this marker in place after you've",
        "# added real rules would silently disable grading, and removing it from a",
        "# still-unauthored file would make an empty policy start gating trials.",
        "# emit_oracles() never overwrites this file once it exists (specs/SCHEMA.md",
        "# §8.2 rule 7), so edits here are safe across regeneration.",
        "#",
        f"# Scenario:   {scenario_id} (specs/{scenario_id}.yaml)",
        f"# Intent doc: oracles/{scenario_id}/intent.md",
        "# Graded against the awscdk arm's synthesized CloudFormation template",
        "# (cdk.out/ScenarioStack.template.json) — specs/SCHEMA.md §4.2/§8.",
        "#",
        "# Tier-\"1\" structural_asserts this policy must encode (from the spec):",
    ]
    if tier1:
        for a in tier1:
            lines.append(f"#   - {a['name']}: {a.get('description', '').strip()}")
            lines.append(f"#     cfn_jsonpath: {a.get('cfn_jsonpath', '<none>')}")
            lines.append(f"#     op={a['op']} expected={a.get('expected')!r}")
    else:
        lines.append("#   (none declared in this spec — this scenario has no tier-\"1\" asserts)")

    lines.append("#")
    lines.append("# cfn_guard_hints (free-form prose from the spec, not executable — guidance only):")
    if hints:
        for hint in hints:
            lines.append(f"#   - {hint}")
    else:
        lines.append("#   (none declared)")

    lines += [
        "#",
        "# TODO(Slice D): replace this placeholder with real cfn-guard 3 rules that",
        "# encode every tier-\"1\" assert and hint above (cfn-guard 3 DSL —",
        "# `rule <name> [when <condition>] { <checks> }`; see oracles/cfn-guard/README.md",
        "# and `cfn-guard validate --rules policy.guard --data <template.json>`).",
        "#",
        "# Placeholder: requires Resources to be a non-empty map, which is true of any",
        "# real synthesized template — i.e. this rule alone certifies nothing about",
        "# the scenario's actual intent and must not be mistaken for a real policy.",
        "rule placeholder_pending_hand_authoring {",
        "\tResources.* EXISTS",
        "}",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def emit_oracles(spec: dict[str, Any], root: Path | None = None) -> dict[str, str]:
    """Produce `oracles/<id>/intent.md`, `oracles/rego/<id>/policy.rego`, and
    this spec's awscdk-side policy bundle for `spec` (a parsed
    `specs/<id>.yaml`). `root` defaults to this repo's root
    (`oracles/emit.py`'s own grandparent directory) — pass a `tmp_path` in
    tests to avoid touching the real tree.

    Returns `{path relative to root, POSIX-separated: final file content}`
    for exactly three files: `intent.md`, the TF-shaped `policy.rego`, and the
    awscdk-side bundle named by `oracle.awscdk_tier1_engine` (default
    `"cfn_guard"` -> `oracles/cfn-guard/<id>/policy.guard`; `"rego"` ->
    `oracles/rego-cfn/<id>/policy.rego`). `intent.md` is always rewritten; the
    two policy files are written only the first time (existing hand-authored
    content is never touched — see module docstring).
    """
    root = root or REPO_ROOT
    scenario_id = spec["id"]
    files: dict[str, str] = {}

    intent_path = _intent_path(scenario_id, root)
    intent_content = _render_intent_md(spec)
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    intent_path.write_text(intent_content)
    files[intent_path.relative_to(root).as_posix()] = intent_content

    rego_path = _rego_path(scenario_id, root)
    if not rego_path.exists():
        rego_path.parent.mkdir(parents=True, exist_ok=True)
        rego_path.write_text(_render_rego_skeleton(spec))
    files[rego_path.relative_to(root).as_posix()] = rego_path.read_text()

    # The awscdk-side bundle: exactly ONE of the two, chosen by
    # `oracle.awscdk_tier1_engine` (specs/SCHEMA.md §4.5). Scaffolding the
    # unselected one too would litter the tree with a policy no generated
    # tests/ ever copies and no trial ever runs -- a stub that looks like
    # grading but is not, which is precisely the failure mode M8 exists to
    # remove. Flipping the field on an already-generated scenario therefore
    # leaves the previous engine's bundle behind as an orphan; delete it by
    # hand (it is hand-authored content, so the generator will not).
    if _awscdk_tier1_engine(spec) == "rego":
        awscdk_path = _rego_cfn_path(scenario_id, root)
        awscdk_skeleton = _render_rego_cfn_skeleton(spec)
    else:
        awscdk_path = _cfn_guard_path(scenario_id, root)
        awscdk_skeleton = _render_guard_skeleton(spec)
    if not awscdk_path.exists():
        awscdk_path.parent.mkdir(parents=True, exist_ok=True)
        awscdk_path.write_text(awscdk_skeleton)
    files[awscdk_path.relative_to(root).as_posix()] = awscdk_path.read_text()

    return files
