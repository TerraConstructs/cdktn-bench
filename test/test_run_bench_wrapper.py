"""Unit tests for scripts/run-bench.sh's argument assembly and model/token
wiring, exercised entirely via --dry-run (AWS_BENCH_DRY_RUN=1): the script
prints the argv it would pass to `uv run cdktn-bench` and a
CLAUDE_CODE_OAUTH_TOKEN_SET flag, then exits — no `uv`, `cdktn-bench`, AWS
account, or Claude Code call is ever touched by these tests.

The runner was flipped `aws-bench` -> `cdktn-bench` on 2026-08-20
(DECISIONS.md Amendment 27): the CLI is a strict superset (same `start`
function object, same flags), and only the trial factory differs —
`cdktn_bench.trial.CdktnTrial.create` sends a stepless task down the
untouched upstream single-step path and a `[[steps]]` task down
`CdktnMultiStepTrial`. `test_exec_target_is_cdktn_bench` below pins the flip
so a silent revert to `aws-bench` (which refuses every multi-step task with
NotImplementedError) fails here rather than at the next live run.
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
    reach `uv run cdktn-bench run` unchanged."""

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


class TestBudgetWiring:
    """MAX_ITERS/MAX_TOKENS (docs/iac-abstraction-aws-bench-plan.md Phase 2
    item 2 / prereg §4) — exercised entirely via --dry-run, same as every
    other class in this file. budget.json is a real-run-only side effect
    (see run-bench.sh's own comment) so it is deliberately NOT asserted on
    here; only the dry-run-printed values and the injected --ak/--ae argv
    are.
    """

    def test_max_iters_defaults_to_100_and_injects_ak_max_turns(
        self, tmp_path: Path
    ) -> None:
        # Default raised 8 -> 100 (Amendment 22): --max-turns counts agent
        # steps, not feedback cycles, and live scenarios need the headroom.
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "MAX_ITERS=100" in proc.stdout
        assert "--ak max_turns=100" in proc.stdout

    def test_max_iters_env_var_overrides_default(self, tmp_path: Path) -> None:
        proc = run_dry([], env={"MAX_ITERS": "3"}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "MAX_ITERS=3" in proc.stdout
        assert "--ak max_turns=3" in proc.stdout
        assert "max_turns=100" not in proc.stdout

    def test_max_iters_flag_overrides_env_var(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--max-iters", "5"], env={"MAX_ITERS": "3"}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert "MAX_ITERS=5" in proc.stdout
        assert "--ak max_turns=5" in proc.stdout

    def test_max_iters_zero_skips_injection(self, tmp_path: Path) -> None:
        proc = run_dry(["--max-iters", "0"], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "MAX_ITERS=0" in proc.stdout
        assert "--ak" not in proc.stdout
        assert "max_turns" not in proc.stdout

    def test_max_iters_injected_before_user_override_so_user_wins(
        self, tmp_path: Path
    ) -> None:
        # harbor.cli.utils.parse_kwargs builds its dict by iterating the
        # --ak list in argv order and overwriting on duplicate keys -- the
        # caller's own explicit --ak max_turns=... (passed after `--`) must
        # therefore appear AFTER the script's own injected default in argv.
        proc = run_dry(
            ["--", "--ak", "max_turns=20"], env={}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        argv_line = proc.stdout.splitlines()[0]
        assert argv_line.index("max_turns=100") < argv_line.index("max_turns=20")

    def test_max_tokens_unset_by_default(self, tmp_path: Path) -> None:
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "MAX_TOKENS=\n" in proc.stdout
        assert "CDKTN_BENCH_MAX_TOKENS" not in proc.stdout

    def test_max_tokens_flag_sets_ae_and_dry_run_report(
        self, tmp_path: Path
    ) -> None:
        proc = run_dry(
            ["--max-tokens", "150000"], env={}, tmp_path=tmp_path
        )

        assert proc.returncode == 0, proc.stderr
        assert "MAX_TOKENS=150000" in proc.stdout
        assert "--ae CDKTN_BENCH_MAX_TOKENS=150000" in proc.stdout

    def test_max_tokens_env_var_works_too(self, tmp_path: Path) -> None:
        proc = run_dry([], env={"MAX_TOKENS": "80000"}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert "MAX_TOKENS=80000" in proc.stdout
        assert "--ae CDKTN_BENCH_MAX_TOKENS=80000" in proc.stdout


class TestHoldoutEquippingGuard:
    """Runtime CLI counterpart of generator/gen.py::enforce_no_holdout_equipping
    (2026-08-06 fix: "the holdout guard misses ... harbor's real knobs are
    --skill/--mcp-config ... invisible to enforce_no_holdout_equipping").
    Exercised entirely via --dry-run -- the refusal (or lack of one) must
    be decidable before any real trial work happens. Slower than the other
    classes in this file (each case that reaches the guard's `uv run
    python -c` spends real subprocess time resolving specs/split.yaml),
    so run_dry's own 10s timeout is generous enough to absorb it.
    """

    def test_refuses_skill_flag_against_a_holdout_scenario(self, tmp_path: Path) -> None:
        # specs/split.yaml (checked in): sfn-jsonata -> holdout.
        proc = run_dry(
            ["--path", "tasks/anchor/sfn-jsonata-awscdk", "--", "--skill", "./my-skill"],
            env={},
            tmp_path=tmp_path,
        )
        assert proc.returncode == 1
        assert "REFUSED" in proc.stderr
        assert "sfn-jsonata" in proc.stderr
        assert "HOLDOUT" in proc.stderr

    def test_refuses_mcp_config_flag_against_a_holdout_scenario(self, tmp_path: Path) -> None:
        proc = run_dry(
            ["--path", "tasks/anchor/sfn-jsonata-awscdk", "--", "--mcp-config", "./mcp.json"],
            env={},
            tmp_path=tmp_path,
        )
        assert proc.returncode == 1
        assert "REFUSED" in proc.stderr

    def test_allows_skill_flag_against_a_train_scenario(self, tmp_path: Path) -> None:
        # specs/split.yaml (checked in): ecs-swappiness -> train.
        proc = run_dry(
            ["--path", "tasks/anchor/ecs-swappiness-awscdk", "--", "--skill", "./my-skill"],
            env={},
            tmp_path=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        assert "--skill ./my-skill" in proc.stdout

    def test_holdout_scenario_with_no_equipping_flags_is_unaffected(
        self, tmp_path: Path
    ) -> None:
        proc = run_dry(
            ["--path", "tasks/anchor/sfn-jsonata-awscdk"], env={}, tmp_path=tmp_path
        )
        assert proc.returncode == 0, proc.stderr

    def test_unclassified_path_does_not_refuse(self, tmp_path: Path) -> None:
        # A path that doesn't resolve to any known spec id at all (no
        # entry in specs/split.yaml) must not be treated as an implicit
        # holdout -- see generator/split.py::spec_group's own "None is
        # 'not yet classified', never an implicit default" contract.
        proc = run_dry(
            ["--path", "tasks/anchor/not-a-real-scenario-awscdk", "--", "--skill", "./s"],
            env={},
            tmp_path=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr

    def test_no_path_and_no_dataset_does_not_crash_on_empty_candidate_array(
        self, tmp_path: Path
    ) -> None:
        # Regression test (2026-08-06 fix round 2): with neither --path nor
        # -d/--dataset supplied, CANDIDATE_SPEC_IDS is legitimately empty
        # (the documented KNOWN LIMITATION above the guard -- this shape
        # cannot be statically narrowed to a scenario from argv alone).
        # Under bash 3.2's `set -u`, expanding "${CANDIDATE_SPEC_IDS[@]}" on
        # a genuinely empty array is an unbound-variable error unless the
        # loop is guarded by an explicit length check first. This must exit
        # 0 (documented can't-narrow-scenario behaviour), not crash with
        # "CANDIDATE_SPEC_IDS[@]: unbound variable".
        proc = run_dry(["--", "--skill", "./s"], env={}, tmp_path=tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert "unbound variable" not in proc.stderr
        assert "--skill ./s" in proc.stdout

    def test_registry_path_with_no_dataset_flag_and_no_path_does_not_crash(
        self, tmp_path: Path
    ) -> None:
        # Same shape via --registry-path (which does not populate DATASET
        # or TASK_PATH) combined with --skill.
        proc = run_dry(
            [
                "--",
                "--registry-path",
                "./local-registry.json",
                "--skill",
                "./s",
            ],
            env={},
            tmp_path=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        assert "unbound variable" not in proc.stderr


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

    def test_usage_advertises_the_default_the_code_actually_uses(
        self, tmp_path: Path
    ) -> None:
        """Doc-drift guard: `--help` said "Default: 8" for a week after
        DECISIONS.md Amendment 22 raised MAX_ITERS 8 -> 100, so an operator
        reading the usage text budgeted for the wrong cap. Ties the advertised
        default to the one `--dry-run` reports, so the two can't drift again.
        """
        help_proc = subprocess.run(
            ["bash", str(RUN_BENCH), "--help"],
            cwd=REPO_ROOT,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert help_proc.returncode == 0, help_proc.stderr

        dry = run_dry([], env={}, tmp_path=tmp_path)
        assert dry.returncode == 0, dry.stderr
        (default,) = [
            line.split("=", 1)[1]
            for line in dry.stdout.splitlines()
            if line.startswith("MAX_ITERS=")
        ]

        assert f"Default: {default}" in help_proc.stdout, (
            f"--help does not advertise the real MAX_ITERS default ({default})"
        )
        assert "Default: 8 (prereg §4)" not in help_proc.stdout


class TestExecTarget:
    """The runner must exec `cdktn-bench`, not `aws-bench`.

    Pinned because the difference is invisible for every task that exists
    today and fatal for the ones that don't: upstream's
    `AwsBenchTrial.create` raises `NotImplementedError("multi-step AWS tasks
    are not yet supported ...")` the moment a task.toml declares `[[steps]]`,
    so a silent revert to `aws-bench` would leave every single-step scenario
    passing and refuse `apigw-redeploy` (the only multi-step scenario)
    outright — at the start of a live, billed run.
    """

    def test_exec_target_is_cdktn_bench(self, tmp_path: Path) -> None:
        proc = run_dry([], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.startswith("uv run cdktn-bench run "), proc.stdout
        assert "uv run aws-bench" not in proc.stdout

    def test_flags_are_unchanged_by_the_flip(self, tmp_path: Path) -> None:
        """cdktn_bench/cli.py registers aws-bench's own `start` function
        object, so flag parity is total by construction -- assert the full
        default argv, not just the binary name."""
        proc = run_dry(["--yes", "-k", "2"], env={}, tmp_path=tmp_path)

        assert proc.returncode == 0, proc.stderr
        argv = proc.stdout.splitlines()[0]
        assert argv == (
            "uv run cdktn-bench run -a claude-code -m claude-sonnet-5 "
            "-o jobs/claude-sonnet-5 -k 2 --yes --ak max_turns=100"
        ), argv
