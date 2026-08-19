"""The per-step harness hook and the reward strategy.

Two behaviours that only exist in cdktn_bench and that a live run would take
~20 minutes and real AWS money to exercise:

1. ``_prepare_step`` runs ``steps/<name>/pre_invoke/pre_invoke.sh`` through
   aws-bench's ``ScriptRunner`` with staged credentials, feeds its
   ``placeholder.json`` into the trial's placeholder map, and aborts the step
   (rather than the trial) when it fails.
2. ``_select_multi_step_reward`` defaults to ``final``, not Harbor's ``mean``.

The ScriptRunner itself is not re-tested here (it is upstream, and it is
covered upstream); what is tested is that we hand it the right *step-rebased*
paths, since that re-basing is the entire cdktn contribution.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aws_bench.dataset.models import ScriptType
from harbor.models.task.config import MultiStepRewardStrategy, StepConfig
from harbor.models.trial.result import StepResult
from harbor.models.verifier.result import VerifierResult
from harbor.trial.multi_step import MultiStepTrial

from cdktn_bench.tests.conftest import make_trial_config
from cdktn_bench.trial import CdktnTrial


@pytest.fixture
def trial(multistep_task_dir: Path, tmp_path: Path, no_account_manager: None):
    return asyncio.run(
        CdktnTrial.create(make_trial_config(multistep_task_dir, tmp_path, trial_name="ms"))
    )


# ── the harness hook ──────────────────────────────────────────────────────


def test_step_pre_invoke_is_discovered_per_step(trial) -> None:
    """Only the step that declares one gets one.

    ``AwsBenchTask.phase_script_path`` cannot answer this: it hardcodes
    ``task_dir / <script_type>``, i.e. the task-level script only.
    """
    assert trial.step_pre_invoke_script_path("01-initial") is None
    found = trial.step_pre_invoke_script_path("02-change-request")
    assert found is not None
    assert found.name == "pre_invoke.sh"
    assert found.parent.parent.name == "02-change-request"


def test_step_without_pre_invoke_runs_no_script(trial, monkeypatch) -> None:
    called: list[str] = []

    async def _never(self, step):
        called.append(step.name)
        return {}

    monkeypatch.setattr(type(trial), "_run_step_phase_script", _never)
    step_result = StepResult(step_name="01-initial")
    asyncio.run(trial._run_step_pre_invoke(StepConfig(name="01-initial"), step_result))
    assert called == []
    assert step_result.exception_info is None


def test_step_pre_invoke_placeholders_feed_the_next_prompt(trial, monkeypatch) -> None:
    """The hand-off memo §4(a) item 3 describes.

    A drift-injection script emits the id of the resource it just mutated; the
    step's instruction interpolates it as ``{{...}}`` in
    ``AwsBenchSingleStepTrial._run_agent_phase``.
    """
    trial._aws_placeholders = {"main": {"Existing": "keep-me"}}

    async def _fake(self, step):
        return {"ToyParameterName": "/cdktn-bench/toy"}

    monkeypatch.setattr(type(trial), "_run_step_phase_script", _fake)
    step_result = StepResult(step_name="02-change-request")
    asyncio.run(
        trial._run_step_pre_invoke(StepConfig(name="02-change-request"), step_result)
    )
    assert trial._aws_placeholders["main"] == {
        "Existing": "keep-me",
        "ToyParameterName": "/cdktn-bench/toy",
    }
    assert step_result.exception_info is None


def test_a_later_step_may_overwrite_an_earlier_placeholder(trial, monkeypatch) -> None:
    """Deliberate divergence from aws-bench's task-level call, which raises.

    Across steps, re-emitting a key is the expected pattern: each step's
    harness action reports the CURRENT id of a resource it just redeployed.
    """
    trial._aws_placeholders = {"main": {"ToyParameterName": "old"}}

    async def _fake(self, step):
        return {"ToyParameterName": "new"}

    monkeypatch.setattr(type(trial), "_run_step_phase_script", _fake)
    asyncio.run(
        trial._run_step_pre_invoke(
            StepConfig(name="02-change-request"), StepResult(step_name="02-change-request")
        )
    )
    assert trial._aws_placeholders["main"]["ToyParameterName"] == "new"


def test_pre_invoke_failure_aborts_the_step_not_the_trial(trial, monkeypatch) -> None:
    """Matches how Harbor treats a failing ``setup.sh``.

    ``MultiStepTrial._run_step`` checks ``step_result.exception_info`` right
    after ``_prepare_step`` and returns; ``_should_stop_after_step`` then ends
    the trial. Raising instead would skip result persistence for the steps that
    DID run.
    """
    prepared: list[str] = []

    async def _boom(self, step):
        raise RuntimeError("terraform apply failed")

    async def _super_prepare(self, step, step_result):
        prepared.append(step.name)

    monkeypatch.setattr(type(trial), "_run_step_phase_script", _boom)
    monkeypatch.setattr(MultiStepTrial, "_prepare_step", _super_prepare)

    step_result = StepResult(step_name="02-change-request")
    asyncio.run(trial._prepare_step(StepConfig(name="02-change-request"), step_result))

    assert step_result.exception_info is not None
    assert step_result.exception_info.exception_type == "RuntimeError"
    # Harbor's own step prep must NOT have run: a step that is already lost
    # should not also pay for a container upload.
    assert prepared == []


def test_harness_action_runs_before_harbor_step_prep(trial, monkeypatch) -> None:
    order: list[str] = []

    async def _fake(self, step):
        order.append("pre_invoke")
        return {}

    async def _super_prepare(self, step, step_result):
        order.append("harbor_prepare_step")

    monkeypatch.setattr(type(trial), "_run_step_phase_script", _fake)
    monkeypatch.setattr(MultiStepTrial, "_prepare_step", _super_prepare)
    asyncio.run(
        trial._prepare_step(
            StepConfig(name="02-change-request"), StepResult(step_name="02-change-request")
        )
    )
    assert order == ["pre_invoke", "harbor_prepare_step"]


def test_script_runner_is_rebased_onto_the_step(trial, monkeypatch) -> None:
    """The one line that answers upstream's "per-step credentialing is undefined".

    ``ScriptRunner`` derives every path from ``script_type.value`` relative to
    the ``task_dir``/``trial_paths`` it is handed, so re-basing both onto the
    step yields ``steps/<n>/pre_invoke/`` in and ``<trial>/steps/<n>/pre_invoke/``
    out, with no upstream change at all.
    """
    captured: dict = {}

    class _FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, output_file_name=None):
            captured["output_file_name"] = output_file_name
            return {}

    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_creds(self, role_type):
        captured["role_type"] = role_type
        yield {"AWS_PROFILE": "main"}

    monkeypatch.setattr("cdktn_bench.trial.ScriptRunner", _FakeRunner)
    monkeypatch.setattr(type(trial), "_staged_credentials", _fake_creds)

    asyncio.run(trial._run_step_phase_script(StepConfig(name="02-change-request")))

    assert captured["script_type"] is ScriptType.PRE_INVOKE
    assert captured["task_dir"] == trial.task.paths.step_dir("02-change-request")
    assert (
        captured["trial_paths"].trial_dir == trial.paths.step_dir("02-change-request")
    )
    assert captured["output_file_name"] == "placeholder.json"
    # Per-task role for now; per-step roles are memo §7 Q9, deliberately deferred.
    assert captured["role_type"].value == "pre-invoke"


# ── reward strategy ───────────────────────────────────────────────────────


def _with_step_rewards(trial, rewards: list[float | None]):
    import types

    trial._result = types.SimpleNamespace(
        step_results=[
            StepResult(
                step_name=f"s{i}",
                verifier_result=None if r is None else VerifierResult(rewards={"reward": r}),
            )
            for i, r in enumerate(rewards)
        ]
    )
    return trial


def test_unset_strategy_defaults_to_final_not_mean(trial) -> None:
    """memo §6.6 / DECISIONS.md Amendment 26.

    With Harbor's ``mean`` default, a trial that failed step 1 and was aborted
    by the ``min_reward`` gate scores the mean of the ONE step it ran — which
    can beat a trial that ran both steps and failed the second. The last step's
    verdict is the trial's verdict.
    """
    assert trial.task.config.multi_step_reward_strategy is None
    _with_step_rewards(trial, [1.0, 0.0])
    assert trial._select_multi_step_reward().rewards == {"reward": 0.0}


def test_explicit_mean_is_still_honoured(trial) -> None:
    trial.task.config.multi_step_reward_strategy = MultiStepRewardStrategy.MEAN
    _with_step_rewards(trial, [1.0, 0.0])
    assert trial._select_multi_step_reward().rewards == {"reward": 0.5}


def test_aborted_trial_scores_the_step_it_failed(trial) -> None:
    """The green-gate case: step 1 fails, step 2 never runs."""
    _with_step_rewards(trial, [0.0])
    assert trial._select_multi_step_reward().rewards == {"reward": 0.0}


def test_reward_selection_does_not_mutate_the_task_config(trial) -> None:
    """``task.config`` is re-read by the verifier and the oracle agent."""
    _with_step_rewards(trial, [1.0])
    trial._select_multi_step_reward()
    assert trial.task.config.multi_step_reward_strategy is None


def test_no_steps_ran_yields_no_reward(trial) -> None:
    _with_step_rewards(trial, [])
    assert trial._select_multi_step_reward() is None
