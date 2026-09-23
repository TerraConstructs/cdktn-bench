"""Self-test for the Phase-2 exit-criterion gate (gates/oracle_falsifiability.py).

Runs the REAL gate (`check_arm`, not a mock) against the toy spec's
hand-authored reference solution and its broken fixtures, and requires reward
1.0 and 0.0 respectively. A gate that prepares its sandbox wrongly — the arm
workspace landing anywhere but the sandbox root, where the patched
tests/static_tiers.sh expects it — makes no authored solve.sh reachable and
would otherwise "pass" forever through the NOT_AUTHORED escape hatch.

hcl_raw is the arm exercised because it needs neither `npm ci` nor a cdktn
synth. Requires terraform + jq on PATH and network the first time `terraform
init` fetches the `hashicorp/aws` provider (the same host-toolchain assumption
as `make falsifiability`). Skips rather than fails when they are missing,
matching oracles/tests' `toolcheck.find_tool` convention: this is a
developer-machine / CI-with-toolchain check, not a hard dependency of
`make test-gates`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# task_dir is re-exported from the gate rather than imported from
# generator/gen.py directly: gates/tests has no sys.path shim for generator/,
# and the gate already imports it.
from gates.oracle_falsifiability import (
    _is_stub,
    check_arm,
    task_dir,
    toolchain_failure_context,
)
from oracles.tests.toolcheck import find_tool

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOY_SPEC = REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml"

requires_hcl_raw_toolchain = pytest.mark.skipif(
    find_tool("terraform") is None or find_tool("jq") is None,
    reason="terraform and/or jq not found on PATH -- see toolcheck.find_tool",
)


def _load_toy_spec():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "generator"))
    from spec_model import load_spec  # noqa: PLC0415

    return load_spec(TOY_SPEC)


@requires_hcl_raw_toolchain
def test_hcl_raw_good_solution_scores_reward_1() -> None:
    """A correct, hand-authored solve.sh must reach reward 1.0 through the
    gate's REAL sandbox-preparation path, not an inert NOT_AUTHORED report.
    `_run_solve` must copy `environment/<ARM_WORKSPACE_SUBDIR[arm]>` onto the
    sandbox root, not the whole `environment/` dir; copying the whole dir fails
    here with reward 0.0 (terraform finds no .tf files where it `cd`s)."""
    spec = _load_toy_spec()
    # Resolved through the generator, not a hardcoded tasks/anchor path:
    # generator/shards.py decides which shard a task lives under, so a
    # literal path here would silently stop finding the file at shard_count > 1.
    solve_sh = task_dir(spec, "hcl_raw") / "solution" / "solve.sh"
    assert not _is_stub(solve_sh), "toy spec's hcl_raw solution/solve.sh must be authored for this test to mean anything"

    results = check_arm(spec, "hcl_raw")
    good = results[0]
    assert good.label == "hcl_raw/solution/solve.sh"
    assert good.reward == 1.0, f"expected reward 1.0, got {good.reward!r} -- detail:\n{good.detail}"
    assert good.ok


@requires_hcl_raw_toolchain
def test_hcl_raw_broken_fixtures_score_reward_0() -> None:
    """Every declared catch's solution/broken/<catch>/solve.sh must score 0.0 --
    the falsifiability half of the same gate. Same sandbox path as the
    good-solution test above, so a gate that always reports 1.0 regardless of
    the artifact fails here even when that test still passes."""
    spec = _load_toy_spec()
    results = check_arm(spec, "hcl_raw")
    broken = [r for r in results if "/broken/" in r.label]
    assert broken, "expected at least one solution/broken/<catch>/ result"
    for r in broken:
        assert r.reward == 0.0, f"{r.label}: expected reward 0.0, got {r.reward!r} -- detail:\n{r.detail}"
        assert r.ok


class TestLiveFamilyVerdict:
    """`apply_live_family_verdict` grades the two tiers this gate cannot run.

    "live" and "teardown" share one rule and must keep sharing it: the host has
    neither a real AWS call nor a real destroy, so the only falsifying evidence
    either tier can offer is a static reward that stayed 1.0 plus a marker the
    fixture earned mechanically. A verdict that accepted a missing marker would
    let a fixture assert its own tier in a comment.
    """

    @staticmethod
    def _run(detail: str, reward: float | None = 1.0):
        from gates.oracle_falsifiability import RunResult  # noqa: PLC0415

        return RunResult("arm/solution/broken/c/solve.sh", reward, True, detail)

    @pytest.mark.parametrize("tier", ["live", "teardown"])
    def test_marker_and_reward_1_is_the_only_pass(self, tier: str) -> None:
        from gates.oracle_falsifiability import (  # noqa: PLC0415
            LIVE_ONLY_CONFIRMED_MARKER,
            apply_live_family_verdict,
        )

        ok = apply_live_family_verdict(self._run(f"{LIVE_ONLY_CONFIRMED_MARKER} earned"), tier)
        assert ok.ok

    @pytest.mark.parametrize("tier", ["live", "teardown"])
    def test_missing_marker_fails_and_says_why(self, tier: str) -> None:
        from gates.oracle_falsifiability import (  # noqa: PLC0415
            LIVE_ONLY_CONFIRMED_MARKER,
            apply_live_family_verdict,
        )

        bad = apply_live_family_verdict(self._run("plan ran, nothing confirmed"), tier)
        assert not bad.ok
        assert LIVE_ONLY_CONFIRMED_MARKER in bad.detail
        assert tier in bad.detail

    @pytest.mark.parametrize("tier", ["live", "teardown"])
    def test_a_static_tier_that_scored_it_0_is_not_a_pass(self, tier: str) -> None:
        from gates.oracle_falsifiability import (  # noqa: PLC0415
            LIVE_ONLY_CONFIRMED_MARKER,
            apply_live_family_verdict,
        )

        bad = apply_live_family_verdict(
            self._run(f"{LIVE_ONLY_CONFIRMED_MARKER}", reward=0.0), tier
        )
        assert not bad.ok


def test_the_two_unrunnable_tiers_are_the_declared_family() -> None:
    """Widening this tuple changes which catches the gate stops grading
    statically, so it is pinned rather than left to a reader's inference."""
    from gates.oracle_falsifiability import LIVE_FAMILY_TIERS  # noqa: PLC0415

    assert LIVE_FAMILY_TIERS == ("live", "teardown")


class TestToolchainFailureContext:
    """A `<LABEL> FAILED` row's own explanation. One shell command carries
    `terraform init && validate && plan`, so the label cannot say whether the
    provider refused the agent's value (a real tier-0 catch) or `init` could not
    resolve a module (a run that proves nothing) -- these lines can."""

    PROVIDER_REFUSAL = (
        "== plan: terraform init && terraform validate && terraform plan ==\n"
        "Initializing modules...\n"
        "Error: expected retention_in_days to be one of [1 3 5], got 10\n"
        "  with module.processor.aws_cloudwatch_log_group.lambda[0],\n"
        "PLAN FAILED\n"
    )
    UNRESOLVED_MODULE = (
        "== plan: terraform init && terraform validate && terraform plan ==\n"
        "Error: Failed to query available provider packages\n"
        "PLAN FAILED\n"
    )

    def test_a_graded_run_gets_no_context(self) -> None:
        assert toolchain_failure_context(
            "== summary: tier0_pass=0 tier1_status=PASS ==\n"
        ) == []

    def test_the_provider_refusal_is_quoted(self) -> None:
        lines = toolchain_failure_context(self.PROVIDER_REFUSAL)
        assert any("retention_in_days" in ln for ln in lines)

    def test_an_init_failure_is_distinguishable_from_it(self) -> None:
        lines = toolchain_failure_context(self.UNRESOLVED_MODULE)
        assert any("provider packages" in ln for ln in lines)
        assert not any("retention_in_days" in ln for ln in lines)

    def test_it_never_returns_more_than_asked(self) -> None:
        noisy = "\n".join(["Error: %d" % i for i in range(50)]) + "\nPLAN FAILED\n"
        assert len(toolchain_failure_context(noisy, keep=3)) == 3
