"""Dispatch: a [[steps]] task becomes a multi-step trial, a stepless one does not.

This is the behaviour the whole slice exists to add, and the one thing that
must NOT change for existing tasks. Both directions are asserted over real
``AwsBenchTrialConfig`` objects and real task dirs — no mocks of the factory —
so the test exercises the same construction path a live run does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aws_bench.dataset.task_config import AwsBenchTask
from aws_bench.task.aws_trial import AwsBenchSingleStepTrial, AwsBenchTrial
from harbor.models.task.verifier_mode import VerifierEnvironmentMode
from harbor.trial.multi_step import MultiStepTrial

from cdktn_bench.queue import CdktnTrialQueue
from cdktn_bench.tests.conftest import make_trial_config
from cdktn_bench.trial import (
    CdktnMultiStepTrial,
    CdktnTrial,
    validate_multi_step_layout,
)


def _create(task_dir: Path, trials_dir: Path, name: str):
    """Build a trial the way the queue does. ``asyncio.run`` keeps this suite
    plugin-free (no pytest-asyncio dependency to add to `make check`)."""
    import asyncio

    return asyncio.run(
        CdktnTrial.create(make_trial_config(task_dir, trials_dir, trial_name=name))
    )


def test_steps_task_dispatches_to_cdktn_multi_step_trial(
    multistep_task_dir: Path, tmp_path: Path, no_account_manager: None
) -> None:
    trial = _create(multistep_task_dir, tmp_path, "ms")
    assert type(trial) is CdktnMultiStepTrial
    assert isinstance(trial, MultiStepTrial)
    assert trial.task.has_steps
    assert [s.name for s in trial.task.config.steps] == [
        "01-initial",
        "02-change-request",
    ]


def test_stepless_task_falls_through_to_the_untouched_aws_bench_path(
    singlestep_task_dir: Path, tmp_path: Path, no_account_manager: None
) -> None:
    """Exactly ``AwsBenchSingleStepTrial`` — not a cdktn subclass of it.

    cdktn-bench adds multi-step; it must not quietly re-route the single-step
    path through new code, because every existing generated task and every
    result already published came through the upstream one.
    """
    trial = _create(singlestep_task_dir, tmp_path, "ss")
    assert type(trial) is AwsBenchSingleStepTrial
    assert not trial.task.has_steps


def test_upstream_still_refuses_multi_step(multistep_task_dir: Path, tmp_path: Path) -> None:
    """Proof that nothing in aws-bench was modified to make this slice work.

    If this ever stops raising, upstream has implemented multi-step itself and
    the whole cdktn_bench.trial seam should be re-evaluated (and probably
    deleted) rather than left shadowing an upstream implementation.
    """
    import asyncio

    with pytest.raises(NotImplementedError, match="multi-step AWS tasks are not yet supported"):
        asyncio.run(
            AwsBenchTrial.create(make_trial_config(multistep_task_dir, tmp_path, trial_name="x"))
        )


def test_multi_step_trial_refuses_a_stepless_task(
    singlestep_task_dir: Path, tmp_path: Path, no_account_manager: None
) -> None:
    task = AwsBenchTask(singlestep_task_dir)
    with pytest.raises(ValueError, match=r"requires a task with \[\[steps\]\]"):
        CdktnMultiStepTrial(
            make_trial_config(singlestep_task_dir, tmp_path, trial_name="bad"), _task=task
        )


def test_queue_builds_trials_through_the_cdktn_factory() -> None:
    """The dispatch point (``aws_bench/task/queue.py``'s retry loop)."""
    assert CdktnTrialQueue.trial_factory is CdktnTrial
    # ...and the scenario admission gate is inherited, not reimplemented: it is
    # what guarantees one mutating trial per AWS account at a time, and a
    # multi-step trial holds it across ALL its steps and the post-trial reset.
    assert "_run_trial" not in vars(CdktnTrialQueue)


def test_the_retry_loop_actually_calls_the_factory(
    multistep_task_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Executes the override, rather than only asserting the attribute.

    ``AwsBenchTrialQueue`` reads ``AwsBenchTrial`` as a module global inside its
    own retry loop, and neither it nor Harbor's ``TrialQueue`` exposes a factory
    hook — so ``CdktnTrialQueue`` re-declares the loop with one line changed.
    This proves the changed line is the one that runs.
    """
    import asyncio

    built: list[object] = []

    class _StubTrial:
        paths = None

        async def run(self):
            class _Result:
                exception_info = None

            return _Result()

    class _StubFactory:
        @classmethod
        async def create(cls, trial_config):
            built.append(trial_config)
            return _StubTrial()

    queue = CdktnTrialQueue(n_concurrent=1)
    monkeypatch.setattr(queue, "trial_factory", _StubFactory)
    monkeypatch.setattr(queue, "_setup_hooks", lambda trial: None)

    config = make_trial_config(multistep_task_dir, tmp_path, trial_name="ms")
    result = asyncio.run(queue._execute_trial_with_retries(config))

    assert built == [config]
    assert result.exception_info is None


def test_separate_environment_verifier_is_refused_per_step(
    multistep_task_dir: Path, tmp_path: Path
) -> None:
    """memo §6.13: aws-bench's task-level ban cannot see a per-step verifier env.

    A step declaring its own verifier environment would make Harbor stop the
    agent container mid-trial, stranding every later step (and every AWS phase
    script, which run in that container).
    """
    task = AwsBenchTask(multistep_task_dir)
    validate_multi_step_layout(task)  # the fixture is clean

    task.config.steps[0].verifier.environment_mode = VerifierEnvironmentMode.SEPARATE
    with pytest.raises(ValueError, match="separate-environment verifier"):
        validate_multi_step_layout(task)
