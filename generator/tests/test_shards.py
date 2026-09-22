"""The shard rule (generator/shards.py).

A shard is an AWS member account (DECISIONS.md Amendment 33), so the two
properties pinned here are the ones an operator's bill and wall-clock depend
on: the assignment is a pure function of (spec.id, arm) — never of iteration
order, mtimes, or generation order — and at N >= 4 one mutating spec's three
shipped arms never share a shard, which is the whole reason for extra accounts.

Also pins the un-sharded default: at shard_count = 1 everything is "anchor" and
the materializer is a no-op.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

import gen
import shards
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = REPO_ROOT / "specs"
# The arms that actually produce a task. `ARM_ORDER` is wider: it is the index
# domain of the assignment, and it carries an arm whose image does not exist yet
# (gen.ARMS_PENDING_IMAGE), which generates nothing to place on an account. The
# distinctness property below is a property of placed tasks, so it is read off
# the arms that have one.
ARMS = tuple(a for a in shards.ARM_ORDER if a not in gen.ARMS_PENDING_IMAGE)


@dataclass
class _LiveCheck:
    concurrency_mode: str | None


@dataclass
class _Verifier:
    live_check: _LiveCheck


@dataclass
class _FakeSpec:
    """The only two fields shard_for reads."""

    id: str
    verifier: _Verifier


def fake_spec(spec_id: str, mode: str | None) -> _FakeSpec:
    return _FakeSpec(id=spec_id, verifier=_Verifier(live_check=_LiveCheck(mode)))


@pytest.fixture
def at_n(monkeypatch):
    """Run the assignment rule at an arbitrary shard count without editing the
    committed knob."""

    def _set(n: int):
        monkeypatch.setattr(shards, "shard_count", lambda: n)
        return n

    return _set


# --- the committed default --------------------------------------------------


def test_committed_shard_count_is_a_positive_int():
    n = shards.shard_count()
    assert isinstance(n, int) and n >= 1
    raw = tomllib.loads(shards.SHARDS_CONFIG_PATH.read_text())
    assert set(raw) == {"shard_count"}, (
        "generator/shards.toml is the ONE shard knob — a second key here is a "
        "second place to look"
    )


def test_shard_zero_keeps_the_existing_scenario_name():
    assert shards.shard_name(0) == "anchor"
    assert shards.shard_name(1) == "anchor-1"
    assert shards.shard_name(7) == "anchor-7"


def test_n_one_maps_everything_to_anchor(at_n):
    at_n(1)
    for mode in (None, "read-only", "mutating"):
        spec = fake_spec("apigw-redeploy", mode)
        for arm in ARMS:
            assert shards.shard_for(spec, arm) == "anchor"


# --- the assignment rule ----------------------------------------------------


def test_read_only_specs_stay_on_shard_zero(at_n):
    at_n(6)
    for mode in (None, "read-only"):
        spec = fake_spec("ecs-swappiness", mode)
        for arm in ARMS:
            assert shards.shard_for(spec, arm) == "anchor"


def test_mutating_arms_get_distinct_shards_once_there_are_enough(at_n):
    """As many distinct accounts as there are arms, or as many as exist — a
    spec's arms never share one while a free shard is left. Written against the
    arm COUNT rather than a literal, because enabling a fourth arm raises the
    N at which the property first holds (shards.shard_for's docstring)."""
    mutating = [s for s in real_specs() if _is_mutating(s)]
    assert mutating, "no mutating spec on disk — this test would prove nothing"
    for n in (4, 5, 8):
        at_n(n)
        for spec in mutating:
            assigned = [shards.shard_for(spec, arm) for arm in ARMS]
            assert len(set(assigned)) == min(len(ARMS), n - 1), (spec.id, n, assigned)
            assert "anchor" not in assigned, (spec.id, n, assigned)


def test_mutating_arms_spread_as_evenly_as_possible_below_n_four(at_n):
    spec = fake_spec("apigw-redeploy", "mutating")
    at_n(2)
    assert {shards.shard_for(spec, arm) for arm in ARMS} == {"anchor-1"}
    at_n(3)
    # Two mutating shards and more arms than that: the arms are dealt round
    # robin, so no shard carries two more than another — the best any
    # assignment can do.
    assigned = [shards.shard_for(spec, arm) for arm in ARMS]
    assert set(assigned) == {"anchor-1", "anchor-2"}
    counts = sorted(assigned.count(s) for s in set(assigned))
    assert counts[-1] - counts[0] <= 1, counts


def test_assignment_is_deterministic(at_n):
    at_n(4)
    spec = fake_spec("named-resource-replacement", "mutating")
    first = [shards.shard_for(spec, arm) for arm in ARMS]
    for _ in range(5):
        # A fresh, equal spec object must land identically: the rule may read
        # spec.id and the arm, and nothing else.
        assert [
            shards.shard_for(fake_spec("named-resource-replacement", "mutating"), arm)
            for arm in ARMS
        ] == first


def test_unknown_arm_is_refused(at_n):
    at_n(4)
    with pytest.raises(ValueError):
        shards.shard_for(fake_spec("apigw-redeploy", "mutating"), "pulumi")


# --- materializer -----------------------------------------------------------


def test_check_passes_on_the_committed_tree():
    assert shards.check() == []


def test_write_is_a_no_op_at_n_one(at_n):
    if shards.shard_count() != 1:
        pytest.skip("committed shard_count != 1; --write is not a no-op there")
    at_n(1)
    assert shards.write() == []


def test_template_is_tracked_files_only():
    files = shards.template_files()
    assert "scenario.toml" in files
    assert "README.md" in files
    assert not [f for f in files if "node_modules" in f or "cdk.out" in f or "dist/" in f]


def test_shard_copy_differs_from_the_template_in_its_name_only():
    tree = shards.expected_shard_tree(3)
    template_root = shards.SCENARIOS_DIR / shards.SCENARIO_BASE
    renamed = {
        rel
        for rel, body in tree.items()
        if body != (template_root / rel).read_bytes()
    }
    assert renamed == {"scenario.toml", "README.md"}
    assert b'name = "anchor-3"' in tree["scenario.toml"]
    assert tree["README.md"].startswith(b"# scenarios/anchor-3\n")


@pytest.fixture
def sandbox_tree(tmp_path, monkeypatch):
    """A throwaway copy of scenarios/ + local-registry.json to materialize into.

    The real scenarios/anchor is hashed against an already-provisioned AWS
    account, so no test may write beside it.
    """
    scenarios = tmp_path / "scenarios"
    for rel in shards.template_files():
        src = shards.SCENARIOS_DIR / shards.SCENARIO_BASE / rel
        dest = scenarios / shards.SCENARIO_BASE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    registry = tmp_path / "local-registry.json"
    registry.write_text(shards.LOCAL_REGISTRY_PATH.read_text())
    monkeypatch.setattr(shards, "SCENARIOS_DIR", scenarios)
    monkeypatch.setattr(shards, "LOCAL_REGISTRY_PATH", registry)
    return tmp_path


def test_write_then_check_round_trips_at_n_three(sandbox_tree, at_n):
    at_n(3)
    assert shards.write()
    assert shards.check_scenarios() == []
    assert (sandbox_tree / "scenarios" / "anchor-1" / "scenario.toml").exists()
    assert (sandbox_tree / "scenarios" / "anchor-2" / "scenario.toml").exists()
    registry = json.loads((sandbox_tree / "local-registry.json").read_text())
    dataset = next(d for d in registry if d["name"] == shards.REGISTRY_DATASET_NAME)
    assert dataset["scenarios"] == [
        {"name": "anchor", "path": "scenarios/anchor"},
        {"name": "anchor-1", "path": "scenarios/anchor-1"},
        {"name": "anchor-2", "path": "scenarios/anchor-2"},
    ]
    # A second run produces the same tree: `make shards` is idempotent, so
    # running it cannot manufacture a diff.
    shards.write()
    assert shards.check_scenarios() == []


def test_a_hand_edited_shard_is_drift(sandbox_tree, at_n):
    at_n(2)
    shards.write()
    (sandbox_tree / "scenarios" / "anchor-1" / "scenario.toml").write_text("tampered\n")
    assert any("differs from" in p for p in shards.check_scenarios())


def test_lowering_the_count_removes_the_extra_shards(sandbox_tree, at_n):
    at_n(3)
    shards.write()
    at_n(1)
    assert shards.check_scenarios(), "shards left over from a higher count must be drift"
    shards.write()
    assert shards.check_scenarios() == []
    assert not list((sandbox_tree / "scenarios").glob("anchor-*"))


# --- on-disk layout ---------------------------------------------------------


def test_every_generated_task_lives_under_the_shard_its_task_toml_names():
    """The path and the declared scenario_id are two encodings of one fact;
    aws-bench-datasets' registry generator reads the path and aws-bench reads
    the field, so a disagreement binds the task to an undeployed scenario."""
    tasks_dir = REPO_ROOT / "tasks"
    checked = 0
    for task_toml in sorted(tasks_dir.glob("*/*/task.toml")):
        declared = tomllib.loads(task_toml.read_text())["scenario"]["scenario_id"]
        assert declared == task_toml.parent.parent.name, task_toml
        checked += 1
    assert checked > 0


def real_specs():
    return [load_spec(p) for p in sorted(SPECS_DIR.glob("*.yaml")) if p.name != "split.yaml"]


def _is_mutating(spec) -> bool:
    return spec.verifier.live_check.concurrency_mode == "mutating"


def test_a_stale_tasks_tree_is_drift(at_n):
    """Changing the knob without `make gen-all` must be a red build: `make
    shards` never touches tasks/, and task.toml's scenario_id keeps agreeing
    with its own (unmoved) parent directory, so nothing else notices. Checks
    the committed tree against a shard count it was not generated for."""
    committed = shards.shard_count()
    at_n(1 if committed > 1 else 4)
    problems = shards.check_tasks()
    assert problems, f"tasks/ generated at N={committed} must be stale at another N"
    assert all("make gen-all" in p for p in problems)
