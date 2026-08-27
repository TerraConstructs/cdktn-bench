"""Offline unit tests for gates/aws_stub.py.

`running_stub()` is load-bearing for three host checks
(`gates/oracle_falsifiability.py`, `gates/grading_proof.py`,
`generator/check_reference_paths.py`), and every one of them is silently
wrong if the stub answers the wrong thing or the yielded environment still
carries an operator's ambient AWS state. Everything here runs on loopback
with no toolchain, no Docker and no network.
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gates import aws_stub  # noqa: E402
from gates.aws_stub import running_stub  # noqa: E402


def _post(env: dict[str, str], body: bytes, headers: dict[str, str] | None = None):
    """POST to the stub named by `env["AWS_ENDPOINT_URL"]` -> (status, body)."""
    req = urllib.request.Request(env["AWS_ENDPOINT_URL"], data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _port_of(env: dict[str, str]) -> int:
    return int(env["AWS_ENDPOINT_URL"].rsplit(":", 1)[1])


class TestRoutes:
    def test_get_caller_identity_answers_200_with_the_stub_account(self):
        with running_stub() as env:
            status, body = _post(
                env,
                b"Action=GetCallerIdentity&Version=2011-06-15",
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert status == 200
        assert b"<Account>123456789012</Account>" in body

    def test_account_id_override_reaches_the_subprocess(self):
        with running_stub(account_id="210987654321") as env:
            status, body = _post(env, b"Action=GetCallerIdentity")
        assert status == 200
        assert b"<Account>210987654321</Account>" in body

    def test_validate_state_machine_definition_answers_200(self):
        with running_stub() as env:
            status, body = _post(
                env,
                b'{"definition":"{}"}',
                {"X-Amz-Target": "AWSStepFunctions.ValidateStateMachineDefinition"},
            )
        assert status == 200
        assert b'"result":"OK"' in body

    def test_unsupported_operation_is_a_logged_400_not_a_silent_success(self):
        """An operation the gates don't need must fail loudly: a 200 here
        would let a gate 'pass' against a route that answers nothing real."""
        with running_stub() as env:
            status, body = _post(
                env,
                b"{}",
                {"X-Amz-Target": "AWSStepFunctions.CreateStateMachine"},
            )
        assert status == 400
        assert b"UnsupportedOperation" in body


class TestYieldedEnvironment:
    def test_ambient_aws_state_is_scrubbed_and_non_aws_state_survives(self, monkeypatch):
        monkeypatch.setenv("AWS_PROFILE", "operator-sso")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-token")
        monkeypatch.setenv("AWS_ENDPOINT_URL_STS", "https://sts.example.invalid")
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/home/op/.aws/credentials")
        monkeypatch.setenv("AWS_CONFIG_FILE", "/home/op/.aws/config")
        monkeypatch.setenv("AWS_CA_BUNDLE", "/home/op/corp-ca.pem")
        monkeypatch.setenv("CDKTN_BENCH_MARKER", "kept")

        with running_stub() as env:
            leftovers = {
                k: v
                for k, v in env.items()
                if k.startswith("AWS_")
                and k
                not in {
                    "AWS_ENDPOINT_URL",
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "AWS_REGION",
                }
            }
            assert leftovers == {}
            assert env["AWS_ACCESS_KEY_ID"] == "AKIAIOSFODNN7EXAMPLE"
            assert env["AWS_SECRET_ACCESS_KEY"] == "dummy-secret-key-not-real"
            assert env["AWS_REGION"] == "us-east-1"
            assert env["AWS_ENDPOINT_URL"].startswith("http://127.0.0.1:")
            # A `env=` kwarg REPLACES the environment, so anything a
            # toolchain subprocess needs must still be there.
            assert env["CDKTN_BENCH_MARKER"] == "kept"
            assert env["PATH"].endswith(os.environ["PATH"])

    def test_aws_cli_is_resolvable_from_the_yielded_path(self):
        """The generated tests/static_tiers.sh preflight shells out to plain
        `aws`; the yielded PATH must resolve it (directly or via the shim)."""
        import shutil

        with running_stub() as env:
            assert shutil.which("aws", path=env["PATH"]) is not None


class TestLifecycle:
    def test_port_announce_failure_raises(self, tmp_path, monkeypatch):
        dead = tmp_path / "dead_stub.py"
        dead.write_text("import sys; sys.exit(3)\n")
        monkeypatch.setattr(aws_stub, "_SCRIPT", dead)
        with pytest.raises(RuntimeError, match="did not announce a port"):
            with running_stub():
                pytest.fail("running_stub must not yield when the stub never bound")

    def test_missing_aws_and_mise_raises_instead_of_yielding_a_doomed_env(
        self, monkeypatch
    ):
        monkeypatch.setattr(aws_stub.shutil, "which", lambda name, *a, **k: None)
        with pytest.raises(RuntimeError, match="no `aws` CLI on PATH"):
            with running_stub():
                pytest.fail("a preflight that cannot run `aws` must fail loudly")

    def test_shim_dir_is_removed_when_the_with_body_raises(self, monkeypatch):
        # `aws` absent, `mise` present -> the shim branch, on any host.
        monkeypatch.setattr(
            aws_stub.shutil,
            "which",
            lambda name, *a, **k: None if name == "aws" else "/usr/bin/mise",
        )
        shim_dir = None
        with pytest.raises(RuntimeError, match="boom"):
            with running_stub() as env:
                shim_dir = Path(env["PATH"].split(os.pathsep)[0])
                assert (shim_dir / "aws").exists()
                raise RuntimeError("boom")
        assert shim_dir is not None and not shim_dir.exists()

    def test_stub_is_torn_down_when_the_with_body_raises(self):
        sentinel = RuntimeError("boom")
        port = None
        with pytest.raises(RuntimeError, match="boom"):
            with running_stub() as env:
                port = _port_of(env)
                raise sentinel
        assert port is not None
        with socket.socket() as sock:
            sock.settimeout(5)
            assert sock.connect_ex(("127.0.0.1", port)) != 0
