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
from gates.oracle_falsifiability import _is_stub, check_arm, task_dir
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
