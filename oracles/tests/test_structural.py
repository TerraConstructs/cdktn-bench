"""Tests for oracles/lib/structural.py.

Two layers, per the task brief ("prove detection"):
  - `Test*Ops` — direct unit tests of `apply_op`/`resolve`/`check_assert` on
    small hand-built documents, covering every op in `VALID_OPS` plus the
    error paths (unknown op, malformed `in`).
  - `TestToySpecIntegration` — the real `specs/_toy/toy-ssm-parameter.yaml`
    spec's tier-0 `structural_asserts`, run against the "good" and "bad"
    (deliberately mis-nested) fixture templates/plans in `oracles/tests/fixtures/`,
    for both the CFN-shaped (`awscdk`) and TF-shaped (`hcl_raw`,
    `terraconstructs`) artifact halves. This is the concrete "a deliberate
    mis-nesting... prove detection" case from the task brief: the bad
    fixtures keep the resource's own `Type` correctly nested (so
    `parameter-exists` still passes) but push `Name`/`Value` one level too
    deep, which only a real per-attribute path check catches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from oracles.lib.structural import (
    AssertResult,
    StructuralAssertError,
    apply_op,
    check,
    check_assert,
    check_spec_assert,
    resolve,
    run_tier0_asserts,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
TOY_SPEC_PATH = REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def toy_spec() -> dict:
    return yaml.safe_load(TOY_SPEC_PATH.read_text())


@pytest.fixture(scope="module")
def cfn_good() -> dict:
    return _load_json("mini_cfn_good.json")


@pytest.fixture(scope="module")
def cfn_bad() -> dict:
    return _load_json("mini_cfn_bad.json")


@pytest.fixture(scope="module")
def tf_good() -> dict:
    return _load_json("mini_tf_plan_good.json")


@pytest.fixture(scope="module")
def tf_bad() -> dict:
    return _load_json("mini_tf_plan_bad.json")


# --------------------------------------------------------------------------
# Unit-level: resolve() / apply_op() / check() / check_assert()
# --------------------------------------------------------------------------


class TestResolve:
    def test_filter_expression_finds_matching_resource(self, cfn_good):
        matches = resolve(cfn_good, "$.Resources[?(@.Type=='AWS::SSM::Parameter')]")
        assert len(matches) == 1
        assert matches[0]["Properties"]["Name"] == "/cdktn-bench-toy/greeting"

    def test_filter_expression_no_match_returns_empty(self, cfn_good):
        assert resolve(cfn_good, "$.Resources[?(@.Type=='AWS::Lambda::Function')]") == []

    def test_wildcard_across_nested_list(self, cfn_good):
        matches = resolve(
            cfn_good,
            "$.Resources[?(@.Type=='AWS::IAM::Role')].Properties.Policies[*].PolicyDocument.Statement[*].Action",
        )
        assert matches == [["ssm:GetParameter", "ssm:GetParameters"]]

    def test_mis_nested_path_resolves_to_nothing_not_an_error(self, cfn_bad):
        # The whole point of the "bad" fixture: this must NOT raise — a
        # missing/mis-nested attribute is a legitimate "0 matches" resolve,
        # which is what turns a real synth mistake into a failed assert
        # rather than a crashed test run.
        assert resolve(cfn_bad, "$.Resources[?(@.Type=='AWS::SSM::Parameter')].Properties.Name") == []


class TestApplyOp:
    def test_exists(self):
        assert apply_op("exists", None, [1]) is True
        assert apply_op("exists", None, []) is False

    def test_not_exists(self):
        assert apply_op("not_exists", None, []) is True
        assert apply_op("not_exists", None, [1]) is False

    def test_eq_requires_exactly_one_match(self):
        assert apply_op("eq", "x", ["x"]) is True
        assert apply_op("eq", "x", ["y"]) is False
        assert apply_op("eq", "x", []) is False
        assert apply_op("eq", "x", ["x", "x"]) is False  # ambiguous match count also fails

    def test_in_flattens_one_level(self):
        assert apply_op("in", ["a", "b"], [["a"]]) is True
        assert apply_op("in", ["a", "b"], ["a", "b"]) is True
        assert apply_op("in", ["a", "b"], ["c"]) is False
        assert apply_op("in", ["a", "b"], []) is False

    def test_in_requires_list_expected(self):
        with pytest.raises(ValueError):
            apply_op("in", "not-a-list", ["a"])

    def test_contains_scalar_in_list(self):
        assert apply_op("contains", "ec2.amazonaws.com", [["ec2.amazonaws.com"]]) is True
        assert apply_op("contains", "ec2.amazonaws.com", ["ec2.amazonaws.com"]) is True
        assert apply_op("contains", "ec2.amazonaws.com", ["lambda.amazonaws.com"]) is False

    def test_contains_substring_in_string(self):
        assert apply_op("contains", "ec2.amazonaws.com", ['{"Service":"ec2.amazonaws.com"}']) is True

    def test_regex(self):
        assert apply_op("regex", r"^/cdktn-bench-toy/", ["/cdktn-bench-toy/greeting"]) is True
        assert apply_op("regex", r"^/other/", ["/cdktn-bench-toy/greeting"]) is False
        assert apply_op("regex", r"^/x/", []) is False

    def test_unknown_op_raises(self):
        with pytest.raises(ValueError):
            apply_op("bogus", None, [])


class TestCheckAndCheckAssert:
    def test_check_returns_result_without_raising_on_failure(self, cfn_bad):
        result = check(cfn_bad, "param-name", "$.Resources[?(@.Type=='AWS::SSM::Parameter')].Properties.Name", "eq", "/cdktn-bench-toy/greeting")
        assert isinstance(result, AssertResult)
        assert result.passed is False
        assert result.actual == []
        assert "FAIL" in result.explain()

    def test_check_assert_raises_structural_assert_error_on_failure(self, cfn_bad):
        with pytest.raises(StructuralAssertError, match="param-name"):
            check_assert(cfn_bad, "param-name", "$.Resources[?(@.Type=='AWS::SSM::Parameter')].Properties.Name", "eq", "/cdktn-bench-toy/greeting")

    def test_check_assert_passes_silently_on_good_fixture(self, cfn_good):
        result = check_assert(cfn_good, "param-name", "$.Resources[?(@.Type=='AWS::SSM::Parameter')].Properties.Name", "eq", "/cdktn-bench-toy/greeting")
        assert result.passed is True


# --------------------------------------------------------------------------
# Integration: the real toy spec's tier-0 asserts vs. the good/bad fixtures
# --------------------------------------------------------------------------


class TestToySpecIntegration:
    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_tier0_asserts_pass_against_good_artifact(self, toy_spec, cfn_good, tf_good, arm):
        document = cfn_good if arm == "awscdk" else tf_good
        results = run_tier0_asserts(document, toy_spec["oracle"]["structural_asserts"], arm=arm)
        # parameter-exists, parameter-name-correct, parameter-value-correct,
        # role-trust-is-ec2-only, parameter-tier-standard (F2 fix,
        # 2026-08-06 -- Tier is absent from both good/bad fixtures here, so
        # this one passes on both, same as parameter-exists).
        assert len(results) == 5
        assert all(r.passed for r in results)

    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_tier0_asserts_detect_mis_nesting_in_bad_artifact(self, toy_spec, cfn_bad, tf_bad, arm):
        document = cfn_bad if arm == "awscdk" else tf_bad
        with pytest.raises(StructuralAssertError) as excinfo:
            run_tier0_asserts(document, toy_spec["oracle"]["structural_asserts"], arm=arm)
        message = str(excinfo.value)
        # The resource-level Type is untouched in the bad fixture, so the
        # bare existence check still passes...
        assert "parameter-exists" not in message
        # ...but every attribute pushed one level too deep is caught.
        assert "parameter-name-correct" in message
        assert "parameter-value-correct" in message
        assert "role-trust-is-ec2-only" in message
        assert "3/5" in message

    def test_check_spec_assert_single_entry(self, toy_spec, cfn_good):
        name_assert = next(a for a in toy_spec["oracle"]["structural_asserts"] if a["name"] == "parameter-name-correct")
        result = check_spec_assert(cfn_good, name_assert, arm="awscdk")
        assert result.passed is True

    def test_check_spec_assert_rejects_arm_not_in_applies_to(self, toy_spec, cfn_good):
        name_assert = dict(next(a for a in toy_spec["oracle"]["structural_asserts"] if a["name"] == "parameter-name-correct"))
        name_assert["applies_to"] = ["awscdk"]
        with pytest.raises(ValueError, match="does not apply"):
            check_spec_assert(cfn_good, name_assert, arm="hcl_raw")

    def test_tier1_asserts_are_never_run_by_run_tier0_asserts(self, toy_spec, cfn_good):
        # policy-resource-scoped-not-wildcard-{cfn,tf} / policy-actions-read-only
        # are tier "1" in the toy spec — run_tier0_asserts must skip them
        # entirely (they're the *.rego/*.guard spec, not something this
        # JSONPath evaluator runs). Confirmed indirectly by the count
        # assertion above (4, not 7); this test also checks their raw
        # cfn_jsonpath (which uses `||`/bare-value filter syntax, some of
        # which jsonpath_ng.ext cannot parse) is never even parsed.
        #
        # policy-resource-scoped-not-wildcard was split into
        # -cfn/-tf (benchmark-integrity finding G2, fixed 2026-08-06):
        # SCHEMA.md §4.2's "one tf_jsonpath covers both TF arms, same path
        # shape as cfn_jsonpath" claim is false for plan-time-unknown
        # attributes -- see specs/SCHEMA.md §4.2.1 and this spec's own
        # inline comments on that assert for the full story.
        tier1_names = {
            a["name"] for a in toy_spec["oracle"]["structural_asserts"] if a["tier"] == "1"
        }
        assert tier1_names == {
            "policy-resource-scoped-not-wildcard-cfn",
            "policy-resource-scoped-not-wildcard-tf",
            "policy-actions-read-only",
        }
        results = run_tier0_asserts(cfn_good, toy_spec["oracle"]["structural_asserts"], arm="awscdk")
        assert {r.name for r in results}.isdisjoint(tier1_names)
