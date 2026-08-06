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
import re
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
    "materialize",
    "run_tier05",
    "run_tier05_or_raise",
    "strip_braces",
]

# "[<node-index>]<jsonpath>" -- the prefix run_tier05 stamps onto a found
# expression's path when `expressions_from` matched more than one ASL
# document (see run_tier05's own `full_path` construction). Used by the
# decomposition-fallback path below to recover which parsed `asl` document
# a case's `expression_path` should be resolved against.
_MULTI_DOC_PREFIX_RE = re.compile(r"^\[(\d+)\](.*)$")


def _split_multi_doc_path(expr_path: str, multi: bool) -> tuple[int, str]:
    """Inverse of `run_tier05`'s `full_path` construction: split a possible
    `"[<node-index>]<jsonpath>"` prefix back off, returning `(node_index,
    bare_jsonpath)`. When `multi` is False (the common case -- one ASL
    document), or the prefix isn't present, returns `(0, expr_path)`
    unchanged."""
    if not multi:
        return 0, expr_path
    m = _MULTI_DOC_PREFIX_RE.match(expr_path)
    if not m:
        return 0, expr_path
    return int(m.group(1)), m.group(2)


class Tier05Error(AssertionError):
    """Raised by `run_tier05_or_raise` when at least one (expression,
    sample) case failed, or when `expressions_from` located no ASL document
    at all (a spec/artifact bug — a scenario that declares `tier05_jsonata`
    is asserting at least one `{% ... %}` expression exists)."""


def _resolve_expressions_from(spec_tier05: dict, document: dict) -> str:
    """`expressions_from` (`specs/SCHEMA.md` §4.4) is either a single
    JSONPath string (used against every arm's own artifact unmodified) or a
    `{"cfn": <path>, "tf": <path>}` mapping -- the normal case for a real
    cross-arm scenario, since a CFN template and a Terraform plan document
    have structurally different roots (`Resources` vs. `planned_values`), so
    one JSONPath cannot resolve against both. Auto-detects which family
    `document` is by checking for the top-level key each family always has
    (verified against real `cdk synth`/`terraform show -json` output --
    CFN templates always carry a top-level `Resources` map; `terraform show
    -json` PLAN output always carries a top-level `planned_values` object),
    and returns the matching path. `hcl_raw` and `terraconstructs` share the
    `tf` path (same collapsing convention as `predicted_tier_caught.hcl`,
    SCHEMA.md §3, and `tf_jsonpath`, §4.2 -- both synthesize to the same
    `terraform show -json` plan shape)."""
    ef = spec_tier05["expressions_from"]
    if isinstance(ef, str):
        return ef
    if "Resources" in document:
        family = "cfn"
    elif "planned_values" in document:
        family = "tf"
    else:
        raise Tier05Error(
            "oracle.tier05_jsonata.expressions_from is arm-keyed (cfn/tf) "
            "but the artifact document has neither a top-level 'Resources' "
            "(CFN template) nor 'planned_values' (Terraform plan) key -- "
            "cannot tell which extraction path applies to this artifact"
        )
    if family not in ef:
        raise Tier05Error(
            f"oracle.tier05_jsonata.expressions_from has no {family!r} entry "
            f"for this {'CFN template' if family == 'cfn' else 'Terraform plan'} "
            f"artifact (declared keys: {sorted(ef)!r})"
        )
    return ef[family]


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


def materialize(node: Any, sample_input: dict, context: dict | None = None) -> Any:
    """Recursively resolve `node` (a raw, still-unevaluated fragment of a
    parsed ASL document -- a dict, a list, a bare `{% ... %}` string, or a
    plain literal) into its fully-evaluated value: every `{% ... %}` string
    leaf, at ANY depth, is replaced by `evaluate()`-ing it against
    `sample_input`/`context`; every other leaf (a plain literal -- a
    JSONata-mode ASL value that was never wrapped in `{% %}` in the first
    place) passes through unchanged; dicts/lists recurse.

    This is the decomposition-fallback half of the fix for benchmark-
    integrity review finding "sfn-jsonata / Tier 0.5 anti-L2 oracle — still
    false-positives on an equally-correct solution" (2026-08-06):
    `oracle.tier05_jsonata.cases` is authored against ONE reference
    decomposition (typically one whole-object `{% ... %}` expression at a
    state's `Output`/`Arguments`), but `JsonataCommonOptions`' typed
    surface (aws-cdk-lib's `outputs`/`arguments` props, and the hand-
    written ASL on hcl_raw) is equally happy with an object literal whose
    INDIVIDUAL fields are each their own `{% ... %}` sub-expression --
    ordinary, idiomatic, equally-correct JSONata-mode ASL that this
    scenario's own instruction never rules out. `run_tier05`'s exact-leaf
    lookup (`found`, keyed by the JSON path a `{% %}` STRING was found at)
    cannot match such a case's `expression_path` (which names the
    CONTAINER, e.g. `.Output` -- a dict, not a string leaf) at all;
    `materialize` is the fallback used when that direct lookup misses:
    resolve `expression_path` against the raw parsed ASL document instead
    (see `run_tier05`'s own fallback branch), and if something is found
    there, materialize IT recursively and compare the fully-resolved value
    to the case's `expected_output` -- semantically identical to evaluating
    one whole-object expression, regardless of how many `{% %}` fragments
    the solution actually split it into.
    """
    if isinstance(node, str):
        stripped = node.strip()
        if stripped.startswith("{%") and stripped.endswith("%}"):
            return evaluate(node, sample_input, context)
        return node
    if isinstance(node, dict):
        return {key: materialize(value, sample_input, context) for key, value in node.items()}
    if isinstance(node, list):
        return [materialize(value, sample_input, context) for value in node]
    return node


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

    THREE outcomes are possible for a case whose `expression_path` matches
    no exact `{% ... %}` STRING leaf (residual-findings fix, 2026-08-06,
    benchmark-integrity review finding "sfn-jsonata / Tier 0.5 anti-L2
    oracle — still false-positives on an equally-correct solution": the
    first fix round only softened the SIBLING mismatch below; this is the
    other half):
      1. `expression_path` also resolves to NOTHING at all in the raw
         parsed ASL document (via `oracles.lib.structural.resolve`) --
         genuinely nothing there. Catches a renamed/removed state -- the
         spec's case still exists, but the thing it was testing doesn't --
         `passed=False`, a real failure, unchanged from before.
      2. `expression_path` resolves to exactly one node that ISN'T a bare
         `{% ... %}` string (a dict/list container -- e.g. a state's whole
         `Output` decomposed into per-field `{% %}` sub-expressions instead
         of one whole-object expression -- or a plain, non-JSONata literal
         value). IF that container has at least one nested `{% ... %}` leaf
         anywhere inside it, `materialize()` recursively evaluates every
         such leaf (passing plain literals through unchanged) and the
         fully-resolved value is compared to `expected_output`, exactly as
         if the reference decomposition had been used -- a correct solution
         that merely decomposed its output differently no longer reads as
         an anti-L2 catch hit.

         A container with ZERO nested `{% ... %}` expressions anywhere
         inside it is a different situation and is deliberately NOT
         materialized-and-compared: it is a fully hardcoded literal, and
         `oracle.tier05_jsonata.cases` (per `specs/SCHEMA.md` §4.4) carries
         exactly one `sample_input`/`expected_output` pair per
         `expression_path` for this spec, so a literal hand-tuned to that
         one sample's `expected_output` would compare equal by construction
         -- `materialize()` on a zero-expression node is just an identity
         round-trip, not a check of anything. (This was the belt half of a
         two-part fix for benchmark-integrity review finding "tier05_jsonata
         materialize() container fallback accepts a fully-hardcoded
         literal", 2026-08-06; the suspenders half is a second sample per
         `expression_path` in this scenario's own `cases[]`, so a literal
         cannot satisfy both even if this guard were ever removed.) Such a
         container is unconditionally `passed=False` with a distinct reason
         string, regardless of whether its literal value happens to equal
         `expected_output`.
      3. an expression IS found (case 0 above didn't apply) but no case
         covers ITS path -- `passed=True`, INFORMATIONAL ONLY, unchanged
         from the first fix round (see the loop at the bottom of this
         function).

    Never raises on a case *failure* (bad syntax, wrong value, or any
    mismatch above) — those are reported as `passed=False` results, exactly
    like a Tier-0 `StructuralAssertError`'s underlying `AssertResult` does.
    Use `run_tier05_or_raise` to fail fast with a summarized message.
    """
    results: list[Tier05CaseResult] = []
    nodes = find_asl_documents(document, _resolve_expressions_from(spec_tier05, document))
    multi = len(nodes) > 1

    asl_docs: list[dict] = []
    found: dict[str, str] = {}  # expression_path -> expression text
    for node_index, node in enumerate(nodes):
        asl = _as_asl_dict(node)
        asl_docs.append(asl)
        for expr_path, expr in jsonata_expressions(asl):
            full_path = f"[{node_index}]{expr_path}" if multi else expr_path
            found[full_path] = expr

    cases = spec_tier05["cases"]
    covered_paths: set[str] = set()
    for sample_index, case in enumerate(cases):
        expr_path = case["expression_path"]
        expr = found.get(expr_path)
        if expr is None:
            doc_index, sub_path = _split_multi_doc_path(expr_path, multi)
            matches = resolve(asl_docs[doc_index], sub_path) if 0 <= doc_index < len(asl_docs) else []
            if len(matches) == 1:
                # Case 2: a container (or a plain literal) sits at this
                # path instead of one whole `{% ... %}` string leaf --
                # materialize it (recursively evaluating any nested
                # `{% ... %}` sub-expressions) and compare that, instead of
                # declaring this a "not found" failure.
                try:
                    if not jsonata_expressions(matches[0]):
                        # Belt half of the fix for benchmark-integrity review
                        # finding "tier05_jsonata materialize() container
                        # fallback accepts a fully-hardcoded literal"
                        # (2026-08-06): zero nested {% ... %} leaves means
                        # this container is a plain literal -- materialize()
                        # would just echo it back unchanged, and with one
                        # sample per expression_path a literal hand-tuned to
                        # that sample's expected_output compares equal by
                        # construction. Refuse to treat that as a pass; see
                        # this function's own docstring (case 2) for the
                        # full rationale.
                        actual = materialize(matches[0], case["input"])
                        passed = False
                        error = (
                            f"expression_path {expr_path!r} names a container/literal "
                            f"with NO nested {{% ... %}} JSONata expression anywhere "
                            f"inside it -- a fully hardcoded literal is indistinguishable "
                            f"from a correct decomposition by value-comparison alone "
                            f"against a single sample, so it is scored as a genuine "
                            f"failure rather than materialized-and-compared, regardless "
                            f"of whether its literal value happens to equal expected_output"
                        )
                    else:
                        actual = materialize(matches[0], case["input"])
                        passed = actual == case["expected_output"]
                        error = None
                        if not passed:
                            error = (
                                f"expression_path {expr_path!r} names a container/literal, "
                                f"not one whole {{% ... %}} expression -- materialized every "
                                f"nested {{% ... %}} sub-expression against sample#{sample_index} "
                                f"and compared the reconstructed value, which did not match "
                                f"expected_output (an equally-correct alternative decomposition "
                                f"would have matched here; this is a genuine value mismatch)"
                            )
                except Exception as exc:  # noqa: BLE001 - see the identical except below
                    actual = None
                    passed = False
                    error = f"{type(exc).__name__}: {exc}"
                covered_paths.add(expr_path)
                # Leaf {% %} expressions nested under this container were
                # just accounted for via materialize() above -- mark them
                # covered too so they don't ALSO surface as a separate,
                # redundant "no covering case" informational line below.
                container_prefix = f"[{doc_index}]{sub_path}" if multi else sub_path
                for leaf_path in found:
                    if leaf_path != container_prefix and (
                        leaf_path.startswith(container_prefix + ".") or leaf_path.startswith(container_prefix + "[")
                    ):
                        covered_paths.add(leaf_path)
                results.append(
                    Tier05CaseResult(
                        expression_path=expr_path,
                        expression="<decomposed: container materialized from its nested {% ... %} sub-expression(s)>",
                        sample_index=sample_index,
                        expected_output=case["expected_output"],
                        actual_output=actual,
                        passed=passed,
                        error=error,
                    )
                )
                continue
            # Case 1: genuinely nothing at this path either as a leaf
            # expression OR as a resolvable container/literal.
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
                        f"expression in the synthesized artifact, and structural "
                        f"resolution of that path against the raw ASL document "
                        f"found {len(matches)} node(s) (need exactly 1 to fall back "
                        f"to decomposition-materialization) -- a renamed/removed "
                        f"state, or a stale case, would land here (found leaf "
                        f"paths: {sorted(found)!r})"
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
            # INFORMATIONAL, not a failure (residual-findings fix,
            # 2026-08-06 -- benchmark-integrity review finding
            # "sfn-jsonata / Tier 0.5 anti-L2 oracle — false-positives on
            # equally-correct solutions"). This used to be `passed=False`,
            # which meant a solution that expresses the SAME semantics as a
            # spec's `cases` with a DIFFERENT (but equally correct)
            # decomposition -- e.g. per-field `{% %}` sub-expressions inside
            # an object literal, instead of one whole-object `{% %}`
            # expression -- was scored as an anti-L2 catch hit purely for
            # decomposition style, contaminating the H2 falsifiability
            # signal this tier exists to produce. `oracle.tier05_jsonata.cases`
            # is authored against ONE reference decomposition (this
            # scenario's own solve.sh); an uncovered expression elsewhere in
            # the artifact is surfaced here (passed=True, so it never fails
            # `run_tier05_or_raise`/`tier05_ok`) so it's still visible to a
            # human reviewing output, without penalizing a correct solution
            # that merely decomposed differently. A case whose own
            # `expression_path` matches NO expression in the artifact (the
            # inverse mismatch -- a renamed/removed state, or genuinely a
            # spec/fixture drift) is intentionally still a hard failure
            # above; only "found more expressions than cases name" is
            # softened here.
            results.append(
                Tier05CaseResult(
                    expression_path=expr_path,
                    expression=expr,
                    sample_index=-1,
                    expected_output=None,
                    actual_output=None,
                    passed=True,
                    error=(
                        f"INFORMATIONAL (non-failing): expression at {expr_path!r} "
                        f"has no covering case in oracle.tier05_jsonata.cases -- "
                        f"this scenario's cases are authored against one reference "
                        f"decomposition; an equally-correct solution using a "
                        f"different (e.g. more granular) decomposition legitimately "
                        f"introduces {{% %}} expressions no case names"
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
