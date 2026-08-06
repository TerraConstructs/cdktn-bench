"""Differential test: the jq-based grader that actually runs inside a trial
(generator/gen.py::ASSERT_LIB_SH, compiled into every generated
tests/_assert_lib.sh) vs. the Python jsonpath-ng-based reference evaluator
(oracles/lib/structural.py) that oracle-equivalence CI and spec-authoring
tooling use.

Both implement the SAME `specs/SCHEMA.md` §4.2 op table, but they used to
disagree on 3 of 6 ops (see the benchmark-integrity review this test was
added to close out):

  - `eq`      : the shell allowed >=1 duplicate matches to all-equal-pass;
                SCHEMA.md §4.2 says "the *(single)* resolved value".
  - `contains`: the shell used `test($e; "")` (a REGEX match) for strings,
                so an expected substring like "ec2.amazonaws.com" would
                also match unrelated text like "ec2Xamazonaws.com" via the
                unescaped "." wildcard -- a real, security-relevant false
                PASS on a role-trust check, not just an academic mismatch.
  - `in`      : the shell didn't flatten a bare-string-vs-list-of-strings
                property (e.g. IAM `Action`) the way the Python evaluator
                (and the toy spec's own `policy-actions-read-only` intent)
                does.

  - `not_exists` additionally had a *shell-only* bug (not a disagreement
    with structural.py, which was already correct): jq's plain field
    access (`.Foo`) returns JSON `null` for an absent key instead of no
    match at all, so a query over N matched objects where none has `Foo`
    collected as `[null, null, ...]` (length N, not 0) -- `not_exists`
    then failed unconditionally, including against a known-good artifact.

This test runs the REAL generated bash function (extracted from
`generator.gen.ASSERT_LIB_SH`, not a re-implementation of it) against the
same fixture documents/expressions Python's `apply_op` sees, and asserts
they agree. Requires `jq` and `bash` on PATH (both are the "guaranteed
present everywhere" baseline this whole design leans on --
DECISIONS.md "Agent-container baseline contract").
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import ASSERT_LIB_SH  # noqa: E402
from jsonpath_jq import jsonpath_to_jq  # noqa: E402

from oracles.lib.structural import apply_op, resolve  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="jq and bash are required to exercise the real generated grader",
)


def _jq_assert(tmp_path: Path, jsonpath: str, op: str, expected, document: dict) -> bool:
    """Run the REAL assert_check() bash function (as it is generated into
    every task's tests/_assert_lib.sh) against `document`, and return its
    pass/fail verdict as a bool -- mirroring what oracles.lib.structural's
    apply_op(op, expected, resolve(document, jsonpath)) returns for the
    Python side, so the two are directly comparable."""
    lib_path = tmp_path / "_assert_lib.sh"
    lib_path.write_text(ASSERT_LIB_SH)
    doc_path = tmp_path / "doc.json"
    doc_path.write_text(json.dumps(document))

    jq_filter = jsonpath_to_jq(jsonpath)
    expected_json = json.dumps(expected)
    script = (
        f"source {shlex.quote(str(lib_path))}\n"
        f"assert_check name {shlex.quote(jq_filter)} {shlex.quote(op)} "
        f"{shlex.quote(expected_json)} {shlex.quote(str(doc_path))}\n"
    )
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def _agree(tmp_path: Path, jsonpath: str, op: str, expected, document: dict) -> None:
    py_actual = resolve(document, jsonpath)
    py_pass = apply_op(op, expected, py_actual)
    jq_pass = _jq_assert(tmp_path, jsonpath, op, expected, document)
    assert py_pass == jq_pass, (
        f"op parity violation: op={op!r} expected={expected!r} "
        f"jsonpath={jsonpath!r} python={py_pass} shell={jq_pass} "
        f"(python resolved={py_actual!r})"
    )


class TestEqParity:
    def test_single_match_equal_passes_both(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "a"}]}
        _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc)

    def test_duplicate_matches_fail_both(self, tmp_path: Path) -> None:
        # Two identical SSM parameters -- SCHEMA.md §4.2 says "the *(single)*
        # resolved value", so >1 match (even if all equal) must FAIL, not
        # pass-by-coincidence. This used to PASS in the shell (any-equal
        # semantics) and FAIL in Python (exactly-one semantics).
        doc = {"Items": [{"Name": "a"}, {"Name": "a"}]}
        _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc)

    def test_mismatch_fails_both(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "b"}]}
        _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc)


class TestContainsParity:
    def test_literal_dot_is_not_a_wildcard(self, tmp_path: Path) -> None:
        # This is the exact false-PASS the finding demonstrated: a regex
        # engine treats "." as "any character", so "ec2.amazonaws.com"
        # would match "ec2Xamazonaws.com" -- contains must be a literal
        # substring test, so this must FAIL in both evaluators.
        doc = {"Principal": {"Service": "ec2Xamazonaws.com"}}
        _agree(tmp_path, "$.Principal.Service", "contains", "ec2.amazonaws.com", doc)

    def test_real_substring_passes_both(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "ec2.amazonaws.com"}}
        _agree(tmp_path, "$.Principal.Service", "contains", "ec2.amazonaws.com", doc)


class TestInParity:
    def test_bare_string_action_passes_both(self, tmp_path: Path) -> None:
        doc = {"Statement": [{"Action": "ssm:GetParameter"}]}
        _agree(
            tmp_path,
            "$.Statement[*].Action",
            "in",
            ["ssm:GetParameter", "ssm:GetParameters"],
            doc,
        )

    def test_list_valued_action_passes_both(self, tmp_path: Path) -> None:
        # This is the toy spec's own shape: Action can resolve to an array
        # (["ssm:GetParameter"]) rather than a bare string across different
        # matched statements -- both evaluators must flatten one level
        # before checking membership.
        doc = {"Statement": [{"Action": ["ssm:GetParameter"]}]}
        _agree(
            tmp_path,
            "$.Statement[*].Action",
            "in",
            ["ssm:GetParameter", "ssm:GetParameters"],
            doc,
        )

    def test_disallowed_action_fails_both(self, tmp_path: Path) -> None:
        doc = {"Statement": [{"Action": ["ssm:PutParameter"]}]}
        _agree(
            tmp_path,
            "$.Statement[*].Action",
            "in",
            ["ssm:GetParameter", "ssm:GetParameters"],
            doc,
        )


class TestSetEqParity:
    """set_eq closes the "op table cannot express exhaustiveness" gap:
    role-trust-is-ec2-only-style checks used `contains`/`in`, which pass as
    long as the correct value is PRESENT -- an extra, unintended value (a
    second trusted principal, a broader Resource) is invisible to both.
    set_eq requires the resolved set to equal expected exactly."""

    def test_exact_match_passes_both(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "ec2.amazonaws.com"}}
        _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)

    def test_extra_unintended_principal_fails_both(self, tmp_path: Path) -> None:
        # This is exactly what `contains`/`in` miss: ec2.amazonaws.com IS
        # present, but so is an unintended second principal -- the real
        # role-trust-is-ec2-only intent ("trusts ONLY ec2.amazonaws.com")
        # requires this to FAIL, not pass-by-partial-match.
        doc = {"Principal": {"Service": ["ec2.amazonaws.com", "lambda.amazonaws.com"]}}
        _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)

    def test_missing_expected_value_fails_both(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "lambda.amazonaws.com"}}
        _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)


class TestFromjsonParity:
    """The `|fromjson` path-grammar extension (generator/jsonpath_jq.py,
    oracles/lib/structural.py) -- lets a tier-0 assert reach inside a
    Terraform plan JSON attribute (or CFN Fn::Join-flattened string) that is
    itself a JSON-encoded string rather than nested structure, e.g. a
    `container_definitions` blob. Without it, the finding's flagship
    nested-attribute catch (ECS swappiness hoisted to the wrong nesting
    level) is invisible on the TF side no matter how correct the outer
    tier-0/tier-1 machinery is -- the path just resolves against the raw
    undecoded string and finds nothing."""

    def test_correctly_nested_swappiness_found(self, tmp_path: Path) -> None:
        doc = {
            "values": {
                "container_definitions": json.dumps(
                    [{"name": "app", "linuxParameters": {"swappiness": 60}}]
                )
            }
        }
        _agree(
            tmp_path,
            "$.values.container_definitions|fromjson[*].linuxParameters.swappiness",
            "eq",
            60,
            doc,
        )

    def test_mis_nested_swappiness_not_found(self, tmp_path: Path) -> None:
        # Swappiness hoisted to the container-definition level instead of
        # nested under linuxParameters -- the exact mis-nesting the
        # taxonomy's flagship catch targets.
        doc = {
            "values": {
                "container_definitions": json.dumps(
                    [{"name": "app", "swappiness": 60, "linuxParameters": {}}]
                )
            }
        }
        _agree(
            tmp_path,
            "$.values.container_definitions|fromjson[*].linuxParameters.swappiness",
            "not_exists",
            None,
            doc,
        )


class TestAbsentOrEqParity:
    """absent_or_eq -- added by a residual-findings fix (2026-08-06) for
    the 'left at its implied default' catch shape: `not_exists` alone
    false-negatived a fully correct solution that wrote the semantically
    identical value explicitly instead of omitting it (the toy spec's own
    parameter-tier-standard assert, e.g. `tier = "Standard"` vs. omitted)."""

    def test_absent_passes_both(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Name": "p"}]}
        _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)

    def test_explicit_default_passes_both(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Tier": "Standard"}]}
        _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)

    def test_wrong_enum_value_fails_both(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Tier": "Advanced"}]}
        _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)

    def test_duplicate_matches_fail_both(self, tmp_path: Path) -> None:
        # Same ambiguity rule as bare `eq`: >1 resolved node is a failure
        # even if every value equals expected, not "pick one".
        doc = {"Resources": [{"Tier": "Standard"}, {"Tier": "Standard"}]}
        _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)


class TestNotExistsParity:
    def test_genuinely_absent_field_passes_both(self, tmp_path: Path) -> None:
        # The ECS-swappiness-style catch: LinuxParameters has no Swappiness
        # key at all (correctly nested elsewhere), so this must PASS
        # (0 matches). The pre-fix shell collected `[null]` here (length 1)
        # and FAILED unconditionally -- this is the flagship regression
        # test for that bug.
        doc = {"ContainerDefinitions": [{"LinuxParameters": {"InitProcessEnabled": True}}]}
        _agree(
            tmp_path,
            "$.ContainerDefinitions[*].LinuxParameters.Swappiness",
            "not_exists",
            None,
            doc,
        )

    def test_present_field_fails_both(self, tmp_path: Path) -> None:
        doc = {"ContainerDefinitions": [{"Swappiness": 60}]}
        _agree(tmp_path, "$.ContainerDefinitions[*].Swappiness", "not_exists", None, doc)


class TestNotRegexParity:
    """not_regex -- added for specs/sfn-jsonata.yaml's mode-mixing catch
    ("no raw un-evaluated JSONPath string anywhere in this JSONata-mode
    ASL"). Literal negation of `regex`'s own per-value match test, except
    0 resolved nodes vacuously PASSES (nothing present to violate a "must
    never contain X" rule) rather than failing `regex`'s own ">=1 node"
    requirement."""

    def test_pattern_absent_passes_both(self, tmp_path: Path) -> None:
        doc = {"Definition": '{"Output": "{% $states.input.orders %}"}'}
        _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc)

    def test_pattern_present_fails_both(self, tmp_path: Path) -> None:
        # A raw, un-evaluated JSONPath string ("$.orders") used as a
        # literal value instead of a proper {% ... %} expression -- exactly
        # the mode-mixing trap this op exists to catch.
        doc = {"Definition": '{"Output": "$.orders"}'}
        _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc)

    def test_zero_resolved_nodes_passes_both(self, tmp_path: Path) -> None:
        # No node at all to check -- vacuously compliant, unlike `regex`
        # (which requires >=1 match).
        doc = {"Other": "irrelevant"}
        _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc)
