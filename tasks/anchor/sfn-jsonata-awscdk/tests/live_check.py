#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (specs/SCHEMA.md §5), the live GATING
oracle of `sfn-jsonata` (specs/sfn-jsonata.yaml). Why only a live check can see
this catch, what each case asserts and the two call shapes:
docs/sfn-jsonata-live-check.md.

`make gen SPEC=specs/sfn-jsonata.yaml` will NOT overwrite this file:
write_tests_dir() is destructive-safe for tests/live_check.py while
verifier.live_check.hand_authored is true (SCHEMA.md §8.2 point 8).

ARM-AGNOSTIC BY CONSTRUCTION: byte-identical in both enabled arms' task
directories, with no arm branch here or in tests/test.sh -- the arm is inferred
from WHICH synthesized artifact is on disk, since each arm's own
static_tiers.sh produces exactly one of them.

OUTCOME CONTRACT (SCHEMA.md §5, gating): a JSON object on stdout whose
`outcome` is "pass" (every case matched), "fail_stale" (a verdict about the
agent's artifact) or "not_verifiable" (the check could not run at all -- never
a statement about the solution). tests/test.sh voids the row for an unanswered
check ("transient-exhausted", "api-error") -- no reward file, trial invalid --
and scores 0.0 for anything else that is not "pass", so `reason` and
`not_verifiable_kind` are what keep an infrastructure failure legible as one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _live_lib import TransientExhausted, run_aws  # noqa: E402

SCENARIO = "sfn-jsonata"

# The synthesized artifact each arm's own tests/static_tiers.sh leaves behind,
# and the document family it is. Exactly one exists in any given task
# container; that is what makes the arm inferable here instead of branched on
# by the caller. Paths match static_tiers.sh's own `ARTIFACT=` line.
ARTIFACT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("/app/project/cdk.out/ScenarioStack.template.json", "cfn"),
    ("/app/project/plan.json", "tf"),
)

# Each case pins ONE state, the input that state receives, and what Step
# Functions must produce for it. Two cases share `ComputeTotals` on purpose:
# a fully hardcoded Output tuned to the first batch cannot also satisfy the
# second, so "computed" is distinguished from "guessed" without inspecting
# the expression at all. Three cases share `CheckBudget`, one on each side of
# the cap and one exactly AT it: a Choice graded only above the threshold is
# satisfied by conditions that route everything to the Fail state.
#
# `input`: the literal payload the graded state is called with.
# `input_from`: run that source state first and use what it produced --
# required wherever the graded value may travel in an assigned variable
# instead of in the state input.
# `expect_output`: deep-compare the parsed TestState `output` to this value.
# `expect_next_state_type`: instead compare the ASL `Type` of the state
# TestState named as `nextState` -- the branch taken, not the branch's name.
CASES: tuple[dict, ...] = (
    {
        "name": "compute-totals-two-orders",
        "state": "ComputeTotals",
        "input": {
            "orders": [
                {"id": "o1", "qty": 2, "price": 10},
                {"id": "o2", "qty": 1, "price": 5},
            ]
        },
        "expect_output": {
            "orders": [
                {"id": "o1", "qty": 2, "price": 10, "total": 20},
                {"id": "o2", "qty": 1, "price": 5, "total": 5},
            ],
            "grandTotal": 25,
        },
    },
    {
        "name": "compute-totals-second-batch",
        "state": "ComputeTotals",
        "input": {
            "orders": [
                {"id": "o3", "qty": 3, "price": 7},
                {"id": "o4", "qty": 4, "price": 2},
            ]
        },
        "expect_output": {
            "orders": [
                {"id": "o3", "qty": 3, "price": 7, "total": 21},
                {"id": "o4", "qty": 4, "price": 2, "total": 8},
            ],
            "grandTotal": 29,
        },
    },
    {
        "name": "check-budget-over-threshold",
        "state": "CheckBudget",
        "input_from": {
            "state": "ComputeTotals",
            "input": {"orders": [{"id": "o5", "qty": 50, "price": 50}]},
        },
        "expect_next_state_type": "Fail",
    },
    {
        # 1000 is the cap itself: "exceeds 1000" is false here, so a `>=`
        # condition fails this case and only this case.
        "name": "check-budget-at-threshold",
        "state": "CheckBudget",
        "input_from": {
            "state": "ComputeTotals",
            "input": {"orders": [{"id": "o6", "qty": 20, "price": 50}]},
        },
        "expect_next_state_type": "Succeed",
    },
    {
        "name": "check-budget-under-threshold",
        "state": "CheckBudget",
        "input_from": {
            "state": "ComputeTotals",
            "input": {"orders": [{"id": "o7", "qty": 10, "price": 50}]},
        },
        "expect_next_state_type": "Succeed",
    },
)

# A Choice may route through intermediate states before reaching the Fail or
# Succeed the prompt requires; the walk is bounded so a definition whose
# `Next` chain cycles cannot hold the verifier open.
MAX_NEXT_HOPS = 5

# One TestState call is a single synchronous request; the deadline exists so a
# hung CLI cannot hold the verifier open, not to allow convergence. It has to
# cover every case's own call plus every chained case's source call at
# CALL_TIMEOUT_S each, and must stay inside the 900s verifier timeout a
# live-check spec gets (gen.py's [verifier] timeout_sec).
CALL_TIMEOUT_S = 60
TOTAL_DEADLINE_S = 480


class NotVerifiable(RuntimeError):
    """The check could not be run -- NEVER a verdict about the solution.

    `kind` is the machine-readable category an operator triages on:
    "no-artifact", "no-state-machine", "undecodable-definition",
    "plan-unknown-definition", "aws-cli-unavailable", "access-denied",
    "transient-exhausted", "api-error".
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class DefinitionRejected(RuntimeError):
    """Step Functions refused the AGENT'S OWN definition -- a verdict about
    the solution, so it becomes a `matched: False` case detail (fail_stale)
    and never a not_verifiable row.

    A malformed ASL, an unparseable `{% ... %}` body, a missing graded state,
    or a Task state whose evaluation would demand a roleArn all arrive as CLI
    errors that look like API failures. Filing them as infrastructure voids
    would send the row back for a re-run instead of counting it as the agent
    failure it is.
    """


# ---------------------------------------------------------------------------
# Artifact discovery and definition extraction (pure)
# ---------------------------------------------------------------------------


def detect_artifact(
    candidates: tuple[tuple[str, str], ...] = ARTIFACT_CANDIDATES,
) -> tuple[Path, str]:
    """The one synthesized artifact this container holds, and its family.

    Non-empty is part of the test: static_tiers.sh writes reward 0.0 and stops
    on an empty artifact, so an empty file here means the toolchain failed,
    not that this arm is the other one. Two artifacts means the workspace is
    not one arm's -- refuse rather than guess which to grade."""
    found = [
        (Path(p), family)
        for p, family in candidates
        if Path(p).is_file() and Path(p).stat().st_size > 0
    ]
    if not found:
        raise NotVerifiable(
            "no-artifact",
            "no synthesized artifact on disk at any of "
            + ", ".join(p for p, _ in candidates),
        )
    if len(found) > 1:
        raise NotVerifiable(
            "no-artifact",
            "more than one arm's artifact is present ("
            + ", ".join(str(p) for p, _ in found)
            + ") -- this workspace is not a single arm's, so which one to "
            "grade cannot be inferred",
        )
    return found[0]


def _state_machine_definition_strings(document: dict, family: str) -> list[Any]:
    if family == "cfn":
        resources = document.get("Resources") or {}
        if not isinstance(resources, dict):
            return []
        return [
            (r.get("Properties") or {}).get("DefinitionString")
            for r in resources.values()
            if isinstance(r, dict)
            and r.get("Type") == "AWS::StepFunctions::StateMachine"
        ]
    resources = (
        ((document.get("planned_values") or {}).get("root_module") or {}).get(
            "resources"
        )
        or []
    )
    if not isinstance(resources, list):
        return []
    return [
        (r.get("values") or {}).get("definition")
        for r in resources
        if isinstance(r, dict) and r.get("type") == "aws_sfn_state_machine"
    ]


def _flatten_join(value: Any) -> Any:
    """A CFN `Fn::Join` whose parts are all literal strings IS a literal
    string, and is joined here rather than refused.

    Synthesis renders `DefinitionString` as a join as soon as any part of the
    ASL carries a token, which a correct solution is free to do (a Task state,
    an `Fn::Sub` in a Cause). Refusing every join would score those
    not_verifiable, i.e. 0.0 under gating. A join carrying a nested intrinsic
    is genuinely unresolvable here and is left as-is for the caller to
    refuse."""
    if not isinstance(value, dict) or set(value) != {"Fn::Join"}:
        return value
    join = value["Fn::Join"]
    if not (isinstance(join, list) and len(join) == 2):
        return value
    separator, parts = join
    if not isinstance(separator, str) or not isinstance(parts, list):
        return value
    if not all(isinstance(part, str) for part in parts):
        return value
    return separator.join(parts)


def extract_definition(document: dict, family: str) -> dict:
    """The decoded ASL state-machine definition, from either artifact shape.

    Both arms hold it as a JSON-ENCODED STRING attribute (CFN
    `Properties.DefinitionString`, Terraform `values.definition`), which is
    the same `|fromjson` step this scenario's tier-0 asserts take. Anything
    else -- zero state machines, several, an `Fn::Join` intrinsic instead of a
    literal string, unparseable JSON -- is unverifiable rather than wrong: the
    tier-0 asserts already grade those shapes, and this oracle has no standing
    to add a second verdict about them."""
    raw = [d for d in _state_machine_definition_strings(document, family)]
    if not raw:
        raise NotVerifiable(
            "no-state-machine",
            f"no state machine found in the {family} artifact",
        )
    if len(raw) > 1:
        raise NotVerifiable(
            "no-state-machine",
            f"{len(raw)} state machines found in the {family} artifact -- this "
            "scenario grades exactly one",
        )
    definition = _flatten_join(raw[0])
    if definition is None:
        # `terraform show -json` omits `values.definition` entirely when the
        # encoded ASL embeds another resource's computed attribute, so the
        # whole string is `(known after apply)` (specs/SCHEMA.md §4.2.1).
        # Naming that condition keeps it out of the generic decode-failure
        # bucket, which would read as a malformed artifact.
        raise NotVerifiable(
            "plan-unknown-definition",
            "the state machine's definition is `(known after apply)` in this "
            "plan -- an ASL that embeds a resource's computed attribute is "
            "plan-time-unknown as a whole, so there is nothing to submit to "
            "TestState",
        )
    if not isinstance(definition, str):
        raise NotVerifiable(
            "undecodable-definition",
            "the state machine's definition is not a literal JSON string "
            f"(got {type(definition).__name__}) -- nothing to submit to "
            "TestState",
        )
    try:
        decoded = json.loads(definition)
    except json.JSONDecodeError as exc:
        raise NotVerifiable(
            "undecodable-definition",
            f"the state machine's definition is not decodable JSON: {exc}",
        ) from exc
    if not isinstance(decoded, dict):
        raise NotVerifiable(
            "undecodable-definition",
            "the decoded state machine definition is not a JSON object",
        )
    return decoded


# ---------------------------------------------------------------------------
# Comparison (pure)
# ---------------------------------------------------------------------------


def deep_equal(observed: Any, expected: Any) -> bool:
    """Structural equality, with numbers compared AS NUMBERS.

    `20` and `20.0` are the same total; the service is free to return either.
    Booleans are compared type-strictly because Python's own `True == 1`
    would otherwise let a Choice condition's `true` satisfy a numeric
    expectation."""
    if isinstance(observed, bool) or isinstance(expected, bool):
        return observed is expected
    if isinstance(observed, (int, float)) and isinstance(expected, (int, float)):
        return float(observed) == float(expected)
    if isinstance(observed, dict) and isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            deep_equal(observed[k], expected[k]) for k in expected
        )
    if isinstance(observed, list) and isinstance(expected, list):
        return len(observed) == len(expected) and all(
            deep_equal(o, e) for o, e in zip(observed, expected)
        )
    return observed == expected


# ---------------------------------------------------------------------------
# TestState
# ---------------------------------------------------------------------------


# Stderr markers that name a defect in the SUBMITTED DEFINITION rather than a
# fault in the infrastructure. Checked after the credential marker, so an
# AccessDeniedException naming a state still triages as access. Throttling and
# timeouts never reach here: tests/_live_lib.py retries them and raises
# TransientExhausted only once its budget is spent.
_DEFINITION_FAULT_MARKERS: tuple[str, ...] = (
    "validationexception",
    "invaliddefinition",
    "invalidname",
    "invalidarn",
    "does not exist",
)


def _classify_cli_failure(stderr: str) -> tuple[str, str]:
    text = stderr.strip()
    lowered = text.lower()
    if "accessdenied" in lowered or "not authorized" in lowered:
        return "access-denied", text
    if any(marker in lowered for marker in _DEFINITION_FAULT_MARKERS):
        return "invalid-definition", text
    return "api-error", text


def call_test_state(
    definition: dict,
    state_name: str,
    payload: dict,
    *,
    variables: str | None = None,
    inspection_level: str = "INFO",
) -> dict:
    """One `stepfunctions test-state` call: the whole machine plus the state
    to evaluate, no roleArn (Pass and Choice need none, and passing one would
    additionally require iam:PassRole).

    `inspection_level` is INFO or DEBUG only. TRACE is HTTP-Task-only and the
    service errors on any other state type; DEBUG is the deepest level a Pass
    or Choice accepts and is the one that returns `inspectionData.variables`,
    the assigned-variable half of a chained case's input.

    Retry is delegated whole to tests/_live_lib.py, which retries only the
    transient class -- a TestState answer does not change over time, so
    re-asking after any resolved refusal would just be a slower same answer. A
    failure that names the definition raises DefinitionRejected instead of
    NotVerifiable: it is the solution that was refused, not the service that
    was unreachable."""
    args = [
        "stepfunctions",
        "test-state",
        "--definition",
        json.dumps(definition),
        "--state-name",
        state_name,
        "--input",
        json.dumps(payload),
        "--inspection-level",
        inspection_level,
    ] + (["--variables", variables] if variables else [])
    try:
        rc, stdout, stderr = run_aws(args, timeout=CALL_TIMEOUT_S)
    except TransientExhausted as exc:
        raise NotVerifiable(exc.kind, str(exc)) from exc
    if rc == 0:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise NotVerifiable(
                "api-error",
                f"unparseable TestState response for {state_name!r}: {exc}",
            ) from exc
    if rc == 127:
        raise NotVerifiable("aws-cli-unavailable", stderr.strip())
    kind, detail = _classify_cli_failure(stderr)
    if kind == "invalid-definition":
        raise DefinitionRejected(
            f"Step Functions refused the submitted definition while "
            f"evaluating state {state_name!r}: {detail}"
        )
    raise NotVerifiable(
        kind, f"aws stepfunctions test-state --state-name {state_name}: {detail}"
    )


def all_states(definition: dict) -> dict:
    """Every state in the definition keyed by name, including those nested in
    Parallel branches and Map iterators.

    A Choice's `nextState` is resolved against this map, not against the
    top-level `States` alone: a solution is free to nest the graded Choice,
    and a top-level-only lookup would report a correct one as routing
    nowhere. The outermost binding of a repeated name wins."""
    collected: dict = {}

    def walk(states: Any) -> None:
        if not isinstance(states, dict):
            return
        nested = []
        for name, state in states.items():
            if not isinstance(state, dict):
                continue
            collected.setdefault(name, state)
            for branch in state.get("Branches") or []:
                if isinstance(branch, dict):
                    nested.append(branch.get("States"))
            for key in ("ItemProcessor", "Iterator"):
                block = state.get(key)
                if isinstance(block, dict):
                    nested.append(block.get("States"))
        for block in nested:
            walk(block)

    walk(definition.get("States"))
    return collected


def reached_state_type(
    definition: dict, next_state: Any, expected: str
) -> tuple[Any, Any]:
    """The `Type` the branch TestState took ends at, and the state carrying
    it.

    The prompt requires the input to REACH a state of the expected Type, not
    to reach it in one hop, so an intermediate Pass on the way to the Fail
    state is correct and must match. The walk stops at the expected Type and
    is capped at MAX_NEXT_HOPS, so a cyclic `Next` chain terminates."""
    states = all_states(definition)
    name = next_state
    observed_type: Any = None
    observed_state: Any = None
    for _ in range(MAX_NEXT_HOPS):
        if not isinstance(name, str):
            break
        state = states.get(name)
        if not isinstance(state, dict):
            break
        observed_type, observed_state = state.get("Type"), name
        if observed_type == expected:
            break
        name = state.get("Next")
    return observed_type, observed_state


def resolve_input(
    case: dict, definition: dict, call: Callable[..., dict]
) -> tuple[dict, str | None]:
    """The payload the graded state is called with, plus the workflow
    variables in scope for that call.

    A case declaring `input_from` runs its source state for real first and
    hands on what that state produced -- its output as the graded state's
    input, its assigned variables as `--variables`. A JSONata-mode solution
    may legitimately carry a value in either, and a literal input would score
    the assigned-variable form 0.0 while the flipped-operator fixture scores
    the same, making the two indistinguishable in the record.

    A source state that does not succeed raises DefinitionRejected: the graded
    state has no input, and that is the solution's own doing."""
    source = case.get("input_from")
    if source is None:
        return case["input"], None
    response = call(
        definition, source["state"], source["input"], inspection_level="DEBUG"
    )
    status = response.get("status")
    if status != "SUCCEEDED":
        raise DefinitionRejected(
            f"state {source['state']!r} reported status {status!r} while "
            f"producing the input for case {case['name']!r}: "
            f"{response.get('error')} {response.get('cause')}".strip()
        )
    raw_output = response.get("output")
    try:
        payload = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
    except json.JSONDecodeError as exc:
        raise DefinitionRejected(
            f"state {source['state']!r} produced output that is not decodable "
            f"JSON, so state {case['state']!r} has no input to grade: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise DefinitionRejected(
            f"state {source['state']!r} produced {type(payload).__name__}, not "
            f"a JSON object, so state {case['state']!r} has no input to grade"
        )
    variables = (response.get("inspectionData") or {}).get("variables")
    return payload, variables if isinstance(variables, str) else None


def evaluate_case(case: dict, definition: dict, call: Callable[..., dict]) -> dict:
    """One case's detail record. `matched` False is a verdict about the
    solution; a NotVerifiable raised from `call` is not, and propagates."""
    detail: dict = {"case": case["name"], "state": case["state"]}
    try:
        payload, variables = resolve_input(case, definition, call)
        response = call(definition, case["state"], payload, variables=variables)
    except DefinitionRejected as exc:
        detail["matched"] = False
        detail["reason"] = str(exc)
        return detail
    detail["input"] = payload
    detail["status"] = response.get("status")
    if response.get("status") != "SUCCEEDED":
        detail["matched"] = False
        detail["reason"] = (
            f"TestState reported status {response.get('status')!r} for state "
            f"{case['state']!r}: {response.get('error')} {response.get('cause')}".strip()
        )
        return detail

    if "expect_next_state_type" in case:
        expected = case["expect_next_state_type"]
        next_state = response.get("nextState")
        observed_type, observed_state = reached_state_type(
            definition, next_state, expected
        )
        detail["next_state"] = next_state
        detail["reached_state"] = observed_state
        detail["next_state_type"] = observed_type
        detail["expected_next_state_type"] = expected
        detail["matched"] = observed_type == expected
        if not detail["matched"]:
            detail["reason"] = (
                f"state {case['state']!r} routed to {next_state!r}, whose "
                f"chain ends at {observed_state!r} (Type {observed_type!r}); "
                f"this input must reach a state of Type {expected!r}"
            )
        return detail

    raw_output = response.get("output")
    try:
        observed = json.loads(raw_output) if isinstance(raw_output, str) else raw_output
    except json.JSONDecodeError as exc:
        detail["matched"] = False
        detail["reason"] = f"TestState output was not decodable JSON: {exc}"
        return detail
    detail["observed_output"] = observed
    detail["expected_output"] = case["expect_output"]
    detail["matched"] = deep_equal(observed, case["expect_output"])
    if not detail["matched"]:
        detail["reason"] = (
            f"state {case['state']!r} computed a different value than this "
            "input requires"
        )
    return detail


def outcome_from(details: list[dict]) -> str:
    """"pass" iff every declared case ran and matched. An empty list is NOT a
    pass: no case evaluated means nothing was proven."""
    if not details:
        return "not_verifiable"
    return "pass" if all(d.get("matched") for d in details) else "fail_stale"


def run(
    cases: tuple[dict, ...],
    definition: dict,
    call: Callable[..., dict],
    deadline: float | None = None,
) -> dict:
    details: list[dict] = []
    for case in cases:
        if deadline is not None and time.monotonic() >= deadline:
            raise NotVerifiable(
                "api-error",
                f"ran out of time before case {case['name']!r} "
                f"({TOTAL_DEADLINE_S}s budget)",
            )
        details.append(evaluate_case(case, definition, call))
    return {
        "outcome": outcome_from(details),
        "cases": details,
        "failures": [d.get("reason", d["case"]) for d in details if not d.get("matched")],
    }


def observe() -> dict:
    try:
        artifact, family = detect_artifact()
        document = json.loads(artifact.read_text())
        definition = extract_definition(document, family)
        result = run(
            CASES,
            definition,
            call_test_state,
            deadline=time.monotonic() + TOTAL_DEADLINE_S,
        )
        result["artifact"] = str(artifact)
        result["artifact_family"] = family
        return result
    except NotVerifiable as exc:
        return {
            "outcome": "not_verifiable",
            "not_verifiable_kind": exc.kind,
            "reason": str(exc),
            "cases": [],
            "failures": [],
        }
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "outcome": "not_verifiable",
            "not_verifiable_kind": "no-artifact",
            "reason": f"could not read the synthesized artifact: {exc}",
            "cases": [],
            "failures": [],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="sfn-jsonata live check")
    parser.add_argument(
        "--expect",
        choices=["ok", "stale"],
        default=None,
        help="fixture-invoked shape: assert the observed outcome. Exits "
        "non-zero when what Step Functions computed contradicts the assertion.",
    )
    args = parser.parse_args()

    result = observe()
    result["scenario"] = SCENARIO
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.expect is None:
        # Verifier-invoked: `.outcome` is the verdict, the exit code is not.
        return 0
    if result["outcome"] == "not_verifiable":
        print(
            "live_check: could not evaluate the state machine -- refusing to "
            "confirm or deny the fixture's assertion",
            file=sys.stderr,
        )
        return 2
    expected = "pass" if args.expect == "ok" else "fail_stale"
    if result["outcome"] != expected:
        print(
            f"live_check: expected outcome {expected!r}, observed "
            f"{result['outcome']!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
