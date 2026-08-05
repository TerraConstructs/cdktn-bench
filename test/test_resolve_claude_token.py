"""Unit tests for scripts/lib/resolve-claude-token.sh's token precedence.

These tests never contact a real Claude Code / Anthropic endpoint and never
read the user's real ~/.anthropic. Each test constructs its own throwaway
token file and its own scrubbed environment (`env -i` plus an explicit
allowlist of vars), so a developer's real credentials never leak into the
test process's assertions, and the fake token values used here are
obviously-fake (`fake-...-token`) so a failing assertion's diff can't be
mistaken for a real secret.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVE_SCRIPT = REPO_ROOT / "scripts" / "lib" / "resolve-claude-token.sh"


def run_resolve(
    *,
    env: dict[str, str],
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Source resolve-claude-token.sh in a scrubbed shell, call
    resolve_claude_token, and print the resulting state on stdout in a
    fixed, greppable shape so tests can assert on it without caring about
    bash's own quoting.
    """
    script = f"""
    set -euo pipefail
    source {RESOLVE_SCRIPT!s}
    resolve_claude_token
    printf 'OAUTH_TOKEN=[%s]\\n' "${{CLAUDE_CODE_OAUTH_TOKEN:-<unset>}}"
    printf 'API_KEY=[%s]\\n' "${{ANTHROPIC_API_KEY:-<unset>}}"
    """
    # Minimal, explicit environment: PATH (need `cat`, `bash` builtins work
    # without it but keep it for portability) and HOME are the only
    # ambient values we let through; everything else — including any real
    # token in the *actual* developer environment — is deliberately absent
    # unless a test opts it in via `env`.
    base_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    full_env = {**base_env, **env}
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def parse_output(stdout: str) -> dict[str, str]:
    result = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key] = value.strip("[]")
    return result


class TestPrecedence:
    def test_env_var_wins_over_token_file(self, tmp_path: Path) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("fake-file-token-should-not-be-used\n")

        proc = run_resolve(
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
                "CLAUDE_CODE_OAUTH_TOKEN": "fake-env-token-wins",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-env-token-wins"

    def test_token_file_used_when_env_var_unset(self, tmp_path: Path) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("fake-file-token-abc123\n")

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-file-token-abc123"

    def test_empty_env_var_falls_through_to_token_file(self, tmp_path: Path) -> None:
        """An exported-but-empty CLAUDE_CODE_OAUTH_TOKEN="" must not be
        treated as "set and wins" — it should fall through to the file,
        matching how Harbor itself drops empty values before forwarding
        them into the container (claude_code.py: `env = {k: v for k, v in
        env.items() if v}`)."""
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("fake-file-token-fallback\n")

        proc = run_resolve(
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
                "CLAUDE_CODE_OAUTH_TOKEN": "",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-file-token-fallback"

    def test_default_token_file_path_is_home_dot_anthropic(
        self, tmp_path: Path
    ) -> None:
        """With $AWS_BENCH_CLAUDE_TOKEN_FILE unset, the default must be
        exactly $HOME/.anthropic (the file `claude setup-token` writes)."""
        (tmp_path / ".anthropic").write_text("fake-default-path-token\n")

        proc = run_resolve(env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-default-path-token"

    def test_whitespace_in_token_file_is_trimmed(self, tmp_path: Path) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("  fake-token-with-padding  \n\n")

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-token-with-padding"


class TestMissingFile:
    def test_missing_token_file_leaves_oauth_token_unset(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"
        assert not missing.exists()

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(missing)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "<unset>"

    def test_missing_token_file_does_not_error(self, tmp_path: Path) -> None:
        """resolve_claude_token must return success (not abort the caller's
        `set -e` script) when there is simply no token available yet —
        that's a legitimate state (ANTHROPIC_API_KEY-only auth)."""
        missing = tmp_path / "does-not-exist"

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(missing)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0
        assert "error" not in proc.stderr.lower()

    def test_empty_token_file_leaves_oauth_token_unset(self, tmp_path: Path) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("")

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "<unset>"

    def test_whitespace_only_token_file_leaves_oauth_token_unset(
        self, tmp_path: Path
    ) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("   \n\n  ")

        proc = run_resolve(
            env={"AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file)},
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "<unset>"


class TestAnthropicApiKeyKeepsWorking:
    def test_api_key_untouched_when_no_oauth_token_available(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"

        proc = run_resolve(
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(missing),
                "ANTHROPIC_API_KEY": "fake-api-key-should-pass-through",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "<unset>"
        assert parsed["API_KEY"] == "fake-api-key-should-pass-through"

    def test_api_key_untouched_even_when_oauth_token_resolves(
        self, tmp_path: Path
    ) -> None:
        """Both can coexist — the script never clears ANTHROPIC_API_KEY,
        matching gates/RECON.md: "both API-key and OAuth-token can coexist —
        Harbor doesn't arbitrate, the `claude` binary does.\""""
        token_file = tmp_path / "anthropic-token"
        token_file.write_text("fake-file-token\n")

        proc = run_resolve(
            env={
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
                "ANTHROPIC_API_KEY": "fake-api-key-still-here",
            },
            tmp_path=tmp_path,
        )

        assert proc.returncode == 0, proc.stderr
        parsed = parse_output(proc.stdout)
        assert parsed["OAUTH_TOKEN"] == "fake-file-token"
        assert parsed["API_KEY"] == "fake-api-key-still-here"


class TestNoTokenLeakageIntoLogs:
    """resolve_claude_token must never print the token value itself —
    only run-bench.sh's own controlled, non-secret status lines should
    appear on stdout/stderr."""

    @pytest.mark.parametrize(
        "fake_token",
        [
            "fake-secret-should-never-appear-in-logs",
            "sk-ant-oat01-totally-fake-oauth-token-value",
        ],
    )
    def test_sourcing_and_calling_resolve_emits_nothing(
        self, tmp_path: Path, fake_token: str
    ) -> None:
        token_file = tmp_path / "anthropic-token"
        token_file.write_text(fake_token + "\n")

        script = f"""
        set -euo pipefail
        source {RESOLVE_SCRIPT!s}
        resolve_claude_token
        """
        proc = subprocess.run(
            ["bash", "-c", script],
            cwd=REPO_ROOT,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(tmp_path),
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0, proc.stderr
        assert fake_token not in proc.stdout
        assert fake_token not in proc.stderr
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_sourcing_with_xtrace_still_does_not_print_token(
        self, tmp_path: Path
    ) -> None:
        """Even under `set -x` (bash command tracing) — the closest thing
        to an accidental debug-log leak — the token value must not appear.
        The function reads the file into a local variable and exports it;
        it never echoes/printfs the token itself. `set -x` does echo
        command *arguments* as they're executed, so `export
        CLAUDE_CODE_OAUTH_TOKEN=<token>` would appear in an xtrace if the
        assignment were written as a literal — this test guards against
        that regression."""
        fake_token = "fake-xtrace-guard-token-value"
        token_file = tmp_path / "anthropic-token"
        token_file.write_text(fake_token + "\n")

        script = f"""
        set -euo pipefail
        source {RESOLVE_SCRIPT!s}
        set -x
        resolve_claude_token
        set +x
        """
        proc = subprocess.run(
            ["bash", "-c", script],
            cwd=REPO_ROOT,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(tmp_path),
                "AWS_BENCH_CLAUDE_TOKEN_FILE": str(token_file),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0, proc.stderr
        # xtrace with variable expansion would show `token=fake-...` or
        # `export CLAUDE_CODE_OAUTH_TOKEN=fake-...` if the script leaked
        # it; assert the raw value is absent from the trace on stderr.
        assert fake_token not in proc.stderr
        assert fake_token not in proc.stdout
