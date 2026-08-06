"""gates/tests/test_oracle_falsifiability.py -- self-test for the Phase-2
exit-criterion gate (gates/oracle_falsifiability.py), added alongside the
fix for benchmark-integrity finding F1 (2026-08-06):

    gates/oracle_falsifiability.py:95 _run_solve copied task/environment
    wholesale so the arm workspace landed at <sandbox>/workspace/ (or
    <sandbox>/app/) while the patched tests/static_tiers.sh expects it at
    the sandbox root -- NO authored solve.sh could ever reach reward 1.0;
    the gate only ever "passed" via its NOT_AUTHORED escape hatch.

This runs the REAL gate (`gates.oracle_falsifiability.check_arm`, not a
mock) against the toy spec's now hand-authored reference solution and
proves it scores reward 1.0 -- the gate's own regressions (e.g. someone
reverting `_run_solve` back to copying the whole `environment/` dir) turn
this test RED instead of staying silently green forever, which is exactly
what let F1 ship unnoticed the first time.

Requires the real per-arm toolchain on PATH (terraform + jq for hcl_raw --
deliberately the arm exercised here, since it needs neither `npm ci` nor
mock-STS/cdktn synth, keeping this test's runtime and dependency footprint
the smallest of the three arms) and network the first time `terraform
init` needs to download the `hashicorp/aws` provider (same host-toolchain
assumption as `make falsifiability` / `make check-paths` --
gates/oracle_falsifiability.py's own module docstring). Skips (does not
fail) when the toolchain isn't available, matching oracles/tests'
`toolcheck.find_tool` convention -- this is a developer-machine /
CI-with-toolchain check, not a hard dependency of `make test-gates`
everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gates.oracle_falsifiability import _is_stub, check_arm
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
    """Regression test for finding F1: a correct, hand-authored solve.sh
    must reach reward 1.0 through the gate's REAL sandbox-preparation code
    path, not just an inert NOT_AUTHORED report. If `_run_solve` ever again
    copies the whole `environment/` dir instead of
    `environment/<ARM_WORKSPACE_SUBDIR[arm]>` onto the sandbox root, this
    fails with reward 0.0 (terraform finds no .tf files at the root it
    `cd`s into)."""
    spec = _load_toy_spec()
    solve_sh = REPO_ROOT / "tasks" / "anchor" / "toy-ssm-parameter-hcl-raw" / "solution" / "solve.sh"
    assert not _is_stub(solve_sh), "toy spec's hcl_raw solution/solve.sh must be authored for this test to mean anything"

    results = check_arm(spec, "hcl_raw")
    good = results[0]
    assert good.label == "hcl_raw/solution/solve.sh"
    assert good.reward == 1.0, f"expected reward 1.0, got {good.reward!r} -- detail:\n{good.detail}"
    assert good.ok


@requires_hcl_raw_toolchain
def test_hcl_raw_broken_fixtures_score_reward_0() -> None:
    """Every declared catch's solution/broken/<catch>/solve.sh must score
    0.0 -- the falsifiability half of the same gate. Uses the same sandbox
    path as the good-solution test above, so a regression that broke ONE
    direction (e.g. a gate that always reports 1.0 regardless of the
    artifact) is caught by this test even if the other one somehow
    wasn't."""
    spec = _load_toy_spec()
    results = check_arm(spec, "hcl_raw")
    broken = [r for r in results if "/broken/" in r.label]
    assert broken, "expected at least one solution/broken/<catch>/ result"
    for r in broken:
        assert r.reward == 0.0, f"{r.label}: expected reward 0.0, got {r.reward!r} -- detail:\n{r.detail}"
        assert r.ok
