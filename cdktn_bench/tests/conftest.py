"""Shared fixtures for cdktn_bench's tests.

Builds real ``AwsBenchTrialConfig`` objects over the toy task dirs in
``fixtures/`` so the dispatch/MRO tests exercise the actual construction path
(``Task`` parsing, ``TrialPaths``, agent + environment factories) rather than a
mock of it. No AWS call and no Docker daemon is involved: the environment
factory only *builds* a ``DockerEnvironment`` object here, it never starts it,
and the agent is the ``nop`` agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aws_bench.dataset.task_config import ConcurrencyMode
from aws_bench.scenario.locator import ScenarioConfig
from aws_bench.task.trial_config import AwsBenchTrialConfig
from harbor.models.trial.config import AgentConfig, TaskConfig

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MULTISTEP_TASK_DIR = FIXTURES_DIR / "multistep-task"
SINGLESTEP_TASK_DIR = FIXTURES_DIR / "singlestep-task"


def make_trial_config(
    task_dir: Path,
    trials_dir: Path,
    *,
    trial_name: str = "toy-trial",
) -> AwsBenchTrialConfig:
    """An ``AwsBenchTrialConfig`` pointing at ``task_dir``.

    ``verify_env=False`` skips the per-trial Organizations contamination read
    (``AwsBenchSingleStepTrial._raise_if_contaminated``), which is the only AWS
    call ``_prepare`` would make before the container starts. Nothing in these
    tests calls ``run()`` anyway; it is set for defence in depth.
    """
    return AwsBenchTrialConfig(
        trial_name=trial_name,
        trials_dir=trials_dir,
        task=TaskConfig(path=task_dir),
        agent=AgentConfig(name="nop"),
        scenario=ScenarioConfig(name="anchor", path=task_dir),
        scenario_id="anchor",
        concurrency_mode=ConcurrencyMode.MUTATING,
        account_mapping={"main": "000000000000"},
        verify_env=False,
    )


@pytest.fixture
def multistep_task_dir() -> Path:
    return MULTISTEP_TASK_DIR


@pytest.fixture
def singlestep_task_dir() -> Path:
    return SINGLESTEP_TASK_DIR


@pytest.fixture
def no_account_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``AccountManager`` in ``cdktn_bench.trial`` only.

    ``AccountManager()`` builds a boto3 Organizations client at construction.
    That makes no API call, but it does read the ambient AWS config, so a
    developer machine with an odd profile could turn a pure unit test into an
    environment-dependent one. Patched on OUR module's imported name — upstream
    ``aws_bench`` is never touched.
    """

    class _StubAccountManager:
        pass

    monkeypatch.setattr("cdktn_bench.trial.AccountManager", _StubAccountManager)
