"""Gate 1 (gates/preflight.py) unit-tested with an injected fake docker
runner -- no real Docker daemon or built arm images required. `run_preflight`
takes a `runner` callable for exactly this reason (see its docstring)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import pytest

from gates.preflight import ARM_ENTRYPOINTS, run_preflight


@dataclass
class _FakeCompleted:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _fake_runner_factory(returncode: int, stdout: str = "", stderr: str = ""):
    calls = []

    def _runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)

    _runner.calls = calls
    return _runner


@pytest.mark.parametrize("arm", sorted(ARM_ENTRYPOINTS))
def test_success_reports_ok_true(arm: str) -> None:
    runner = _fake_runner_factory(0, stdout="preflight: all checks passed", stderr="")
    report = run_preflight(arm, runner=runner)
    assert report["ok"] is True
    assert report["exit_code"] == 0
    assert report["reason"] is None
    assert report["arm"] == arm
    assert report["entrypoint"] == ARM_ENTRYPOINTS[arm]
    assert report["image"] == f"cdktn-bench/{arm}:dev"
    assert len(runner.calls) == 1
    cmd = runner.calls[0][0]
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert "--network" in cmd and "none" in cmd
    assert "--memory" in cmd and "4g" in cmd
    assert cmd[-2:] == ["--entrypoint", ARM_ENTRYPOINTS[arm]] or ARM_ENTRYPOINTS[arm] in cmd


def test_nonzero_exit_reports_ok_false_with_reason() -> None:
    runner = _fake_runner_factory(1, stdout="", stderr="FAIL tsc --noEmit failed\nerror TS2345 ...")
    report = run_preflight("awscdk", runner=runner)
    assert report["ok"] is False
    assert report["exit_code"] == 1
    assert "preflight-script-failed" in report["reason"]


def test_oom_exit_code_is_classified() -> None:
    runner = _fake_runner_factory(137, stdout="", stderr="")
    report = run_preflight("terraconstructs", runner=runner)
    assert report["ok"] is False
    assert report["reason"] == "oom-killed"


def test_image_not_found_is_classified() -> None:
    runner = _fake_runner_factory(
        125,
        stdout="",
        stderr="docker: Error response from daemon: Unable to find image 'cdktn-bench/hcl-raw:dev' locally.",
    )
    report = run_preflight("hcl-raw", runner=runner)
    assert report["ok"] is False
    assert report["reason"] == "image-not-found"


def test_docker_daemon_unreachable_is_classified() -> None:
    runner = _fake_runner_factory(
        1,
        stdout="",
        stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
    )
    report = run_preflight("awscdk", runner=runner)
    assert report["ok"] is False
    assert report["reason"] == "docker-daemon-unreachable"


def test_docker_binary_missing_is_handled() -> None:
    def _runner(cmd, **kwargs):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'docker'")

    report = run_preflight("awscdk", runner=_runner)
    assert report["ok"] is False
    assert report["exit_code"] is None
    assert "docker binary not found" in report["reason"]


def test_timeout_is_handled() -> None:
    def _runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 300))

    report = run_preflight("awscdk", runner=_runner, timeout=5)
    assert report["ok"] is False
    assert report["exit_code"] is None
    assert "timed out" in report["reason"]


def test_unknown_arm_reports_ok_false_without_invoking_runner() -> None:
    runner = _fake_runner_factory(0)
    report = run_preflight("pulumi", runner=runner)
    assert report["ok"] is False
    assert "unknown arm" in report["reason"]
    assert runner.calls == []


def test_image_override_is_used() -> None:
    runner = _fake_runner_factory(0)
    report = run_preflight("awscdk", image="my-registry/awscdk:custom", runner=runner)
    assert report["image"] == "my-registry/awscdk:custom"
    assert "my-registry/awscdk:custom" in runner.calls[0][0]


def test_hcl_raw_entrypoint_differs_from_the_other_two() -> None:
    assert ARM_ENTRYPOINTS["hcl-raw"] == "/opt/preflight/preflight.sh"
    assert ARM_ENTRYPOINTS["awscdk"] == ARM_ENTRYPOINTS["terraconstructs"] == "/usr/local/bin/preflight.sh"
