"""Unit tests for `sfn-jsonata`'s hand-authored tests/live_check.py.

Covers the pure half only -- artifact detection, definition extraction from
both arms' artifact shapes, output comparison, and outcome mapping -- driven
by RECORDED `stepfunctions test-state` responses. Nothing here touches the
network: `call` is injected everywhere a real run would reach AWS.

The file under test lives in the generated task tree because that is where a
hand-authored live check lives (specs/SCHEMA.md §8.2 point 8); it is loaded by
path rather than imported, and every arm's copy is asserted byte-identical.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_CHECK_COPIES = sorted(REPO_ROOT.glob("tasks/*/sfn-jsonata-*/tests/live_check.py"))

# specs/sfn-jsonata.yaml enables exactly these arms, and each enabled arm's
# task dir carries the same hand-authored oracle.
ENABLED_ARMS = ("awscdk", "hcl-raw")


def _load():
    assert LIVE_CHECK_COPIES, "sfn-jsonata has no tests/live_check.py in any task dir"
    # tests/ is uploaded wholesale to the verifier container: compiling the
    # file under test must not leave a __pycache__ behind in a generated task
    # tree, which no `make gen` path sweeps and no `git status` shows.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "sfn_jsonata_live_check", LIVE_CHECK_COPIES[0]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


lc = _load()


# ---------------------------------------------------------------------------
# Recorded TestState responses (shape verified against the real API: `output`
# is a JSON-ENCODED STRING, a Choice returns `nextState`, `status` is a field
# of a 200 response body rather than an HTTP error).
# ---------------------------------------------------------------------------

CORRECT_COMPUTE_TOTALS = {
    "output": json.dumps(
        {
            "orders": [
                {"id": "o1", "qty": 2, "price": 10, "total": 20},
                {"id": "o2", "qty": 1, "price": 5, "total": 5},
            ],
            "grandTotal": 25,
        }
    ),
    "status": "SUCCEEDED",
    "nextState": "CheckBudget",
}

WRONG_COMPUTE_TOTALS = {
    "output": json.dumps(
        {
            "orders": [
                {"id": "o1", "qty": 2, "price": 10, "total": 20},
                {"id": "o2", "qty": 1, "price": 5, "total": 5},
            ],
            "grandTotal": 0,
        }
    ),
    "status": "SUCCEEDED",
    "nextState": "CheckBudget",
}

CHOICE_TO_FAIL = {"output": "{}", "status": "SUCCEEDED", "nextState": "OverBudget"}
CHOICE_TO_SUCCEED = {"output": "{}", "status": "SUCCEEDED", "nextState": "WithinBudget"}
STATE_FAILED = {
    "status": "FAILED",
    "error": "States.QueryEvaluationError",
    "cause": "the JSONata expression could not be evaluated",
}

DEFINITION = {
    "QueryLanguage": "JSONata",
    "StartAt": "ComputeTotals",
    "States": {
        "ComputeTotals": {
            "Type": "Pass",
            "Output": "{% $states.input %}",
            "Next": "CheckBudget",
        },
        "CheckBudget": {
            "Type": "Choice",
            "Choices": [
                {"Condition": "{% $states.input.grandTotal > 1000 %}", "Next": "OverBudget"}
            ],
            "Default": "WithinBudget",
        },
        "OverBudget": {"Type": "Fail", "Error": "GrandTotalExceedsBudget"},
        "WithinBudget": {"Type": "Succeed"},
    },
}

CFN_ARTIFACT = {
    "Resources": {
        "OrderBatchStateMachine": {
            "Type": "AWS::StepFunctions::StateMachine",
            "Properties": {"DefinitionString": json.dumps(DEFINITION)},
        }
    }
}

TF_ARTIFACT = {
    "planned_values": {
        "root_module": {
            "resources": [
                {"type": "aws_iam_role", "values": {"name": "sfn-exec"}},
                {
                    "type": "aws_sfn_state_machine",
                    "values": {"definition": json.dumps(DEFINITION)},
                },
            ]
        }
    }
}


def _candidates(tmp_path: Path, *, cfn: str | None, tf: str | None):
    cfn_path = tmp_path / "cdk.out" / "ScenarioStack.template.json"
    tf_path = tmp_path / "plan.json"
    if cfn is not None:
        cfn_path.parent.mkdir(parents=True, exist_ok=True)
        cfn_path.write_text(cfn)
    if tf is not None:
        tf_path.write_text(tf)
    return ((str(cfn_path), "cfn"), (str(tf_path), "tf"))


# ---------------------------------------------------------------------------
# Byte-identity across arms
# ---------------------------------------------------------------------------


def test_every_arms_copy_is_byte_identical() -> None:
    """The live oracle must not be able to tell which arm produced the state
    machine it is grading -- the same rule that makes the check arm-agnostic
    is what lets tests/test.sh invoke it with no arm branch."""
    # The count is asserted first: a single copy would make byte-identity
    # vacuously true, and one copy is exactly what a generator that stubbed
    # the other arm's oracle would leave behind.
    assert len(LIVE_CHECK_COPIES) == len(ENABLED_ARMS), (
        "sfn-jsonata must carry one tests/live_check.py per enabled arm "
        f"({', '.join(ENABLED_ARMS)}), found: "
        + ", ".join(str(p) for p in LIVE_CHECK_COPIES)
    )
    bodies = {p.read_bytes() for p in LIVE_CHECK_COPIES}
    assert len(bodies) == 1, (
        "sfn-jsonata's tests/live_check.py differs between arms: "
        + ", ".join(str(p) for p in LIVE_CHECK_COPIES)
    )


# ---------------------------------------------------------------------------
# Artifact detection
# ---------------------------------------------------------------------------


def test_detects_the_awscdk_template(tmp_path: Path) -> None:
    path, family = lc.detect_artifact(_candidates(tmp_path, cfn="{}", tf=None))
    assert family == "cfn"
    assert path.name == "ScenarioStack.template.json"


def test_detects_the_terraform_plan(tmp_path: Path) -> None:
    path, family = lc.detect_artifact(_candidates(tmp_path, cfn=None, tf="{}"))
    assert family == "tf"
    assert path.name == "plan.json"


def test_no_artifact_is_not_verifiable(tmp_path: Path) -> None:
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.detect_artifact(_candidates(tmp_path, cfn=None, tf=None))
    assert exc.value.kind == "no-artifact"


def test_an_empty_artifact_does_not_count_as_present(tmp_path: Path) -> None:
    """static_tiers.sh already scores an empty artifact 0.0; treating it as
    'this must be the other arm' would grade the wrong document."""
    with pytest.raises(lc.NotVerifiable):
        lc.detect_artifact(_candidates(tmp_path, cfn="", tf=None))


def test_two_artifacts_refuse_to_guess_the_arm(tmp_path: Path) -> None:
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.detect_artifact(_candidates(tmp_path, cfn="{}", tf="{}"))
    assert exc.value.kind == "no-artifact"


# ---------------------------------------------------------------------------
# Definition extraction
# ---------------------------------------------------------------------------


def test_extracts_the_definition_from_the_cfn_template() -> None:
    assert lc.extract_definition(CFN_ARTIFACT, "cfn") == DEFINITION


def test_extracts_the_definition_from_the_terraform_plan() -> None:
    assert lc.extract_definition(TF_ARTIFACT, "tf") == DEFINITION


@pytest.mark.parametrize("family, document", [("cfn", {"Resources": {}}), ("tf", {})])
def test_no_state_machine_is_not_verifiable(family: str, document: dict) -> None:
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.extract_definition(document, family)
    assert exc.value.kind == "no-state-machine"


def test_two_state_machines_are_not_verifiable() -> None:
    document = {
        "Resources": {
            "A": CFN_ARTIFACT["Resources"]["OrderBatchStateMachine"],
            "B": CFN_ARTIFACT["Resources"]["OrderBatchStateMachine"],
        }
    }
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.extract_definition(document, "cfn")
    assert exc.value.kind == "no-state-machine"


def _cfn_with(definition_string) -> dict:
    return {
        "Resources": {
            "SM": {
                "Type": "AWS::StepFunctions::StateMachine",
                "Properties": {"DefinitionString": definition_string},
            }
        }
    }


def test_a_literal_fn_join_definition_is_resolved() -> None:
    """Synthesis renders DefinitionString as a join as soon as the ASL carries
    any token, and the join is often still all literal parts. Refusing it
    would score a correct solution not_verifiable, i.e. 0.0 under gating."""
    encoded = json.dumps(DEFINITION)
    half = len(encoded) // 2
    document = _cfn_with({"Fn::Join": ["", [encoded[:half], encoded[half:]]]})
    assert lc.extract_definition(document, "cfn") == DEFINITION


def test_a_token_bearing_fn_join_is_not_verifiable() -> None:
    """A join with a nested intrinsic cannot be resolved without the deploy,
    so there is nothing to submit to TestState."""
    document = _cfn_with({"Fn::Join": ["", ["{\"a\": \"", {"Ref": "Role"}, "\"}"]]})
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.extract_definition(document, "cfn")
    assert exc.value.kind == "undecodable-definition"


def test_a_plan_time_unknown_definition_has_its_own_kind() -> None:
    """`terraform show -json` omits `values.definition` entirely when the
    encoded ASL embeds a computed attribute (specs/SCHEMA.md §4.2.1). That is
    a knownness condition, not a malformed artifact, and must be named."""
    document = {
        "planned_values": {
            "root_module": {
                "resources": [{"type": "aws_sfn_state_machine", "values": {}}]
            }
        }
    }
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.extract_definition(document, "tf")
    assert exc.value.kind == "plan-unknown-definition"
    assert "known after apply" in str(exc.value)


def test_unparseable_definition_json_is_not_verifiable() -> None:
    document = {
        "Resources": {
            "SM": {
                "Type": "AWS::StepFunctions::StateMachine",
                "Properties": {"DefinitionString": "{not json"},
            }
        }
    }
    with pytest.raises(lc.NotVerifiable) as exc:
        lc.extract_definition(document, "cfn")
    assert exc.value.kind == "undecodable-definition"


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def test_numbers_compare_as_numbers() -> None:
    assert lc.deep_equal({"grandTotal": 25.0}, {"grandTotal": 25})


def test_booleans_do_not_satisfy_numbers() -> None:
    assert not lc.deep_equal(True, 1)
    assert not lc.deep_equal(1, True)


def test_an_extra_key_is_not_equal() -> None:
    assert not lc.deep_equal({"a": 1, "b": 2}, {"a": 1})


def test_list_order_matters() -> None:
    assert not lc.deep_equal([1, 2], [2, 1])


# ---------------------------------------------------------------------------
# Case evaluation and outcome mapping
# ---------------------------------------------------------------------------


def _call_returning(*responses):
    queue = list(responses)
    return lambda definition, state, payload, **kwargs: queue.pop(0)


def _source_response(grand_total: int) -> dict:
    """What a chained case's source state (`ComputeTotals`) returns: the total
    in the state output AND in an assigned variable, which is the pair a
    JSONata-mode solution may legitimately choose between."""
    return {
        "output": json.dumps({"grandTotal": grand_total}),
        "status": "SUCCEEDED",
        "nextState": "CheckBudget",
        "inspectionData": {"variables": json.dumps({"grandTotal": grand_total})},
    }


def _case_named(name: str) -> dict:
    matches = [case for case in lc.CASES if case["name"] == name]
    assert len(matches) == 1, f"no single case named {name!r}"
    return matches[0]


def test_a_correct_output_matches() -> None:
    detail = lc.evaluate_case(
        lc.CASES[0], DEFINITION, _call_returning(CORRECT_COMPUTE_TOTALS)
    )
    assert detail["matched"] is True


def test_a_wrong_grand_total_does_not_match() -> None:
    detail = lc.evaluate_case(
        lc.CASES[0], DEFINITION, _call_returning(WRONG_COMPUTE_TOTALS)
    )
    assert detail["matched"] is False
    assert "computed a different value" in detail["reason"]


def test_the_choice_case_grades_the_type_of_the_state_reached() -> None:
    """The prompt fixes only `ComputeTotals` and `CheckBudget`; a correct
    solution may name its Fail state anything, so the branch is graded by the
    ASL Type of whatever state TestState says comes next."""
    detail = lc.evaluate_case(
        lc.CASES[2], DEFINITION, _call_returning(_source_response(2500), CHOICE_TO_FAIL)
    )
    assert detail["matched"] is True
    assert detail["next_state"] == "OverBudget"
    assert detail["next_state_type"] == "Fail"


def test_a_flipped_condition_routes_to_succeed_and_does_not_match() -> None:
    detail = lc.evaluate_case(
        lc.CASES[2],
        DEFINITION,
        _call_returning(_source_response(2500), CHOICE_TO_SUCCEED),
    )
    assert detail["matched"] is False
    assert detail["next_state_type"] == "Succeed"


def test_a_chained_case_feeds_the_source_states_output_and_variables() -> None:
    """A solution may `Assign` the total and branch on `{% $grandTotal > 1000 %}`.
    The graded call therefore has to carry what the source state actually
    produced -- output AND variables -- or that solution scores 0.0 while
    being correct."""
    calls: list[tuple] = []

    def record(definition, state, payload, **kwargs):
        calls.append((state, payload, kwargs))
        return _source_response(2500) if state == "ComputeTotals" else CHOICE_TO_FAIL

    detail = lc.evaluate_case(lc.CASES[2], DEFINITION, record)
    assert detail["matched"] is True
    assert calls[0][0] == "ComputeTotals"
    assert calls[0][2]["inspection_level"] == "DEBUG"
    assert calls[1][0] == "CheckBudget"
    assert calls[1][1] == {"grandTotal": 2500}
    assert json.loads(calls[1][2]["variables"]) == {"grandTotal": 2500}


def test_the_cap_itself_is_graded_on_the_succeed_side() -> None:
    """A grand total of exactly 1000 does not EXCEED 1000, so a `>=`
    condition routes it to the Fail state. Only a case at the boundary can
    see that."""
    case = _case_named("check-budget-at-threshold")
    assert case["expect_next_state_type"] == "Succeed"
    detail = lc.evaluate_case(
        case, DEFINITION, _call_returning(_source_response(1000), CHOICE_TO_FAIL)
    )
    assert detail["matched"] is False


def test_an_under_budget_batch_must_reach_a_succeed() -> None:
    """Without this case a condition of `{% true %}` -- everything over
    budget -- scores pass."""
    case = _case_named("check-budget-under-threshold")
    detail = lc.evaluate_case(
        case, DEFINITION, _call_returning(_source_response(500), CHOICE_TO_FAIL)
    )
    assert detail["matched"] is False
    detail = lc.evaluate_case(
        case, DEFINITION, _call_returning(_source_response(500), CHOICE_TO_SUCCEED)
    )
    assert detail["matched"] is True


def test_a_failing_source_state_is_a_solution_verdict_not_a_void() -> None:
    detail = lc.evaluate_case(lc.CASES[2], DEFINITION, _call_returning(STATE_FAILED))
    assert detail["matched"] is False
    assert "ComputeTotals" in detail["reason"]


def test_a_refused_definition_is_fail_stale_not_not_verifiable() -> None:
    """A ValidationException names a defect in the agent's ARTIFACT. Filing it
    as an infrastructure void would send the row back for a re-run instead of
    counting it as the agent failure it is."""

    def refuse(definition, state, payload, **kwargs):
        raise lc.DefinitionRejected(
            "ValidationException: Invalid State Machine Definition"
        )

    detail = lc.evaluate_case(lc.CASES[0], DEFINITION, refuse)
    assert detail["matched"] is False
    assert lc.outcome_from([detail]) == "fail_stale"


# ---------------------------------------------------------------------------
# Reaching the graded branch
# ---------------------------------------------------------------------------


def test_an_intermediate_state_still_reaches_the_expected_type() -> None:
    """The prompt requires the execution to REACH a Fail state, not to reach
    it in one hop."""
    definition = {
        "States": {
            "Announce": {"Type": "Pass", "Next": "OverBudget"},
            "OverBudget": {"Type": "Fail"},
        }
    }
    assert lc.reached_state_type(definition, "Announce", "Fail") == ("Fail", "OverBudget")


def test_a_nested_state_is_resolved() -> None:
    """`nextState` need not be a top-level key: the graded Choice may sit
    inside a Parallel branch or a Map iterator."""
    definition = {
        "States": {
            "Work": {
                "Type": "Parallel",
                "Branches": [{"States": {"Deep": {"Type": "Fail"}}}],
            }
        }
    }
    assert lc.reached_state_type(definition, "Deep", "Fail") == ("Fail", "Deep")


def test_a_cyclic_next_chain_terminates() -> None:
    definition = {
        "States": {
            "A": {"Type": "Pass", "Next": "B"},
            "B": {"Type": "Pass", "Next": "A"},
        }
    }
    assert lc.reached_state_type(definition, "A", "Fail")[0] == "Pass"


def test_a_non_succeeded_status_is_a_verdict_not_an_infrastructure_error() -> None:
    """The service rejected the AGENT's own expression -- a 200 response with
    status FAILED, not an API failure."""
    detail = lc.evaluate_case(lc.CASES[0], DEFINITION, _call_returning(STATE_FAILED))
    assert detail["matched"] is False
    assert detail["status"] == "FAILED"


def test_outcome_is_pass_only_when_every_case_matched() -> None:
    assert lc.outcome_from([{"matched": True}, {"matched": True}]) == "pass"
    assert lc.outcome_from([{"matched": True}, {"matched": False}]) == "fail_stale"


def test_no_cases_is_never_a_pass() -> None:
    assert lc.outcome_from([]) == "not_verifiable"


def test_run_evaluates_every_declared_case() -> None:
    result = lc.run(
        lc.CASES,
        DEFINITION,
        _call_returning(
            CORRECT_COMPUTE_TOTALS,
            CORRECT_COMPUTE_TOTALS,
            _source_response(2500),
            CHOICE_TO_FAIL,
            _source_response(1000),
            CHOICE_TO_SUCCEED,
            _source_response(500),
            CHOICE_TO_SUCCEED,
        ),
    )
    assert len(result["cases"]) == len(lc.CASES)
    assert result["outcome"] == "fail_stale"  # case 2 uses a different batch
    assert result["failures"]


def test_run_propagates_an_api_failure_instead_of_scoring_it() -> None:
    def boom(definition, state, payload, **kwargs):
        raise lc.NotVerifiable("access-denied", "AccessDeniedException")

    with pytest.raises(lc.NotVerifiable):
        lc.run(lc.CASES, DEFINITION, boom)


@pytest.mark.parametrize(
    "stderr, kind",
    [
        ("An error occurred (AccessDeniedException) when calling TestState", "access-denied"),
        (
            "An error occurred (ValidationException): bad definition",
            "invalid-definition",
        ),
        (
            "An error occurred (ValidationException): State ComputeTotals does "
            "not exist",
            "invalid-definition",
        ),
        ("An error occurred (InternalServerError): try again", "api-error"),
    ],
)
def test_cli_failures_are_classified_for_the_operator(stderr: str, kind: str) -> None:
    assert lc._classify_cli_failure(stderr)[0] == kind


def test_throttling_never_reaches_this_classifier() -> None:
    """Retry is the shared runner's job, not this file's.

    tests/_live_lib.py retries the transient class and raises
    TransientExhausted only once its budget is spent, so a throttle arriving
    here would mean the call bypassed it -- and this classifier would turn a
    retryable outage into an unretried "api-error" 0.0."""
    assert lc._classify_cli_failure(
        "An error occurred (ThrottlingException): Rate exceeded"
    )[0] == "api-error"
    assert "throttled" not in lc.NotVerifiable.__doc__
