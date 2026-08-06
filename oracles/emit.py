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


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------


def _render_intent_md(spec: dict[str, Any]) -> str:
    scenario_id = spec["id"]
    title = spec.get("title", scenario_id)
    intent = spec["oracle"]["intent"].strip()
    return (
        f"# Oracle intent: {title}\n\n"
        f"`{scenario_id}` — generated verbatim from `specs/{scenario_id}.yaml`'s "
        f"`oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single "
        f"natural-language source of truth that both "
        f"`../rego/{scenario_id}/policy.rego` and "
        f"`../cfn-guard/{scenario_id}/policy.guard` must encode at the same "
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
    `oracles/cfn-guard/<id>/policy.guard` for `spec` (a parsed
    `specs/<id>.yaml`). `root` defaults to this repo's root
    (`oracles/emit.py`'s own grandparent directory) — pass a `tmp_path` in
    tests to avoid touching the real tree.

    Returns `{path relative to root, POSIX-separated: final file content}`
    for exactly those three files. `intent.md` is always rewritten;
    `policy.rego`/`policy.guard` are written only the first time (existing
    hand-authored content is never touched — see module docstring).
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

    guard_path = _cfn_guard_path(scenario_id, root)
    if not guard_path.exists():
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        guard_path.write_text(_render_guard_skeleton(spec))
    files[guard_path.relative_to(root).as_posix()] = guard_path.read_text()

    return files
