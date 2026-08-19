"""The MRO composition is the whole design — so it is asserted, not assumed.

``docs/design/multistep-trial-investigation.md`` §2 claims that
``CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial)`` linearises so
that Harbor owns the multi-step *workload* and aws-bench owns the AWS
*lifecycle*. That claim is load-bearing: if a future aws-bench moved one of its
overrides onto ``SingleStepTrial``-specific ground, or if Harbor's
``MultiStepTrial`` grew a ``run``/``_prepare`` of its own, the composition would
silently start dropping credential staging or account reset — a multi-step trial
would run with NO AWS credentials and simply score 0, which is the worst kind of
failure for a benchmark: quiet and plausible.

These tests fail loudly on that day.
"""

from __future__ import annotations

import pytest
from aws_bench.task.aws_trial import AwsBenchSingleStepTrial
from harbor.trial.multi_step import MultiStepTrial
from harbor.trial.single_step import SingleStepTrial
from harbor.trial.trial import Trial

from cdktn_bench.trial import CdktnMultiStepTrial


def test_mro_is_exactly_the_documented_linearisation() -> None:
    assert CdktnMultiStepTrial.__mro__[:5] == (
        CdktnMultiStepTrial,
        MultiStepTrial,
        AwsBenchSingleStepTrial,
        SingleStepTrial,
        Trial,
    )


# (method, owning class) — the table in cdktn_bench/trial.py's docstring.
@pytest.mark.parametrize(
    ("method", "owner"),
    [
        # the multi-step workload
        ("_run", MultiStepTrial),
        ("_run_step", MultiStepTrial),
        ("_run_step_agent", MultiStepTrial),
        ("_run_step_verifier", MultiStepTrial),
        ("_should_stop_after_step", MultiStepTrial),
        ("_archive_step_outputs", MultiStepTrial),
        ("_create_step_dirs", MultiStepTrial),
        # the AWS lifecycle
        ("run", AwsBenchSingleStepTrial),
        ("_prepare", AwsBenchSingleStepTrial),
        ("_run_agent_phase", AwsBenchSingleStepTrial),
        ("_run_shared_verifier", AwsBenchSingleStepTrial),
        ("_stop_agent_environment", AwsBenchSingleStepTrial),
        ("_setup_agent_environment", AwsBenchSingleStepTrial),
        ("_init_logger", AwsBenchSingleStepTrial),
        ("_staged_credentials", AwsBenchSingleStepTrial),
        ("_run_phase_script", AwsBenchSingleStepTrial),
        ("_reset_scenario_account", AwsBenchSingleStepTrial),
        # our own deliberate overrides
        ("__init__", CdktnMultiStepTrial),
        ("_recover_outputs", CdktnMultiStepTrial),
        ("_prepare_step", CdktnMultiStepTrial),
        ("_select_multi_step_reward", CdktnMultiStepTrial),
    ],
)
def test_method_resolves_to_the_intended_owner(method: str, owner: type) -> None:
    resolved = getattr(CdktnMultiStepTrial, method)
    qualname = getattr(resolved, "__qualname__", None)
    assert qualname is not None, method
    assert qualname.split(".")[0] == owner.__name__, (
        f"{method} resolved to {qualname}, expected {owner.__name__}.{method}"
    )


def test_aws_lifecycle_overrides_live_on_trial_not_single_step() -> None:
    """The property that makes the composition work at all.

    ``AwsBenchSingleStepTrial`` contributes AWS behaviour by overriding
    ``Trial``-level lifecycle hooks. If any of them were instead an override of
    a ``SingleStepTrial``-only method, ``MultiStepTrial`` (which does not call
    that method) would never reach it.
    """
    for method in (
        "_prepare",
        "_run_agent_phase",
        "_run_shared_verifier",
        "_stop_agent_environment",
        "_setup_agent_environment",
        "_init_logger",
    ):
        assert hasattr(Trial, method), (
            f"aws-bench overrides {method!r}, but harbor's Trial no longer declares it — "
            "the AWS behaviour is no longer a Trial-level hook and the MRO "
            "composition may no longer deliver it to the multi-step engine."
        )


def test_single_step_guard_still_exists_upstream() -> None:
    """The obstacle our ``__init__`` exists to bypass must still be real.

    If upstream ever drops the guard, our ``Trial.__init__`` bypass becomes
    unnecessary (and, worse, starts skipping whatever ``SingleStepTrial.__init__``
    has grown in the meantime). Assert the guard, not its absence.
    """
    with pytest.raises(ValueError, match="without \\[\\[steps\\]\\]"):
        SingleStepTrial(config=None, _task=_FakeSteppedTask())  # type: ignore[arg-type]


class _FakeSteppedTask:
    has_steps = True
