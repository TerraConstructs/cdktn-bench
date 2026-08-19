"""Gates 2+3 over a MULTI-STEP trial dir (task #14).

A multi-step trial (``cdktn_bench.trial.CdktnMultiStepTrial``, driving Harbor's
``harbor/trial/multi_step.py``) **relocates** ``agent/``, ``verifier/`` and
``artifacts/`` into ``steps/<name>/`` after every step
(``MultiStepTrial._archive_step_outputs``). Before this suite, every gate
reader that hardcoded ``<trial>/agent/trajectory.json`` or
``<trial>/verifier/...`` silently reported "absent" for a trial that had in
fact produced complete evidence — which classifies a real, fully-evidenced
trial as ``invalid-infra`` ("could not audit trial") and drops it from the
scored denominator.

The fixtures here are built by hand from Harbor's own
``harbor/models/trial/result.py`` schema (``TrialResult.step_results:
list[StepResult]``), and ``test_synthetic_step_results_match_harbors_schema``
validates them against that model so the fixture cannot drift away from the
thing it claims to imitate. Full Docker trial runs are out of scope for this
suite.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gates.audit import audit_trial, resolve_step_names, resolve_trajectory_paths
from gates.emit_result import (
    VALID,
    build_result_record,
    extract_n_llm_calls,
    extract_n_llm_calls_per_step,
    read_step_summary,
    read_tier1_not_verifiable,
    read_tier_evidence,
    to_result_row,
)
from gates.tests.conftest import trial_dir
from metrics.validate_result import validate_result

FAKE_DIGEST_IMAGE_REF = "cdktn-bench/awscdk@sha256:" + "0" * 64

STEP_NAMES = ("01-initial", "02-change-request")


# --- fixture builders -------------------------------------------------------


def _multistep_task_dir(root: Path) -> Path:
    """A multi-step TASK dir: no root instruction.md, one per step.

    Mirrors the shape ``docs/design/multistep-trial-investigation.md`` §5
    specifies and ``cdktn_bench/tests/fixtures/multistep-task`` implements.
    Built here rather than imported so gates/ keeps no dependency on the
    cdktn_bench package.
    """
    task_dir = root / "task"
    for name in STEP_NAMES:
        step = task_dir / "steps" / name
        (step / "tests").mkdir(parents=True)
        (step / "instruction.md").write_text(f"do {name}\n")
        (step / "tests" / "test.sh").write_text("#!/usr/bin/env bash\ntrue\n")
    (task_dir / "task.toml").write_text(
        "[[steps]]\nname = '01-initial'\nmin_reward = 1.0\n\n"
        "[[steps]]\nname = '02-change-request'\n"
    )
    return task_dir


def _step_result(
    name: str,
    *,
    reward: float | None,
    n_input: int,
    n_output: int,
    n_cache: int,
    cost: float,
    exception_type: str | None = None,
) -> dict:
    """One ``harbor.models.trial.result.StepResult``, as JSON.

    ``exception_type`` models a step that STARTED and died — Harbor appends the
    StepResult before running the step, so such a step is present in
    ``step_results`` with no ``verifier_result``.
    """
    return {
        "step_name": name,
        "agent_result": None
        if exception_type is not None
        else {
            "n_input_tokens": n_input,
            "n_output_tokens": n_output,
            "n_cache_tokens": n_cache,
            "cost_usd": cost,
        },
        "verifier_result": None if reward is None else {"rewards": {"reward": reward}},
        "exception_info": None
        if exception_type is None
        else {
            "exception_type": exception_type,
            "exception_message": f"{name}: pre_invoke.sh exited 1",
            "exception_traceback": "Traceback (most recent call last):\n  ...\n",
            "occurred_at": "2026-08-20T00:00:00Z",
        },
    }


def _multistep_trial_dir(
    root: Path,
    *,
    step_names: tuple[str, ...] = STEP_NAMES,
    rewards: tuple[float | None, ...] = (1.0, 1.0),
    final_reward: float | None = 1.0,
    failed_steps: tuple[str, ...] = (),
) -> Path:
    """A multi-step TRIAL dir with per-step agent/ and verifier/ subtrees.

    The per-step trajectories are copies of the checked-in ``awscdk/genuine``
    fixture, so the audit gate sees the same real toolchain evidence it sees
    for the single-step fixtures — the only thing under test here is WHERE the
    evidence lives.
    """
    trial = root / "trial"
    trial.mkdir()
    source_agent = trial_dir("awscdk", "genuine") / "agent"

    for name in step_names:
        step_dir = trial / "steps" / name
        step_dir.mkdir(parents=True)
        shutil.copytree(source_agent, step_dir / "agent")
        (step_dir / "verifier").mkdir()

    (trial / "result.json").write_text(
        json.dumps(
            {
                # MultiStepTrial NEVER sets the top-level agent_result
                # (harbor/trial/multi_step.py::_run) — that is the whole reason
                # _aggregate_step_tokens exists.
                "verifier_result": None
                if final_reward is None
                else {"rewards": {"reward": final_reward}},
                "step_results": [
                    _step_result(
                        name,
                        reward=rewards[i] if i < len(rewards) else None,
                        n_input=100 * (i + 1),
                        n_output=20 * (i + 1),
                        n_cache=5 * (i + 1),
                        cost=0.01 * (i + 1),
                        exception_type="ScriptExecutionError"
                        if name in failed_steps
                        else None,
                    )
                    for i, name in enumerate(step_names)
                ],
            }
        )
    )
    return trial


@pytest.fixture
def multistep(tmp_path: Path) -> tuple[Path, Path]:
    return _multistep_trial_dir(tmp_path), _multistep_task_dir(tmp_path)


# --- the fixture is a real Harbor shape, not a convenient invention ---------


def test_synthetic_step_results_match_harbors_schema(multistep) -> None:
    trial, _ = multistep
    from harbor.models.trial.result import StepResult

    data = json.loads((trial / "result.json").read_text())
    parsed = [StepResult.model_validate(sr) for sr in data["step_results"]]
    assert [sr.step_name for sr in parsed] == list(STEP_NAMES)
    assert parsed[0].agent_result is not None
    assert parsed[0].verifier_result is not None


def test_synthetic_FAILED_step_matches_harbors_schema(tmp_path: Path) -> None:
    """The failure fixture is a real Harbor shape too, not a convenient one.

    Guards the regression tests below: if Harbor's ``ExceptionInfo`` gains or
    renames a required field, this fails loudly rather than letting those tests
    keep passing against a shape Harbor would never write.
    """
    from harbor.models.trial.result import StepResult

    trial = _multistep_trial_dir(
        tmp_path,
        rewards=(1.0, None),
        final_reward=None,
        failed_steps=("02-change-request",),
    )
    data = json.loads((trial / "result.json").read_text())
    parsed = [StepResult.model_validate(sr) for sr in data["step_results"]]

    assert parsed[1].exception_info is not None
    assert parsed[1].exception_info.exception_type == "ScriptExecutionError"
    # The defining property: it started (it has a slot) but never verified.
    assert parsed[1].verifier_result is None


# --- step discovery ---------------------------------------------------------


def test_step_names_come_from_result_json_execution_order(multistep) -> None:
    trial, _ = multistep
    assert resolve_step_names(trial) == list(STEP_NAMES)


def test_step_names_fall_back_to_sorted_dirs_without_result_json(multistep) -> None:
    trial, _ = multistep
    (trial / "result.json").unlink()
    assert resolve_step_names(trial) == sorted(STEP_NAMES)


def test_single_step_trial_dir_has_no_steps(multistep) -> None:
    assert resolve_step_names(trial_dir("awscdk", "genuine")) == []


# --- gate 2: audit ----------------------------------------------------------


def test_audit_finds_the_relocated_trajectories(multistep) -> None:
    trial, _ = multistep
    paths = resolve_trajectory_paths(trial)
    assert [p.parent.parent.name for p in paths] == list(STEP_NAMES)

    report = audit_trial(trial, "awscdk")
    assert report["valid"] is True
    assert report["trajectory_path"] == str(paths[0])
    assert report["trajectory_paths"] == [str(p) for p in paths]


def test_audit_is_a_trial_level_question_so_steps_are_concatenated(multistep) -> None:
    """An agent that ran ``cdk synth`` in step 1 and only edited files in step 2
    has not bypassed the toolchain. Bash calls from every step count."""
    trial, _ = multistep
    single = audit_trial(trial_dir("awscdk", "genuine"), "awscdk")
    multi = audit_trial(trial, "awscdk")
    assert multi["bash_call_count"] == 2 * single["bash_call_count"]
    assert len(multi["evidence"]) == 2 * len(single["evidence"])


def test_single_step_audit_record_is_unchanged(multistep) -> None:
    """No ``trajectory_paths`` key for a single-step trial: byte-identical."""
    report = audit_trial(trial_dir("awscdk", "genuine"), "awscdk")
    assert "trajectory_paths" not in report


# --- gate 3: score fields ---------------------------------------------------


def test_record_is_valid_and_aggregates_across_steps(multistep) -> None:
    trial, task = multistep
    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF, {})

    assert record["validity_class"] == VALID
    assert record["reward"] == 1.0
    # 100+200 / 20+40 / 5+10 / .01+.02 — TrialResult.compute_token_cost_totals'
    # own second branch.
    assert record["n_input_tokens"] == 300
    assert record["n_output_tokens"] == 60
    assert record["n_cache_tokens"] == 15
    assert record["cost_usd"] == pytest.approx(0.03)


def test_n_llm_calls_is_the_cumulative_sum_across_steps(multistep) -> None:
    trial, task = multistep
    for name in STEP_NAMES:
        path = trial / "steps" / name / "agent" / "trajectory.json"
        data = json.loads(path.read_text())
        data["steps"] = list(data.get("steps", [])) + [
            {"source": "agent", "llm_call_count": 3}
        ]
        path.write_text(json.dumps(data))

    assert extract_n_llm_calls_per_step(trial) == {
        "01-initial": 3,
        "02-change-request": 3,
    }
    assert extract_n_llm_calls(trial) == 6

    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF, {})
    assert record["n_llm_calls"] == 6


def test_one_unreadable_step_trajectory_makes_the_sum_unknown(multistep) -> None:
    """`None`-not-`0` extends across steps: a partial sum silently understates
    iterations-to-green, which is exactly what the None contract prevents."""
    trial, _ = multistep
    (trial / "steps" / "02-change-request" / "agent" / "trajectory.json").write_text(
        "{not json"
    )
    assert extract_n_llm_calls_per_step(trial)["02-change-request"] is None
    assert extract_n_llm_calls(trial) is None


# --- gate 3: relocated verifier evidence ------------------------------------


def test_tier1_marker_is_read_from_the_scoring_step(multistep) -> None:
    """Reverse order, first hit wins: under the cdktn default
    ``multi_step_reward_strategy = "final"`` the published reward comes from
    the LAST step, so the flag must describe that step's verification."""
    trial, _ = multistep
    (trial / "steps" / "01-initial" / "verifier" / "tier1-not-verifiable").write_text(
        "step 1 marker"
    )
    (
        trial / "steps" / "02-change-request" / "verifier" / "tier1-not-verifiable"
    ).write_text("step 2 marker")

    present, detail = read_tier1_not_verifiable(trial)
    assert present is True
    assert detail == "step 2 marker"


def test_tier1_marker_absent_when_no_step_wrote_one(multistep) -> None:
    trial, _ = multistep
    assert read_tier1_not_verifiable(trial) == (False, None)


def test_tier_evidence_is_read_from_the_scoring_step(multistep) -> None:
    trial, _ = multistep
    (trial / "steps" / "01-initial" / "verifier" / "test-stdout.txt").write_text(
        "  PASS [only-in-step-1]\n== summary: tier0_pass=1 tier1_status=pass ==\n"
    )
    (
        trial / "steps" / "02-change-request" / "verifier" / "test-stdout.txt"
    ).write_text(
        "  FAIL [only-in-step-2]: nope\n== summary: tier0_pass=0 tier1_status=fail ==\n"
    )

    evidence = read_tier_evidence(trial)
    assert evidence == {"tier0": {"only-in-step-2": "FAIL"}, "tier1_status": "fail"}


def test_tier_evidence_none_when_no_step_verified(multistep) -> None:
    trial, _ = multistep
    assert read_tier_evidence(trial) is None


# --- gate 3: the aborted-trial signal (memo §6.7) ---------------------------


def test_step_summary_reports_completed_vs_declared(multistep) -> None:
    trial, task = multistep
    summary = read_step_summary(trial, task)
    assert summary["names"] == list(STEP_NAMES)
    assert summary["n_started"] == 2
    assert summary["n_declared"] == 2
    assert summary["n_failed"] == 0
    assert summary["aborted_early"] is False
    assert [row["step_name"] for row in summary["per_step"]] == list(STEP_NAMES)
    assert summary["per_step"][1]["n_output_tokens"] == 40


def test_a_min_reward_abort_is_visible_as_aborted_early(tmp_path: Path) -> None:
    """The failure mode this field exists for.

    ``MultiStepTrial._should_stop_after_step`` aborts by RETURNING: the failure
    is recorded on the StepResult, never on ``TrialResult.exception_info``. So
    a trial that ran 1 of 2 steps looks, to every top-level reader (including
    this gate's validity classification), exactly like a clean trial.
    """
    trial = _multistep_trial_dir(
        tmp_path, step_names=("01-initial",), rewards=(0.0,), final_reward=0.0
    )
    task = _multistep_task_dir(tmp_path)

    summary = read_step_summary(trial, task)
    assert summary["n_started"] == 1
    assert summary["n_declared"] == 2
    assert summary["aborted_early"] is True

    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF, {})
    # Still "valid" — the trial ran, the toolchain was invoked, the reward is
    # a real 0.0. `steps.aborted_early` is what says it stopped half way.
    assert record["validity_class"] == VALID
    assert record["reward"] == 0.0
    assert record["steps"]["aborted_early"] is True


def test_a_failed_LAST_step_is_still_aborted_early(tmp_path: Path) -> None:
    """The counting hole that a purely arithmetic ``aborted_early`` had.

    Harbor appends the StepResult BEFORE running the step, so a step that dies
    in ``_prepare_step`` still occupies a slot: for a failure in the LAST
    declared step, ``n_started == n_declared``. That is precisely where the
    design puts the harness action (step 2's ``pre_invoke`` deploys step 1's
    work and injects drift), so the canonical harness-failure case must not be
    the one case the signal misses.
    """
    trial = _multistep_trial_dir(
        tmp_path,
        rewards=(1.0, None),
        final_reward=None,
        failed_steps=("02-change-request",),
    )
    task = _multistep_task_dir(tmp_path)

    summary = read_step_summary(trial, task)
    # Every step slot is occupied — arithmetic alone cannot see the failure.
    assert summary["n_started"] == 2
    assert summary["n_declared"] == 2
    assert summary["n_failed"] == 1
    assert summary["aborted_early"] is True
    assert summary["per_step"][1]["exception_type"] == "ScriptExecutionError"

    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF, {})
    assert record["steps"]["aborted_early"] is True
    # The reward is genuinely ABSENT, not 0.0: `final` selects the last step's
    # verifier_result and that step never verified. Only to_result_row coerces
    # it to 0.0 for the published row.
    assert record["reward"] is None


def test_an_exception_alongside_a_score_is_not_an_abort(tmp_path: Path) -> None:
    """The other half of Harbor's predicate, so ``n_failed`` cannot over-fire.

    ``_should_stop_after_step`` stops only on ``exception_info and not
    verifier_result``. A step that raised but still got scored did not abort
    the trial, and must not be counted as a failure.
    """
    trial = _multistep_trial_dir(tmp_path)
    task = _multistep_task_dir(tmp_path)
    data = json.loads((trial / "result.json").read_text())
    data["step_results"][0]["exception_info"] = {
        "exception_type": "FlakyWarning",
        "exception_message": "recovered",
        "exception_traceback": "...",
        "occurred_at": "2026-08-20T00:00:00Z",
    }
    (trial / "result.json").write_text(json.dumps(data))

    summary = read_step_summary(trial, task)
    assert summary["n_failed"] == 0
    assert summary["aborted_early"] is False


def test_single_step_record_gains_no_steps_key(task_dir) -> None:
    """The byte-identical guarantee for every existing single-step trial."""
    record = build_result_record(
        trial_dir("awscdk", "genuine"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
    )
    assert "steps" not in record
    assert read_step_summary(trial_dir("awscdk", "genuine"), task_dir) is None


# --- gate 3: the published row ---------------------------------------------


def test_multistep_record_emits_a_schema_valid_row(multistep) -> None:
    """A multi-step task has NO root instruction.md, so before task #14 the
    equipping hash raised FileNotFoundError and ``to_result_row`` refused to
    emit any row at all — a multi-step trial was unpublishable."""
    trial, task = multistep
    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF, {})
    assert record["equipping_hash"] is not None
    assert "equipping_hash_error" not in record

    row = to_result_row(
        record,
        model="claude-sonnet-5",
        harness="empty",
        oracle_version="oracles@fixture",
    )
    assert validate_result(row) == []
    assert row["tokens_output"] == 60
    # The row's shape is pre-registered (additionalProperties: false); the
    # multi-step diagnostics live on the RECORD, not the row.
    assert "steps" not in row


def test_equipping_hash_tracks_every_step_instruction(tmp_path: Path) -> None:
    from gates.equipping import compute_equipping_hash

    task = _multistep_task_dir(tmp_path)
    before = compute_equipping_hash(task, FAKE_DIGEST_IMAGE_REF, {})
    (task / "steps" / "02-change-request" / "instruction.md").write_text("do it differently\n")
    after = compute_equipping_hash(task, FAKE_DIGEST_IMAGE_REF, {})
    assert before != after


def test_single_step_equipping_hash_is_unchanged_by_the_multistep_branch(
    task_dir,
) -> None:
    """No HASH_SCHEME_VERSION bump: a single-step task still hashes exactly the
    manifest it always did, so no published result needs re-hashing."""
    import hashlib

    from gates.equipping import HASH_SCHEME_VERSION, compute_equipping_hash

    expected_manifest = {
        "hash_scheme_version": HASH_SCHEME_VERSION,
        "equipping_files": [],
        "image_ref": FAKE_DIGEST_IMAGE_REF,
        "image_digest": FAKE_DIGEST_IMAGE_REF,
        "extra_cfg": {},
        "instruction_md_sha256": hashlib.sha256(
            (Path(task_dir) / "instruction.md").read_bytes()
        ).hexdigest(),
    }
    canonical = json.dumps(expected_manifest, sort_keys=True, separators=(",", ":"))
    assert compute_equipping_hash(task_dir, FAKE_DIGEST_IMAGE_REF, {}) == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
