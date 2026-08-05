"""Thin integration tests for each gate's argparse-driven `main()`, run
in-process (capsys) rather than via subprocess -- fast, and still exercises
the real CLI wiring end-to-end, not just the library functions."""

from __future__ import annotations

import json

from gates.audit import main as audit_main
from gates.emit_result import main as emit_result_main
from gates.tests.conftest import trial_dir

FAKE_DIGEST_IMAGE_REF = "cdktn-bench/fixture@sha256:" + "1" * 64


def test_audit_cli_valid_exits_zero(capsys) -> None:
    rc = audit_main([str(trial_dir("awscdk", "genuine")), "--arm", "awscdk"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is True


def test_audit_cli_bypass_exits_nonzero(capsys) -> None:
    rc = audit_main([str(trial_dir("hcl-raw", "bypass")), "--arm", "hcl-raw"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is False
    assert "invalid-bypass" in out["reason"]


def test_audit_cli_missing_trial_dir_exits_two(capsys) -> None:
    rc = audit_main(["/nonexistent/trial", "--arm", "awscdk"])
    assert rc == 2


def test_emit_result_cli_valid_exits_zero(capsys, task_dir) -> None:
    rc = emit_result_main(
        [
            str(trial_dir("terraconstructs", "genuine")),
            "--arm",
            "terraconstructs",
            "--task-dir",
            str(task_dir),
            "--image-ref",
            FAKE_DIGEST_IMAGE_REF,
            "--extra-cfg",
            '{"model": "claude-sonnet-5"}',
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["validity_class"] == "valid"
    assert out["score_emitted"] is True


def test_emit_result_cli_infra_failure_exits_nonzero(capsys, task_dir) -> None:
    rc = emit_result_main(
        [
            str(trial_dir("hcl-raw", "infra-failure")),
            "--arm",
            "hcl-raw",
            "--task-dir",
            str(task_dir),
            "--image-ref",
            FAKE_DIGEST_IMAGE_REF,
        ]
    )
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["validity_class"] == "invalid-infra"
    assert out["score_emitted"] is False


def test_emit_result_cli_rejects_bad_extra_cfg(capsys, task_dir) -> None:
    rc = emit_result_main(
        [
            str(trial_dir("awscdk", "genuine")),
            "--arm",
            "awscdk",
            "--task-dir",
            str(task_dir),
            "--image-ref",
            FAKE_DIGEST_IMAGE_REF,
            "--extra-cfg",
            "not json",
        ]
    )
    assert rc == 2
