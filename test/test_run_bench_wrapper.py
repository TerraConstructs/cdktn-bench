"""Unit tests for scripts/run-bench.sh's argument assembly and model/token
wiring, exercised entirely via --dry-run (AWS_BENCH_DRY_RUN=1): the script
prints the argv it would pass to `uv run aws-bench` and a
CLAUDE_CODE_OAUTH_TOKEN_SET flag, then exits — no `uv`, `aws-bench`, AWS
account, or Claude Code call is ever touched by these tests.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_BENCH = REPO_ROOT / "scripts" / "run-bench.sh"


def run_dry(
    args: list[str],
    *,
    env: dict[str, str],
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    base_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    full_env = {**base_env, **env}
    return subprocess.run(
        ["bash", str(RUN_BENCH), "--dry-run", *args],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestModelDefaulting:
    def test_default_model_is_claude_sonnet_5(self, tmp_path: Path) -> None:
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert " -m claude-sonnet-5 " in proc.stdout

    def test_model_env_var_overrides_default(self, tmp_path: Path) -> None:
        proc = run_dry(
            [], env={"MODEL": "claude-haiku-4-5-20251001"}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert " -m claude-haiku-4-5-20251001 " in proc.stdout

    def test_model_flag_overrides_env_var(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--model", "claude-haiku-4-5-20251001"],
            env={"MODEL": "claude-sonnet-5"},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert " -m claude-haiku-4-5-20251001 " in proc.stdout

    def test_short_model_flag_works(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["-m", "claude-haiku-4-5-20251001"], env={}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert " -m claude-haiku-4-5-20251001 " in proc.stdout

    def test_no_bedrock_naming_by_default(self, tmp_path: Path) -> None:
        """The default model string must be the bare Anthropic-API/OAuth
        name, not a Bedrock-style `global.anthropic.*` ARN-ish string —
        this script never sets CLAUDE_CODE_USE_BEDROCK /
        AWS_BEARER_TOKEN_BEDROCK, so ClaudeCode.run() takes the plain-API
        model-name path (claude_code.py:1074-1091)."""
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "global.anthropic." not in proc.stdout
        assert "anthropic.claude" not in proc.stdout


class TestJobsDirDefaulting:
    def test_default_jobs_dir_is_derived_from_model(self, tmp_path: Path) -> None:
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert " -o jobs/claude-sonnet-5" in proc.stdout

    def test_explicit_jobs_dir_flag_wins(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["-o", "jobs/custom-cell"], env={}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert " -o jobs/custom-cell" in proc.stdout
        assert "jobs/claude-sonnet-5" not in proc.stdout

    def test_long_jobs_dir_flag(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--jobs-dir", "jobs/another-cell"], env={}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert " -o jobs/another-cell" in proc.stdout


class TestLocalRegistryFlagsSurfaced:
    """The flags local-registry.md's documented invocations need must all
    reach `uv run aws-bench run` unchanged."""

    def test_scenario_path_and_task_path(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--scenario-path", "./scenarios", "--path", "./tasks/anchor"],
            env={},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "--scenario-path ./scenarios" in proc.stdout
        assert "--path ./tasks/anchor" in proc.stdout

    def test_registry_path_and_dataset(self, tmp_path: Path) -> None:
        proc = run_dry(
            [
                "--registry-path",
                "./local-registry.json",
                "-d",
                "cdktn-bench-anchor@0.1.0",
            ],
            env={},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "--registry-path ./local-registry.json" in proc.stdout
        assert "-d cdktn-bench-anchor@0.1.0" in proc.stdout

    def test_env_name_n_tasks_n_attempts_yes(self, tmp_path: Path) -> None:
        proc = run_dry(
            [
                "--env-name",
                "cdktn-anchor",
                "-l",
                "1",
                "-k",
                "1",
                "--yes",
            ],
            env={},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "--env-name cdktn-anchor" in proc.stdout
        assert " -l 1" in proc.stdout
        assert " -k 1" in proc.stdout
        assert "--yes" in proc.stdout

    def test_agent_defaults_to_claude_code(self, tmp_path: Path) -> None:
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert " -a claude-code " in proc.stdout

    def test_unrecognized_args_pass_through_verbatim(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--", "-i", "some-glob-*", "--extra-instruction-path", "./x.md"],
            env={},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "-i some-glob-*" in proc.stdout
        assert "--extra-instruction-path ./x.md" in proc.stdout


class TestTokenWiringEndToEnd:
    """Confirms the wrapper actually calls into the token-resolution logic
    (not just that the isolated resolve function works) and that the token
    value never appears in the wrapper's own dry-run output."""

    def test_reports_token_unset_with_no_source_available(
        self, tmp_path: Path
    ) -> None:
        proc = run_dry(
            [],
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(tmp_path / "nope")},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "CLAUDE_CODE_OAUTH_TOKEN_SET=0" in proc.stdout

    def test_reports_token_set_from_file(self, tmp_path: Path) -> None:
        token_file = tmp_path / "tok"
        token_file.write_text("fake-wiring-test-token\n")

        proc = run_dry(
            [],
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "CLAUDE_CODE_OAUTH_TOKEN_SET=1" in proc.stdout
        assert "fake-wiring-test-token" not in proc.stdout
        assert "fake-wiring-test-token" not in proc.stderr

    def test_reports_token_set_from_preexisting_env_var(
        self, tmp_path: Path
    ) -> None:
        proc = run_dry(
            [],
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(tmp_path / "nope"),
                "CLAUDE_CODE_OAUTH_TOKEN": "fake-preexisting-env-token",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "CLAUDE_CODE_OAUTH_TOKEN_SET=1" in proc.stdout
        assert "fake-preexisting-env-token" not in proc.stdout
        assert "fake-preexisting-env-token" not in proc.stderr

    def test_dry_run_argv_never_contains_the_token(self, tmp_path: Path) -> None:
        """The token travels as an env var, never as an argv entry — dry-run
        output is argv-only, so it structurally cannot leak the token
        regardless of resolution source. This test pins that invariant."""
        token_file = tmp_path / "tok"
        token_file.write_text("fake-argv-leakage-guard-token\n")

        proc = run_dry(
            ["--scenario-path", "./scenarios", "--path", "./tasks/anchor"],
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
                "ANTHROPIC_API_KEY": "fake-api-key-also-should-not-leak",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        assert "fake-argv-leakage-guard-token" not in proc.stdout
        assert "fake-argv-leakage-guard-token" not in proc.stderr
        assert "fake-api-key-also-should-not-leak" not in proc.stdout
        assert "fake-api-key-also-should-not-leak" not in proc.stderr


class TestHelp:
    def test_help_flag_exits_zero_and_does_not_touch_token_resolution(
        self, tmp_path: Path
    ) -> None:
        token_file = tmp_path / "tok"
        token_file.write_text("fake-help-path-token\n")

        base_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
        }
        proc = subprocess.run(
            ["bash", str(RUN_BENCH), "--help"],
            cwd=REPO_ROOT,
            env=base_env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0, proc.stderr
        assert "Usage: scripts/run-bench.sh" in proc.stdout
        assert "fake-help-path-token" not in proc.stdout
        assert "fake-help-path-token" not in proc.stderr
