"""oracles/lib/tier05_jsonata.py

Tier-0.5 oracle: **embedded-expression evaluation** (`DECISIONS.md`
Amendment №1, `specs/SCHEMA.md` §4.4). Evaluates every `{% ... %}` JSONata
expression embedded in a synthesized Step Functions ASL definition against a
scenario's `oracle.tier05_jsonata.cases`, using `jsonata-python`.

Outer-template structural assertions (tier "0"/"1") can only see the CFN/TF
document shape — an embedded JSONata expression that is syntactically
invalid, or subtly wrong about JSONata's sequence semantics, sails through
every one of them and only fails at `CreateStateMachine` or at execution
time. This module closes that gap locally, offline.

Where this runs: HOST-SIDE, post-hoc, not inside an arm's agent container
(see `DECISIONS.md` "Tier-0.5 runs host-side, non-gating" for the full
rationale/record of this decision). None of the three arm images ship
Python or `jsonata-python` — that dependency lives in this repo's own
`pyproject.toml`/`uv` environment, the same one this file already runs in
under `oracles/tests/`. Run it as:

    uv run python -m oracles.lib.tier05_jsonata <artifact.json> <spec.yaml>

against the artifact a trial's `tests/static_tiers.sh` already produced
(`$ARTIFACT`, exported/copied out of the container) and the scenario's own
`specs/<id>.yaml`. Exit 0 iff every case passed; non-zero otherwise, with
`Tier05CaseResult.explain()` lines on stdout. Mirrors `tests/live_check.py`'s
existing non-gating precedent: this is intentionally NOT wired into
`generator/gen.py`'s generated `tests/static_tiers.sh` (so it can never
affect `/logs/verifier/reward.txt`) -- see `build_tier05_host_readme()` in
`generator/gen.py`, which emits a `tests/TIER05.md` note into any generated
task whose spec declares `tier05_jsonata`, pointing back at this exact
command, so the hook is documented and discoverable per-task rather than
silently absent.

Technique ported from
`tc-ai-pdlc-coding-features/tests/helpers_asl.py` (`strip_braces`,
`jsonata_expressions`, `evaluate`) — read alongside this file for the
original CFN-template-specific version this generalizes. This version:
  - locates the ASL definition(s) via a **JSONPath** (`expressions_from`,
    `specs/SCHEMA.md` §4.4) resolved through `oracles.lib.structural.resolve`,
    so it works against either a CFN template OR a Terraform plan JSON
    document without a second extraction mechanism (per §4.4: "the ASL JSON
    is extractable from both CFN and TF plan output, so this adds no arm
    asymmetry"), instead of `helpers_asl.py`'s CFN-`find_resources`-specific
    `definitions()`;
  - takes `sample_inputs` from the spec instead of being called ad hoc per
    test, and reports every `(expression, sample)` pair's outcome rather
    than asserting inline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jsonata

from .structural import resolve

__all__ = [
    "Tier05CaseResult",
    "Tier05Error",
    "evaluate",
    "find_asl_documents",
    "jsonata_expressions",
    "run_tier05",
    "run_tier05_or_raise",
    "strip_braces",
]


class Tier05Error(AssertionError):
    """Raised by `run_tier05_or_raise` when at least one (expression,
    sample) case failed, or when `expressions_from` located no ASL document
    at all (a spec/artifact bug — a scenario that declares `tier05_jsonata`
    is asserting at least one `{% ... %}` expression exists)."""


def find_asl_documents(document: dict, expressions_from: str) -> list[Any]:
    """Resolve `oracle.tier05_jsonata.expressions_from` (a JSONPath, per
    `specs/SCHEMA.md` §4.4) against `document` (a parsed CFN template or TF
    plan JSON). Returns every matched node — each expected to be either a
    JSON string holding a full ASL definition (CFN's
    `DefinitionString`-after-`Fn::Join`-flattening shape) or an ASL dict
    already (TF plan JSON's `definition` attribute is typically a plain JSON
    string too, but callers may pre-parse)."""
    return resolve(document, expressions_from)


def _as_asl_dict(node: Any) -> dict:
    if isinstance(node, dict):
        return node
    if isinstance(node, str):
        return json.loads(node)
    raise Tier05Error(f"expected an ASL JSON string or dict at expressions_from, got {type(node).__name__}: {node!r}")


def strip_braces(expression: str) -> str:
    """Strip a `{% ... %}` ASL embedded-expression wrapper, returning the
    bare JSONata source. Raises `Tier05Error` (not a bare `assert`, unlike
    `helpers_asl.py`'s original) if `expression` isn't actually wrapped —
    callers here are walking untrusted synthesized output, not a
    hand-written test fixture, so a malformed node should produce a legible
    oracle failure rather than an `AssertionError` stack trace."""
    stripped = expression.strip()
    if not (stripped.startswith("{%") and stripped.endswith("%}")):
        raise Tier05Error(f"not a JSONata embedded-expression string (missing {{% %}} wrapper): {expression!r}")
    return stripped[2:-2].strip()


def jsonata_expressions(node: Any, path: str = "$") -> list[tuple[str, str]]:
    """Every `{% ... %}` string anywhere under `node` (an ASL dict, or list/
    scalar reached while walking one), paired with the JSON path it was
    found at, for legible failure messages. Same walk as
    `helpers_asl.py`'s function of the same name."""
    found: list[tuple[str, str]] = []
    if isinstance(node, str):
        stripped = node.strip()
        if stripped.startswith("{%") and stripped.endswith("%}"):
            found.append((path, node))
    elif isinstance(node, dict):
        for key, value in node.items():
            found.extend(jsonata_expressions(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(jsonata_expressions(value, f"{path}[{index}]"))
    return found


def evaluate(expression: str, sample_input: dict, context: dict | None = None) -> Any:
    """Evaluate a `{% ... %}` ASL expression the way Step Functions JSONata
    mode would: `$states.input` bound to `sample_input`, `$states.context`
    to `context`. Propagates whatever `jsonata-python` raises on a
    syntactically invalid expression — `run_tier05` catches that and turns
    it into a failed `Tier05CaseResult` rather than crashing the whole run."""
    bindings = {"states": {"input": sample_input, "context": context or {}}}
    return jsonata.Jsonata(strip_braces(expression)).evaluate(None, bindings)


@dataclass(frozen=True)
class Tier05CaseResult:
    expression_path: str
    expression: str
    sample_index: int
    expected_output: Any
    actual_output: Any
    passed: bool
    error: str | None = None

    def explain(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        tail = f" ERROR={self.error}" if self.error else ""
        return (
            f"[{verdict}] {self.expression_path} sample#{self.sample_index} "
            f"expr={self.expression!r} expected={self.expected_output!r} "
            f"actual={self.actual_output!r}{tail}"
        )


def run_tier05(document: dict, spec_tier05: dict) -> list[Tier05CaseResult]:
    """Run every case in `spec_tier05['cases']` against the ONE `{% ... %}`
    expression it names via `expression_path` (`specs/SCHEMA.md` §4.4 shape:
    `{expressions_from, cases: [{expression_path, input, expected_output}, ...]}`).

    Each case is matched to exactly its own expression -- NOT the cartesian
    product of every found expression against every case, which is what
    this function used to do. That cartesian version rejected a fully
    correct multi-expression state machine unconditionally the moment it
    had more than one embedded expression (e.g. state A's expression
    evaluated against state B's sample input, compared against state B's
    expected output, fails despite A and B individually being correct) --
    exactly the shape the real sfn-jsonata seed scenario needs (a
    "non-trivial input/output transformation" plus a mode-mixing trap,
    almost certainly >1 embedded expression).

    Two conditions are themselves reported as *failed* cases (via
    `Tier05CaseResult.error`, not a Python exception) rather than silently
    skipped, so a spec/artifact mismatch is caught, not ignored:
      - a case's `expression_path` matches no expression actually found in
        the synthesized artifact (catches a renamed/removed state -- the
        spec's case still exists, but the thing it was testing doesn't);
      - an expression IS found but no case covers its path (an
        under-tested embedded expression, silently un-graded).

    Never raises on a case *failure* (bad syntax, wrong value, or either
    mismatch above) — those are reported as `passed=False` results, exactly
    like a Tier-0 `StructuralAssertError`'s underlying `AssertResult` does.
    Use `run_tier05_or_raise` to fail fast with a summarized message.
    """
    results: list[Tier05CaseResult] = []
    nodes = find_asl_documents(document, spec_tier05["expressions_from"])

    found: dict[str, str] = {}  # expression_path -> expression text
    for node_index, node in enumerate(nodes):
        asl = _as_asl_dict(node)
        for expr_path, expr in jsonata_expressions(asl):
            full_path = f"[{node_index}]{expr_path}" if len(nodes) > 1 else expr_path
            found[full_path] = expr

    cases = spec_tier05["cases"]
    covered_paths: set[str] = set()
    for sample_index, case in enumerate(cases):
        expr_path = case["expression_path"]
        expr = found.get(expr_path)
        if expr is None:
            results.append(
                Tier05CaseResult(
                    expression_path=expr_path,
                    expression="<not found>",
                    sample_index=sample_index,
                    expected_output=case["expected_output"],
                    actual_output=None,
                    passed=False,
                    error=(
                        f"expression_path {expr_path!r} matches no {{% ... %}} "
                        f"expression in the synthesized artifact (found paths: "
                        f"{sorted(found)!r}) -- a renamed/removed state, or a "
                        f"stale case, would land here"
                    ),
                )
            )
            continue
        covered_paths.add(expr_path)
        try:
            actual = evaluate(expr, case["input"])
            passed = actual == case["expected_output"]
            error = None
        except Exception as exc:  # noqa: BLE001 - jsonata-python raises broad/undocumented exception types on bad syntax or eval errors; any of them must become a failed case, not a crashed oracle run
            actual = None
            passed = False
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            Tier05CaseResult(
                expression_path=expr_path,
                expression=expr,
                sample_index=sample_index,
                expected_output=case["expected_output"],
                actual_output=actual,
                passed=passed,
                error=error,
            )
        )

    for expr_path, expr in found.items():
        if expr_path not in covered_paths:
            results.append(
                Tier05CaseResult(
                    expression_path=expr_path,
                    expression=expr,
                    sample_index=-1,
                    expected_output=None,
                    actual_output=None,
                    passed=False,
                    error=(
                        f"expression at {expr_path!r} has no case in "
                        f"oracle.tier05_jsonata.cases -- every embedded "
                        f"expression must have at least one covering case"
                    ),
                )
            )

    return results


def run_tier05_or_raise(document: dict, spec_tier05: dict) -> list[Tier05CaseResult]:
    """`run_tier05`, but raises `Tier05Error` summarizing every failing case
    (and the "found nothing to check" case) — what a generated
    `static_tiers.sh`/pytest test should call."""
    results = run_tier05(document, spec_tier05)
    if not results:
        raise Tier05Error(
            f"no {{% ... %}} JSONata expression found under expressions_from="
            f"{spec_tier05['expressions_from']!r} — a scenario that declares "
            f"tier05_jsonata must have at least one embedded expression"
        )
    failures = [r for r in results if not r.passed]
    if failures:
        raise Tier05Error(
            f"{len(failures)}/{len(results)} Tier-0.5 JSONata case(s) failed:\n"
            + "\n".join(f.explain() for f in failures)
        )
    return results


def main(argv: list[str]) -> int:
    """`uv run python -m oracles.lib.tier05_jsonata <artifact.json> <spec.yaml>`
    -- the host-side, post-hoc CLI this module's docstring describes.
    Writes one `Tier05CaseResult.explain()` line per case to stdout and a
    machine-readable summary to
    /logs/verifier/tier05-result.json IF that directory exists (matching
    tests/live_check.py's own `/logs/verifier/live_check-result.json`
    convention), but never touches /logs/verifier/reward.txt -- this tier
    is non-gating in v1 by design (DECISIONS.md), the same as live_check."""
    import sys as _sys
    from pathlib import Path as _Path

    import yaml as _yaml

    if len(argv) != 3:
        print(f"usage: {argv[0]} <artifact.json> <spec.yaml>", file=_sys.stderr)
        return 2
    artifact_path, spec_path = _Path(argv[1]), _Path(argv[2])

    document = json.loads(artifact_path.read_text())
    spec = _yaml.safe_load(spec_path.read_text())
    spec_tier05 = spec.get("oracle", {}).get("tier05_jsonata")
    if not spec_tier05:
        print(f"{spec_path}: oracle.tier05_jsonata is null -- nothing to check")
        return 0

    results = run_tier05(document, spec_tier05)
    for r in results:
        print(r.explain())
    passed = bool(results) and all(r.passed for r in results)

    logs_dir = _Path("/logs/verifier")
    if logs_dir.is_dir():
        (logs_dir / "tier05-result.json").write_text(
            json.dumps(
                {
                    "passed": passed,
                    "cases": [
                        {
                            "expression_path": r.expression_path,
                            "passed": r.passed,
                            "error": r.error,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )

    return 0 if passed else 1


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv))
