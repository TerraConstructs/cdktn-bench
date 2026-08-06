"""oracles/lib/structural.py

Path-based structural assertions against synthesized CloudFormation JSON
(the `awscdk` arm's `cdk.out/ScenarioStack.template.json`) and Terraform
plan JSON (`terraform show -json` output, shared by the `hcl_raw` and
`terraconstructs` arms — `specs/SCHEMA.md` §4.2).

Implements the **tier-"0"** half of the spec's `oracle.structural_asserts`
contract (`specs/SCHEMA.md` §4.2): each assert is
`{name, cfn_jsonpath | tf_jsonpath, op, expected}`; this module resolves the
path with `jsonpath-ng` (Goessner JSONPath plus its `[?(@.cond)]` filter
extension, `jsonpath_ng.ext`) and applies `op`.

Tier-"1" asserts are deliberately **not** evaluated here — per SCHEMA §4.2,
those are the *spec* for the hand-authored `oracles/rego/<id>/policy.rego`
and `oracles/cfn-guard/<id>/policy.guard` files, not something this
JSONPath-based evaluator runs directly. Concretely: some tier-"1" paths in
`specs/_toy/toy-ssm-parameter.yaml` (e.g. the `||`-combined
`AWS::IAM::Policy' || @.Type=='AWS::IAM::Role`) filter) use syntax
`jsonpath_ng.ext` cannot parse at all — that is expected and correct; a
generated `tests/static_tiers.sh` must only ever call `check_assert` for
entries whose `tier == "0"`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jsonpath_ng.ext import parse as _jsonpath_parse

VALID_OPS = frozenset(
    {
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
        "absent_or_eq", "not_regex",
    }
)

# Matches generator/jsonpath_jq.py's FROMJSON_SEP grammar extension: one or
# more `|fromjson` markers splitting a path into segments, where each
# segment after the first is resolved against the JSON-decoding of every
# node the previous segment resolved to (a Terraform plan JSON attribute
# like `values.container_definitions`/`values.assume_role_policy`/
# `values.policy`, or a CFN `DefinitionString`, stores its value as a JSON
# *string*, not nested structure -- see jsonpath_to_jq's own docstring for
# the full rationale). jsonpath-ng has no native pipe-to-fromjson operator,
# so this is implemented by resolving segment-by-segment in Python instead
# of compiling one combined expression.
FROMJSON_SEP = "|fromjson"


class StructuralAssertError(AssertionError):
    """Raised by `check_assert` (never by `resolve`/`apply_op` themselves) —
    carries a human-legible explanation of exactly which assert failed and
    what was actually found, for a pytest/CI failure message or a
    `static_tiers.sh` log line."""


@dataclass(frozen=True)
class AssertResult:
    name: str
    expression: str
    op: str
    expected: Any
    actual: list[Any]
    passed: bool

    def explain(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] {self.name}: {self.op}({self.expression!r}"
            f"{', expected=' + repr(self.expected) if self.expected is not None else ''}) "
            f"-> actual={self.actual!r}"
        )


def resolve(document: dict, expression: str) -> list[Any]:
    """Resolve a JSONPath expression (the shape of `cfn_jsonpath`/
    `tf_jsonpath` in `specs/SCHEMA.md` §4.2 — Goessner JSONPath plus
    `[?(@.cond)]` filters, plus the `|fromjson` extension for
    JSON-string-valued attributes, see FROMJSON_SEP above) against a parsed
    JSON document. Returns every matched value, in document order (may be
    empty).

    Raises `jsonpath_ng.exceptions.JsonPathParserError` on a syntax the
    parser can't handle. That is a deliberate signal, not a bug to work
    around: a tier-"1"-only expression reaching this function is itself the
    bug (see module docstring) — callers should let it propagate rather
    than catch-and-hide it.
    """
    if FROMJSON_SEP in expression:
        return _resolve_with_fromjson(document, expression)
    compiled = _jsonpath_parse(expression)
    return [match.value for match in compiled.find(document)]


def _resolve_with_fromjson(document: dict, expression: str) -> list[Any]:
    segments = expression.split(FROMJSON_SEP)
    nodes: list[Any] = [document]
    for i, seg in enumerate(segments):
        seg = seg.strip()
        compiled = _jsonpath_parse(seg if i == 0 else ("$" + seg if seg else "$"))
        next_nodes: list[Any] = []
        for node in nodes:
            next_nodes.extend(match.value for match in compiled.find(node))
        nodes = next_nodes
        if i < len(segments) - 1:
            decoded: list[Any] = []
            for node in nodes:
                if not isinstance(node, str):
                    raise StructuralAssertError(
                        f"|fromjson: expected a JSON string at segment {i} of "
                        f"{expression!r}, got {type(node).__name__}: {node!r}"
                    )
                decoded.append(json.loads(node))
            nodes = decoded
    return nodes


def _flatten_once(values: list[Any]) -> list[Any]:
    """Flatten one level of list-nesting (e.g. an `Action` property that is
    sometimes a bare string, sometimes a list of strings, across different
    matched statements) — used by `in`/`contains` so both shapes compare
    the same way."""
    flat: list[Any] = []
    for value in values:
        if isinstance(value, list):
            flat.extend(value)
        else:
            flat.append(value)
    return flat


def _contains_one(value: Any, expected: Any) -> bool:
    if isinstance(value, str) and isinstance(expected, str):
        return expected in value
    if isinstance(value, (list, tuple, set)):
        return expected in value
    return value == expected


def apply_op(op: str, expected: Any, actual: list[Any]) -> bool:
    """Apply one `specs/SCHEMA.md` §4.2 `op` to the values `resolve`
    returned. Pure function — no I/O, easy to unit-test in isolation from
    JSONPath parsing."""
    if op not in VALID_OPS:
        raise ValueError(f"unknown op {op!r}; must be one of {sorted(VALID_OPS)}")

    if op == "exists":
        return len(actual) > 0

    if op == "not_exists":
        return len(actual) == 0

    if op == "eq":
        # SCHEMA §4.2: "the (single) resolved value equals `expected`" — a
        # path resolving to 0 or >1 nodes fails 'eq' outright rather than
        # picking one arbitrarily; that ambiguity is itself a failure.
        return len(actual) == 1 and actual[0] == expected

    if op == "in":
        if not isinstance(expected, (list, tuple, set)):
            raise ValueError("op 'in' requires a list `expected`")
        flat = _flatten_once(actual)
        return len(flat) > 0 and all(value in expected for value in flat)

    if op == "contains":
        return any(_contains_one(value, expected) for value in actual)

    if op == "regex":
        pattern = re.compile(expected)
        return len(actual) > 0 and all(
            isinstance(value, str) and pattern.search(value) is not None
            for value in actual
        )

    if op == "not_regex":
        # Literal negation of `regex` -- an unanchored search (matches
        # ANYWHERE in the string, same as `regex`), never a full-string
        # match. Unlike `regex`, 0 resolved nodes vacuously PASSES (nothing
        # present to violate the "must never contain X" rule) rather than
        # failing the ">= 1 node" requirement `regex` itself has -- added
        # for the sfn-jsonata mode-mixing catch's "no raw un-evaluated
        # JSONPath string anywhere in this JSONata-mode ASL" fact, which
        # `regex` alone cannot express (it can only assert presence, never
        # absence) and `not_exists` cannot express either (that checks for
        # an absent KEY, not an absent substring inside an arbitrary
        # string value) -- see specs/SCHEMA.md §4.2's op table entry.
        pattern = re.compile(expected)
        return all(
            not (isinstance(value, str) and pattern.search(value) is not None)
            for value in actual
        )

    if op == "absent_or_eq":
        # Residual finding fix (2026-08-06): "resolves to nothing OR
        # resolves to exactly the explicit default" -- the op the
        # 'parameter-tier-standard'-style catch actually needs. `not_exists`
        # alone false-negatived a fully correct solution that wrote the
        # semantically-identical explicit default (e.g. `tier = "Standard"`)
        # instead of omitting the field; `eq` alone rejects the (also
        # correct, and in fact more common per-arm) omitted-field form.
        # Ambiguity (>1 resolved node) is a failure here too, same
        # rationale as bare `eq`.
        return len(actual) == 0 or (len(actual) == 1 and actual[0] == expected)

    if op == "set_eq":
        # SCHEMA §4.2: exact set equality (flattened one level, same
        # bare-string-or-list-of-strings normalization as 'in') -- the
        # "and nothing else" op the "scoped, not broader" catch family
        # needs, which neither 'in' (subset-only) nor 'contains'
        # (any-match-only) can express: a correct value plus an EXTRA,
        # unintended one passes both of those but must fail set_eq.
        if not isinstance(expected, (list, tuple, set)):
            raise ValueError("op 'set_eq' requires a list `expected`")
        flat = _flatten_once(actual)
        return set(flat) == set(expected)

    raise AssertionError(f"unreachable: op {op!r} in VALID_OPS but unhandled")


def check(document: dict, name: str, expression: str, op: str, expected: Any = None) -> AssertResult:
    """Resolve + apply in one call, returning a structured `AssertResult`
    (never raises on assert *failure* — only on a malformed expression/op,
    same as `resolve`/`apply_op`). Use this from a test that wants to
    collect multiple results before deciding pass/fail; use `check_assert`
    below to fail fast."""
    actual = resolve(document, expression)
    passed = apply_op(op, expected, actual)
    return AssertResult(name=name, expression=expression, op=op, expected=expected, actual=actual, passed=passed)


def check_assert(document: dict, name: str, expression: str, op: str, expected: Any = None) -> AssertResult:
    """Same as `check`, but raises `StructuralAssertError` on failure — the
    call generated `static_tiers.sh`/pytest tests should use when a failing
    assert must abort the tier immediately."""
    result = check(document, name, expression, op, expected)
    if not result.passed:
        raise StructuralAssertError(result.explain())
    return result


def check_spec_assert(document: dict, assert_spec: dict, *, arm: str) -> AssertResult:
    """Run one `oracle.structural_asserts[i]` entry (as parsed from a
    scenario's YAML, `specs/SCHEMA.md` §4.2) against `document`, picking
    `cfn_jsonpath` or `tf_jsonpath` by `arm`. Raises `StructuralAssertError`
    on failure. Raises `KeyError`/`ValueError` if `assert_spec` doesn't
    apply to `arm` at all (caller bug — check `applies_to` first) or is
    missing the path field `arm` needs.
    """
    applies_to = assert_spec.get("applies_to", ["awscdk", "hcl_raw", "terraconstructs"])
    if arm not in applies_to:
        raise ValueError(f"assert {assert_spec['name']!r} does not apply to arm {arm!r} (applies_to={applies_to!r})")

    if arm == "awscdk":
        path_field = "cfn_jsonpath"
    elif arm in ("hcl_raw", "terraconstructs"):
        path_field = "tf_jsonpath"
    else:
        raise ValueError(f"unknown arm {arm!r}")

    expression = assert_spec.get(path_field)
    if not expression:
        raise ValueError(f"assert {assert_spec['name']!r} has no {path_field!r} for arm {arm!r}")

    return check_assert(
        document,
        name=assert_spec["name"],
        expression=expression,
        op=assert_spec["op"],
        expected=assert_spec.get("expected"),
    )


def run_tier0_asserts(document: dict, structural_asserts: list[dict], *, arm: str) -> list[AssertResult]:
    """Run every `tier == "0"` entry in `structural_asserts` that applies to
    `arm`, collecting all results (does not fail fast — a generated
    `static_tiers.sh` wants to report every tier-0 failure in one pass, not
    just the first). Raises `StructuralAssertError` summarizing every
    failure if any occurred, after running the full set.
    """
    results: list[AssertResult] = []
    failures: list[AssertResult] = []
    for assert_spec in structural_asserts:
        if assert_spec.get("tier", "0") != "0":
            continue
        applies_to = assert_spec.get("applies_to", ["awscdk", "hcl_raw", "terraconstructs"])
        if arm not in applies_to:
            continue
        result = check(
            document,
            name=assert_spec["name"],
            expression=assert_spec["cfn_jsonpath"] if arm == "awscdk" else assert_spec["tf_jsonpath"],
            op=assert_spec["op"],
            expected=assert_spec.get("expected"),
        )
        results.append(result)
        if not result.passed:
            failures.append(result)

    if failures:
        raise StructuralAssertError(
            f"{len(failures)}/{len(results)} tier-0 structural assert(s) failed for arm {arm!r}:\n"
            + "\n".join(f.explain() for f in failures)
        )
    return results
