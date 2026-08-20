"""gates/tests/test_seed_unchanged_gate.py — the MANDATORY brownfield
do-nothing check inside gates/oracle_falsifiability.py (specs/SCHEMA.md §2.7,
DECISIONS.md Amendment 28 §5).

Why this needs its own test rather than relying on `make falsifiability`: the
gate's real run needs the arm toolchain (terraform/node/npm) and several
minutes, so it lives in `make ci`, not in `make check`. The two properties
below are pure control flow and belong in the offline floor —

  1. a `workspace_seed` spec whose `solution/broken/seed-unchanged/solve.sh` is
     MISSING is a hard FAIL, not a skip. Making it a skip would be the exact
     shape of the "NOT_AUTHORED reads as PASS" finding this repo already fixed
     once for check-paths: the one negative that can catch a
     rewards-doing-nothing scenario would silently stop running;
  2. a GREENFIELD spec produces no such row at all — the check must not invent
     an obligation for scenarios that have no seed to leave unchanged.

The verdict threshold itself (`reward < 1.0`) is exercised for real by
`make falsifiability SPEC=specs/named-resource-replacement.yaml`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT))

from gates.oracle_falsifiability import _check_seed_unchanged  # noqa: E402
from gen import SEED_UNCHANGED_FIXTURE, task_dir  # noqa: E402
from spec_model import load_spec  # noqa: E402

PILOT_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
GREENFIELD_SPEC = REPO_ROOT / "specs" / "ecs-swappiness.yaml"


def test_missing_fixture_is_a_hard_fail(tmp_path: Path) -> None:
    spec = load_spec(PILOT_SPEC)
    # A task dir that is real in every respect EXCEPT the do-nothing fixture.
    real = task_dir(spec, "hcl_raw")
    fake = tmp_path / real.name
    shutil.copytree(real, fake)
    shutil.rmtree(fake / "solution" / "broken" / SEED_UNCHANGED_FIXTURE)

    results = _check_seed_unchanged(spec, "hcl_raw", fake, None)
    assert len(results) == 1
    assert results[0].ok is False
    assert "MISSING" in results[0].detail
    assert SEED_UNCHANGED_FIXTURE in results[0].label


def test_greenfield_spec_produces_no_row() -> None:
    spec = load_spec(GREENFIELD_SPEC)
    assert not spec.is_brownfield()
    assert _check_seed_unchanged(spec, "hcl_raw", task_dir(spec, "hcl_raw"), None) == []


@pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
def test_the_pilot_ships_the_fixture_on_every_arm(arm: str) -> None:
    spec = load_spec(PILOT_SPEC)
    path = (
        task_dir(spec, arm) / "solution" / "broken" / SEED_UNCHANGED_FIXTURE / "solve.sh"
    )
    assert path.is_file()


def test_the_generic_extra_broken_loop_does_not_double_run_it() -> None:
    """The fixture already ran under its own dedicated, differently-worded
    check. Running it again in check_arm's extra-broken loop would double the
    slowest step in the gate and report the same fact under a vaguer label
    (and under a stricter `== 0.0` rule than Amendment 28 §5 states)."""
    source = (REPO_ROOT / "gates" / "oracle_falsifiability.py").read_text()
    assert "extra_dir.name == SEED_UNCHANGED_FIXTURE" in source


# ---------------------------------------------------------------------------
# 3. reward < 1.0 is NECESSARY BUT NOT SUFFICIENT
#
# `tests/static_tiers.sh` writes 0.0 for a broken TOOLCHAIN as well as for a
# rejected solution -- `TF-PLAN FAILED`, `MISSING ARTIFACT`, and the mock-STS
# `tf-plan-mock-sts-unavailable` bail-out, which that script itself labels
# "a run-invalidating test-infrastructure condition, NOT a bad solution".
#
# Accepting those 0.0s would let this gate report "the oracle rejects doing
# nothing" on a run where nothing was ever graded -- a vacuous pass in the one
# check whose entire purpose is to be un-fakeable. Observed for real: a batch
# `make falsifiability` run on 2026-08-20 produced `TF-PLAN FAILED` for the
# terraconstructs do-nothing fixture (mock-STS port contention between
# back-to-back fixtures) while the same fixture, run in isolation, failed
# honestly on `security-group-uses-the-new-team-prefixed-name`.
#
# These tests drive `_check_seed_unchanged` with `_run_solve` stubbed, so they
# stay in the offline floor (`make check`) rather than needing a toolchain.
# ---------------------------------------------------------------------------

GRADED_DETAIL = (
    "  FAIL [security-group-uses-the-new-team-prefixed-name]: "
    'op=eq expected="platform-..." resolved=["internal-..."]\n'
    "== summary: tier0_pass=0 tier1_status=PASS =="
)
UNGRADED_DETAIL = "TF-PLAN FAILED"


def _run_with_stub(monkeypatch, reward: float | None, detail: str, ok: bool = True):
    import gates.oracle_falsifiability as gof

    spec = load_spec(PILOT_SPEC)
    task = task_dir(spec, "terraconstructs")

    def fake_run_solve(_task, _arm, _solve, label, **_kw):
        return gof.RunResult(label, reward, ok, detail)

    monkeypatch.setattr(gof, "_run_solve", fake_run_solve)
    results = gof._check_seed_unchanged(spec, "terraconstructs", task, None)
    assert len(results) == 1
    return results[0]


def test_zero_reward_with_a_graded_artifact_passes(monkeypatch) -> None:
    """The honest shape: the toolchain ran, the tier-0 name assert rejected the
    unchanged seed. This is the verdict the gate exists to record."""
    assert _run_with_stub(monkeypatch, 0.0, GRADED_DETAIL).ok is True


def test_zero_reward_without_a_graded_artifact_fails(monkeypatch) -> None:
    """The vacuous shape: reward 0.0, but no tier-0 summary — the toolchain
    died before grading anything, so this run proves nothing either way. It
    must FAIL (unprovable ⇒ fail-closed), not silently bank a pass."""
    result = _run_with_stub(monkeypatch, 0.0, UNGRADED_DETAIL)
    assert result.ok is False
    assert "never produced a graded artifact" in result.detail
    assert "run-invalidating" in result.detail


def test_full_reward_still_fails_with_the_rewards_doing_nothing_message(
    monkeypatch,
) -> None:
    """The failure this whole fixture exists for: the change request is already
    satisfied by the seed, so doing nothing earns full marks."""
    result = _run_with_stub(monkeypatch, 1.0, GRADED_DETAIL)
    assert result.ok is False
    assert "rewards doing nothing" in result.detail
