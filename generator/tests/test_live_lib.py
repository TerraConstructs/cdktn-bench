"""The shared live-check retry runner: classification, bounds, and mapping.

A transient AWS failure must never become a verdict: under fail-closed gating,
one timed-out `describe-security-groups` scores a correct, deployed, converged
solution 0.0. `tests/_live_lib.py` is what stands between the two, so both of
its halves are pinned here — what counts as TRANSIENT, and that the retry it
buys stays bounded hard enough to fit inside the 900s verifier timeout.

Fail-closed is the property under test throughout: exhausting the budget must
still refuse reward, never award it.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import gen
from gen import LIVE_LIB_PY, write_tests_dir
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
# s3-acl-vs-object-ownership-log-delivery's observe() makes six sequential
# run_aws calls -- the most any oracle in this corpus makes, and therefore the
# call count every composite bound below is asserted against.
FATTEST_ORACLE_CALLS = 6
SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
# Resolved through the generator, never spelled out: a task's shard is
# `generator/shards.toml` arithmetic, so a literal path here goes stale the next
# time a shard is added and the failure reads as a missing file.
LIVE_CHECK = gen.task_dir(load_spec(SPEC), "awscdk") / "tests" / "live_check.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lib(tmp_path_factory: pytest.TempPathFactory):
    """The emitted `_live_lib.py` itself, imported from a real generated tree."""
    path = tmp_path_factory.mktemp("live_lib") / "_live_lib.py"
    path.write_text(LIVE_LIB_PY)
    return _load("_live_lib_under_test", path)


@pytest.fixture(autouse=True)
def _fresh_retry_budget(lib):
    """The retry budget is module state; one test must not spend another's."""
    lib.reset_retry_budget()
    yield
    lib.reset_retry_budget()


# (stderr or exception text, expected class). Every TRANSIENT row is a shape
# botocore or the CLI emits when the request reached no decision; every RESOLVED
# row is an answer AWS gave, which a retry would only re-collect.
CLASSIFICATION_TABLE = [
    ('Read timeout on endpoint URL: "None"', "transient"),
    ("Connect timeout on endpoint URL: https://ec2.us-east-1.amazonaws.com/", "transient"),
    ("botocore.exceptions.ConnectTimeoutError: Connect timeout", "transient"),
    ("EndpointConnectionError: Could not connect to the endpoint URL", "transient"),
    ("('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))", "transient"),
    ("aws ec2 describe-security-groups: client call timed out after 60s", "transient"),
    ("Connection timed out during endpoint resolution", "transient"),
    ("An error occurred (Throttling) when calling the DescribeStacks operation", "transient"),
    ("An error occurred (ThrottlingException) when calling the TestState operation", "transient"),
    ("An error occurred (RequestLimitExceeded) when calling DescribeInstances", "transient"),
    ("An error occurred (TooManyRequestsException) when calling GetFunction", "transient"),
    ("An error occurred (SlowDown) when calling the PutObject operation", "transient"),
    ("An error occurred (ServiceUnavailable) when calling the ListBuckets operation", "transient"),
    ("An error occurred (InternalError) when calling the DescribeVpcEndpoints operation", "transient"),
    ("An error occurred (500) when calling the GetBucketPolicy operation", "transient"),
    ("An error occurred (503) when calling the GetBucketPolicy operation", "transient"),
    ("An error occurred (AccessDenied) when calling the GetBucketAcl operation", "resolved"),
    ("An error occurred (AccessDeniedException) when calling TestState", "resolved"),
    ("An error occurred (ValidationException) when calling the TestState operation", "resolved"),
    ("An error occurred (NoSuchBucket) when calling the GetBucketLogging operation", "resolved"),
    ("An error occurred (ResourceNotFoundException) when calling GetAlias", "resolved"),
    ("An error occurred (NoSuchLifecycleConfiguration) when calling GetBucketLifecycle", "resolved"),
    ("Unable to locate credentials", "resolved"),
    ("You must specify a region.", "resolved"),
    ("aws: command not found", "resolved"),
    # A deadline someone else imposed is a verdict, not an unanswered question.
    ("PhaseTimeoutError: reset phase timed out after 300s", "resolved"),
    ("Stack ScenarioStack deletion timed out", "resolved"),
    ("", "resolved"),
]


@pytest.mark.parametrize(("text", "expected"), CLASSIFICATION_TABLE)
def test_classification(lib, text: str, expected: str) -> None:
    assert lib.classify(text) == expected


def test_backoff_is_bounded_capped_and_never_shorter_than_its_floor(lib) -> None:
    """Jitter only lengthens a delay, and the whole budget fits the verifier."""
    delays = list(lib.backoff_delays(rand=lambda: 1.0))
    assert len(delays) == lib.MAX_ATTEMPTS - 1
    floors = [lib.BACKOFF_BASE_S * 2**i for i in range(len(delays))]
    for delay, floor in zip(delays, floors):
        assert min(floor, lib.BACKOFF_CAP_S) <= delay <= lib.BACKOFF_CAP_S * (1 + lib.BACKOFF_JITTER)
    assert FATTEST_ORACLE_CALLS * lib.CALL_TIMEOUT_S + lib.MAX_PROCESS_RETRY_WALL_S < 900, (
        "the worst-case check could outlive the [verifier] timeout, which"
        " destroys the row instead of reporting it transient-exhausted"
    )


class _FakeRunner:
    """`subprocess.run` stand-in returning a scripted sequence of results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, argv, **kwargs):
        self.calls += 1
        rc, out, err = self.results[min(self.calls - 1, len(self.results) - 1)]
        return subprocess.CompletedProcess(argv, rc, out, err)


def test_transient_is_retried_until_it_succeeds(lib) -> None:
    slept: list[float] = []
    runner = _FakeRunner([(255, "", "Read timeout on endpoint URL"), (0, "{}", "")])
    rc, out, _ = lib.run_aws(
        ["ec2", "describe-security-groups"],
        sleep=slept.append,
        now=lambda: 0.0,
        rand=lambda: 0.0,
        runner=runner,
    )
    assert (rc, out) == (0, "{}")
    assert runner.calls == 2
    assert slept == [lib.BACKOFF_BASE_S]


def test_resolved_is_returned_on_the_first_attempt(lib) -> None:
    slept: list[float] = []
    runner = _FakeRunner([(254, "", "An error occurred (AccessDenied) when calling GetBucketAcl")])
    rc, _, err = lib.run_aws(
        ["s3api", "get-bucket-acl"], sleep=slept.append, now=lambda: 0.0, runner=runner
    )
    assert rc == 254
    assert "AccessDenied" in err
    assert runner.calls == 1
    assert slept == []


def test_exhausting_the_budget_raises_rather_than_answering(lib) -> None:
    runner = _FakeRunner([(255, "", "An error occurred (Throttling) when calling DescribeStacks")])
    with pytest.raises(lib.TransientExhausted) as caught:
        lib.run_aws(
            ["cloudformation", "describe-stacks"],
            sleep=lambda _s: None,
            now=lambda: 0.0,
            rand=lambda: 0.0,
            runner=runner,
        )
    assert runner.calls == lib.MAX_ATTEMPTS
    assert caught.value.kind == "transient-exhausted"


def test_the_wall_clock_cap_stops_retrying_before_the_attempt_cap(lib) -> None:
    """Both bounds are enforced; whichever binds first ends the call."""
    runner = _FakeRunner([(255, "", "Connect timeout on endpoint URL")])
    clock = iter([0.0] + [lib.MAX_TOTAL_WALL_S] * 10)
    with pytest.raises(lib.TransientExhausted):
        lib.run_aws(
            ["ec2", "describe-vpc-endpoints"],
            sleep=lambda _s: None,
            now=lambda: next(clock),
            rand=lambda: 0.0,
            runner=runner,
        )
    assert runner.calls == 1


def test_a_missing_aws_binary_is_resolved_not_retried(lib) -> None:
    def runner(argv, **kwargs):
        raise FileNotFoundError("aws")

    rc, _, err = lib.run_aws(["sts", "get-caller-identity"], runner=runner)
    assert rc == 127
    assert "aws" in err


def test_a_client_timeout_is_transient(lib) -> None:
    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 60)

    with pytest.raises(lib.TransientExhausted):
        lib.run_aws(
            ["ec2", "describe-security-groups"],
            sleep=lambda _s: None,
            now=lambda: 0.0,
            rand=lambda: 0.0,
            runner=runner,
        )


def test_the_helper_is_emitted_next_to_every_live_check(tmp_path: Path) -> None:
    """A live_check.py without its runner would die on import and grade nothing."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "live_check.py").write_bytes(LIVE_CHECK.read_bytes())
    write_tests_dir(load_spec(SPEC), "awscdk", tests_dir)
    assert (tests_dir / "_live_lib.py").read_text() == LIVE_LIB_PY


def test_an_exhausted_live_check_reports_not_verifiable_with_its_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lib
) -> None:
    """The mapping the whole change exists for, on a real hand-authored oracle.

    `poll()` is the pure boundary: with the account unreadable it must refuse
    to answer — never `pass`, never `fail_stale` — and it must say WHY, so an
    outage stays legible as one rather than reading as a bad solution.
    """
    # Copied out of the task tree before import: importing it in place makes
    # CPython write __pycache__ into a generated tests/ directory, which harbor
    # then uploads wholesale into the verifier container.
    oracle = tmp_path / "live_check.py"
    oracle.write_bytes(LIVE_CHECK.read_bytes())
    (tmp_path / "_live_lib.py").write_text(LIVE_LIB_PY)
    module = _load("named_resource_live_check", oracle)

    def _exhausted(args, **kwargs):
        raise module.TransientExhausted(f"aws {' '.join(args)}", 4, 42.0, "Read timeout")

    monkeypatch.setattr(module, "run_aws", _exhausted)
    result = module.poll()
    assert result["outcome"] == "not_verifiable"
    assert result["not_verifiable_kind"] == "transient-exhausted"
    assert result["failures"] == []


def test_the_whole_check_shares_one_retry_budget_across_its_calls(lib) -> None:
    """Six exhausted calls must still fit the verifier, not six full budgets.

    The retry cost is what is shared and bounded; a check's own polling is not
    charged to it, so a legitimately slow verdict never turns into an
    infrastructure one.
    """
    clock = [0.0]

    def runner(argv, timeout=None, **kwargs):
        clock[0] += timeout
        return subprocess.CompletedProcess(argv, 255, "", "Read timeout on endpoint URL")

    def sleep(seconds):
        clock[0] += seconds

    for _ in range(FATTEST_ORACLE_CALLS):
        with pytest.raises(lib.TransientExhausted):
            lib.run_aws(
                ["s3api", "get-bucket-acl"],
                sleep=sleep,
                now=lambda: clock[0],
                rand=lambda: 1.0,
                runner=runner,
            )
    budget = FATTEST_ORACLE_CALLS * lib.CALL_TIMEOUT_S + lib.MAX_PROCESS_RETRY_WALL_S
    assert clock[0] <= budget < 900


def test_polling_time_is_not_charged_to_the_retry_budget(lib) -> None:
    """A check that polls for minutes must still get its retries."""
    runner = _FakeRunner([(0, "{}", "")])
    clock = [0.0]

    def poll_slowly(_seconds):
        clock[0] += 300.0

    for _ in range(3):
        rc, _, _ = lib.run_aws(
            ["s3api", "get-bucket-acl"],
            sleep=poll_slowly,
            now=lambda: clock[0],
            runner=runner,
        )
        assert rc == 0
        poll_slowly(None)
    assert lib._retry_spent == 0.0
