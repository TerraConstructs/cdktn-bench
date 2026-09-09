"""The post-trial reset retries a client timeout, and only a client timeout.

A reset that AWS never answered must not take a shard out of the pool on the
first try: `Read timeout on endpoint URL` is the shape that fails a reset and
then succeeds on an unchanged retry against an unchanged account. These tests
pin the rule's three halves — a transient failure is re-run under a wall-clock
budget that counts whole attempts, a RESOLVED one (a harness deadline included)
is not re-run at all, and the operator gets the failure's real ending.

Contamination itself is upstream's and is deliberately not re-implemented here:
each reset pass flags on failure and clears on success, so a succeeding retry
clears the flag its predecessor set.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path

import pytest

from cdktn_bench import trial as trial_module
from cdktn_bench.aws_transient import (
    MAX_RESET_ATTEMPTS,
    MAX_RESET_RETRY_WALL_S,
    RESET_BACKOFF_BASE_S,
    RESET_BACKOFF_CAP_S,
    classify,
    reset_backoff_delays,
)
from cdktn_bench.trial import (
    RESET_RAISED,
    RESET_REPORTED,
    TransientResetRetryMixin,
)

TRANSIENT = (RESET_REPORTED, 'ResetFailedError: Read timeout on endpoint URL: "None"')
RESOLVED = (RESET_REPORTED, "ResetFailedError: AccessDenied when calling DeleteStack")
RAISED = (RESET_RAISED, "BuildError: container build failed")

CONTAMINATED = "flagged contaminated"


class _FakeTrial(TransientResetRetryMixin):
    """Only what ``_reset_scenario_account`` touches, with the pass faked out.

    ``attempt_duration_s`` is how long one reset pass takes on the fake clock,
    so the wall budget is exercised by the attempts themselves rather than by
    the sleeps between them.
    """

    def __init__(self, failures, attempt_duration_s: float = 0.0) -> None:
        self.failures = list(failures)
        self.attempt_duration_s = attempt_duration_s
        self.attempts: list[int] = []
        self.logger = logging.getLogger("cdktn-bench-test-reset")
        self.slept: list[float] = []
        self.clock = 0.0
        self.config = type("Cfg", (), {"scenario_id": "anchor"})()

    async def _attempt_scenario_reset(self, attempt: int):
        self.attempts.append(attempt)
        self.clock += self.attempt_duration_s
        return self.failures[min(attempt - 1, len(self.failures) - 1)]


def _run(trial: _FakeTrial, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep(seconds: float) -> None:
        trial.slept.append(seconds)
        trial.clock += seconds

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    monkeypatch.setattr(trial_module.time, "monotonic", lambda: trial.clock)
    asyncio.run(trial._reset_scenario_account())


def test_a_transient_reset_is_retried_until_it_succeeds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    trial = _FakeTrial([TRANSIENT, TRANSIENT, None])
    with caplog.at_level(logging.INFO):
        _run(trial, monkeypatch)
    assert trial.attempts == [1, 2, 3]
    assert len(trial.slept) == 2
    assert "transient" in caplog.text
    assert CONTAMINATED not in caplog.text


def test_a_resolved_reset_is_not_retried_and_still_flags_the_account(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    trial = _FakeTrial([RESOLVED])
    with caplog.at_level(logging.INFO):
        _run(trial, monkeypatch)
    assert trial.attempts == [1]
    assert trial.slept == []
    assert "resolved" in caplog.text
    assert CONTAMINATED in caplog.text


def test_an_unrecovered_transient_reset_still_flags_the_account(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Fail-closed: exhausting the retries changes nothing about the outcome."""
    trial = _FakeTrial([TRANSIENT])
    with caplog.at_level(logging.INFO):
        _run(trial, monkeypatch)
    assert trial.attempts == list(range(1, MAX_RESET_ATTEMPTS + 1))
    assert CONTAMINATED in caplog.text


def test_a_slow_attempt_spends_the_wall_budget_and_stops_the_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound counts attempts, not sleeps, so a slow reset ends the retry."""
    duration = MAX_RESET_RETRY_WALL_S / 1.5
    trial = _FakeTrial([TRANSIENT], attempt_duration_s=duration)
    _run(trial, monkeypatch)
    assert trial.attempts == [1, 2]
    assert trial.clock <= MAX_RESET_RETRY_WALL_S + duration


def test_a_reset_that_raised_reports_the_exception_not_a_contamination_claim(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Tags are applied inside a pass, so a pass that raised may have set none."""
    trial = _FakeTrial([RAISED])
    with caplog.at_level(logging.INFO):
        _run(trial, monkeypatch)
    assert "Post-trial reset raised for anchor" in caplog.text
    assert "container build failed" in caplog.text
    assert CONTAMINATED not in caplog.text


def test_the_final_attempt_is_logged_at_error_with_its_classification(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An operator at WARNING must still see why the reset was given up on."""
    trial = _FakeTrial([TRANSIENT, RESOLVED])
    with caplog.at_level(logging.INFO):
        _run(trial, monkeypatch)
    attempt_lines = [r for r in caplog.records if "classified" in r.getMessage()]
    assert [r.levelno for r in attempt_lines] == [logging.INFO, logging.ERROR]


def test_the_reset_backoff_is_bounded_and_never_shorter_than_its_floor() -> None:
    delays = list(reset_backoff_delays(rand=lambda: 1.0))
    assert len(delays) == MAX_RESET_ATTEMPTS - 1
    assert max(delays) <= RESET_BACKOFF_CAP_S * 1.25
    assert min(delays) >= RESET_BACKOFF_BASE_S


def test_reset_failure_texts_classify_as_intended() -> None:
    assert classify(TRANSIENT[1]) == "transient"
    assert classify(RESOLVED[1]) == "resolved"
    assert classify("ResetFailedError: Stack ScenarioStack is in DELETE_FAILED") == "resolved"
    # A deadline the harness imposed is a verdict, not an unanswered question:
    # retrying it spends another whole reset pass to earn the same timeout.
    assert classify("PhaseTimeoutError: reset phase timed out after 300s") == "resolved"
    assert classify("PhaseTimeoutError: build phase timed out after 600s") == "resolved"
    assert classify("ResetFailedError: Stack ScenarioStack deletion timed out") == "resolved"


def test_signal_extraction_skips_every_reset_directory_name(
    tmp_path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reset artifact is not an agent trial, whichever attempt produced it.

    A retry directory read as a trial prints a row with no arm and reports the
    reset's own exception as an INFRA-FAIL against a task that never failed.
    """
    spec = importlib.util.spec_from_file_location(
        "extract_signals", Path(__file__).resolve().parents[2] / "metrics" / "extract_signals.py"
    )
    extract_signals = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract_signals)

    names = [trial_module.RESET_TRIAL_NAME_PREFIX] + [
        f"{trial_module.RESET_TRIAL_NAME_PREFIX}-retry-{n}"
        for n in range(2, MAX_RESET_ATTEMPTS + 1)
    ]
    job_dir = tmp_path / "job" / "2026-01-01__00-00-00"
    for name in names:
        directory = job_dir / name
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(
            json.dumps({"exception_info": {"exception_type": "ResetFailedError"}})
        )

    monkeypatch.setenv("SIGNALS_OUT", str(tmp_path / "signals.json"))
    extract_signals.main([str(job_dir)])
    assert "INFRA-FAIL" not in capsys.readouterr().out
