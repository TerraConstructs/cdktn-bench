"""Tests for oracles/lib/tier05_jsonata.py.

Fixtures: `mini_asl_cfn_good.json` (one correct `{% ... %}` expression) and
`mini_asl_cfn_bad.json` (two bad ones embedded in an otherwise
well-formed outer template — a semantic bug, wrong literal, plus a real
JSONata syntax error) — the task brief's "a bad jsonata expr — prove
detection" case. Both classes must surface as a failed `Tier05CaseResult`,
never as an uncaught exception (that's the entire point of Tier 0.5: an
outer-template-only check sails right past both).

`mini_asl_cfn_multi_good.json` (two states, two DIFFERENT correct
expressions) is the regression fixture for the cartesian-product bug fixed
alongside `cases[].expression_path` (see TestRunTier05's docstring and
run_tier05's own).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oracles.lib.tier05_jsonata import (
    Tier05Error,
    evaluate,
    find_asl_documents,
    jsonata_expressions,
    run_tier05,
    run_tier05_or_raise,
    strip_braces,
)

FIXTURES = Path(__file__).parent / "fixtures"

EXPRESSIONS_FROM = "$.Resources[?(@.Type=='AWS::StepFunctions::StateMachine')].Properties.DefinitionString"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def asl_good() -> dict:
    return _load_json("mini_asl_cfn_good.json")


@pytest.fixture
def asl_bad() -> dict:
    return _load_json("mini_asl_cfn_bad.json")


@pytest.fixture
def asl_multi_good() -> dict:
    return _load_json("mini_asl_cfn_multi_good.json")


class TestStripBraces:
    def test_strips_wrapper(self):
        assert strip_braces("{% 'hello-' & $states.input.name %}") == "'hello-' & $states.input.name"

    def test_rejects_unwrapped_string(self):
        with pytest.raises(Tier05Error):
            strip_braces("not-an-expression")


class TestJsonataExpressions:
    def test_finds_single_expression(self, asl_good):
        definition_string = find_asl_documents(asl_good, EXPRESSIONS_FROM)[0]
        asl = json.loads(definition_string)
        found = jsonata_expressions(asl)
        assert len(found) == 1
        path, expr = found[0]
        assert expr == "{% 'hello-' & $states.input.name %}"
        assert path.endswith(".Output")

    def test_finds_multiple_expressions(self, asl_bad):
        definition_string = find_asl_documents(asl_bad, EXPRESSIONS_FROM)[0]
        asl = json.loads(definition_string)
        found = jsonata_expressions(asl)
        assert len(found) == 2


class TestEvaluate:
    def test_evaluates_against_states_input(self):
        assert evaluate("{% 'hello-' & $states.input.name %}", {"name": "world"}) == "hello-world"

    def test_bad_syntax_raises(self):
        with pytest.raises(Exception):  # noqa: B017 - jsonata-python's own exception type, intentionally broad
            evaluate("{% 'hello-' & & $states.input.name %}", {"name": "world"})


class TestFindAslDocuments:
    def test_resolves_definition_string_via_jsonpath(self, asl_good):
        nodes = find_asl_documents(asl_good, EXPRESSIONS_FROM)
        assert len(nodes) == 1
        assert isinstance(nodes[0], str)
        assert json.loads(nodes[0])["StartAt"] == "ComputeGreeting"


class TestRunTier05:
    """`cases` are keyed by `expression_path`, each case testing exactly the
    ONE expression it names — not the cartesian product of every found
    expression against every case (the bug this shape replaced: see
    run_tier05's own docstring for the exact "state C's count compared
    against state G's expected greeting" repro this fixed)."""

    def test_good_fixture_case_passes(self, asl_good):
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.ComputeGreeting.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                }
            ],
        }
        results = run_tier05(asl_good, spec_tier05)
        assert len(results) == 1
        assert all(r.passed for r in results)
        # run_tier05_or_raise must not raise on an all-green result set
        run_tier05_or_raise(asl_good, spec_tier05)

    def test_multi_expression_all_correct_machine_passes(self, asl_multi_good):
        # THE regression test for the cartesian-product bug: two states,
        # two different correct expressions, each with its OWN case. The
        # old (unkeyed) run_tier05 would have evaluated Count's expression
        # against Greet's sample input too (and vice versa) and rejected
        # this fully-correct machine.
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.Greet.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                },
                {
                    "expression_path": "$.States.Count.Output",
                    "input": {"items": [1, 2, 3]},
                    "expected_output": 3,
                },
            ],
        }
        results = run_tier05(asl_multi_good, spec_tier05)
        assert len(results) == 2
        assert all(r.passed for r in results), [r.explain() for r in results]
        run_tier05_or_raise(asl_multi_good, spec_tier05)  # must not raise

    def test_bad_fixture_detects_semantic_bug_without_crashing(self, asl_bad):
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.ComputeGreeting.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                },
                {
                    "expression_path": "$.States.BrokenSyntax.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                },
            ],
        }
        results = run_tier05(asl_bad, spec_tier05)
        # 2 cases, each matched to its own (bad) expression -- but the call
        # itself must not raise.
        assert len(results) == 2
        assert all(not r.passed for r in results)

        semantic_bug = [r for r in results if r.error is None]
        syntax_error = [r for r in results if r.error is not None]
        assert len(semantic_bug) == 1  # 'hi-world' != 'hello-world'
        assert semantic_bug[0].actual_output == "hi-world"
        assert len(syntax_error) == 1
        assert "&" in (syntax_error[0].error or "") or "JException" in (syntax_error[0].error or "")

    def test_run_tier05_or_raise_raises_on_bad_fixture(self, asl_bad):
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.ComputeGreeting.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                },
                {
                    "expression_path": "$.States.BrokenSyntax.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                },
            ],
        }
        with pytest.raises(Tier05Error, match=r"2/2 Tier-0\.5"):
            run_tier05_or_raise(asl_bad, spec_tier05)

    def test_run_tier05_or_raise_raises_when_no_expression_found(self, asl_good):
        spec_tier05 = {
            "expressions_from": "$.Resources[?(@.Type=='AWS::Lambda::Function')].Properties.DefinitionString",
            "cases": [
                {
                    "expression_path": "$.States.ComputeGreeting.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                }
            ],
        }
        with pytest.raises(Tier05Error, match="no {% ... %}"):
            run_tier05_or_raise(asl_good, spec_tier05)

    def test_renamed_state_is_caught_not_silently_skipped(self, asl_good):
        # A case pointing at a path that doesn't exist in the artifact (a
        # renamed/removed state) must FAIL, not be silently dropped --
        # otherwise a scenario author renaming a state (or a regenerated
        # artifact shifting a path) would quietly stop being graded at all.
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.NoSuchState.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                }
            ],
        }
        results = run_tier05(asl_good, spec_tier05)
        by_path = {r.expression_path: r for r in results}
        # 2 results: the declared-but-nonexistent case itself (must FAIL,
        # not vanish), PLUS the real expression the artifact does contain,
        # which is now uncovered by any case (must ALSO fail -- see
        # test_uncovered_expression_is_caught).
        assert len(results) == 2
        assert not by_path["$.States.NoSuchState.Output"].passed
        assert "matches no" in (by_path["$.States.NoSuchState.Output"].error or "")
        assert not by_path["$.States.ComputeGreeting.Output"].passed
        assert "no case" in (by_path["$.States.ComputeGreeting.Output"].error or "")

    def test_uncovered_expression_is_caught(self, asl_multi_good):
        # An expression the artifact contains but that no case covers must
        # also surface as a failure, not silently pass ungraded.
        spec_tier05 = {
            "expressions_from": EXPRESSIONS_FROM,
            "cases": [
                {
                    "expression_path": "$.States.Greet.Output",
                    "input": {"name": "world"},
                    "expected_output": "hello-world",
                }
                # $.States.Count.Output has no case here.
            ],
        }
        results = run_tier05(asl_multi_good, spec_tier05)
        uncovered = [r for r in results if r.expression_path == "$.States.Count.Output"]
        assert len(uncovered) == 1
        assert not uncovered[0].passed
        assert "no case" in (uncovered[0].error or "")
