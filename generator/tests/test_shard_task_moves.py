"""A task that changes shard keeps its hand-authored files.

Raising generator/shards.toml's shard_count moves tasks between tasks/<shard>/
directories, and generate() sweeps the copy left behind. `solution/**/solve.sh`
and a hand-authored `tests/live_check.py` are the only destructive-safe paths
in a task dir (specs/SCHEMA.md §8.2 point 8), so the sweep must carry them to
the new shard rather than delete them: turning the knob must never cost an
author their work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import gen
import shards
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_PATH = REPO_ROOT / "specs" / "named-resource-replacement.yaml"


@pytest.fixture
def moved_task(tmp_path, monkeypatch):
    """A mutating spec's awscdk task sitting under the shard it occupied at
    N=1, with the knob now at N=4, in a throwaway tasks/ tree."""
    monkeypatch.setattr(shards, "shard_count", lambda: 4)
    tasks = tmp_path / "tasks"
    monkeypatch.setattr(gen, "TASKS_DIR", tasks)
    spec = load_spec(SPEC_PATH)
    assert spec.verifier.live_check.concurrency_mode == "mutating"
    stale = tasks / "anchor" / f"{spec.id}-awscdk"
    assert gen.task_dir(spec, "awscdk") != stale, "N=4 must move this task"
    for rel, body in {
        "solution/solve.sh": "#!/usr/bin/env bash\nhand-authored reference\n",
        "solution/broken/ingress-widened-to-the-internet/solve.sh": "#!/usr/bin/env bash\nfixture\n",
        f"solution/broken/{gen.SEED_UNCHANGED_FIXTURE}/solve.sh": "#!/usr/bin/env bash\ngenerated\n",
        "steps/01-first/solution/solve.sh": "#!/usr/bin/env bash\nstep fixture\n",
        "tests/live_check.py": "# hand-authored live check\n",
        "tests/static_tiers.sh": "# generated\n",
        "task.toml": '[metadata]\nid = "11111111-2222-4333-8444-555555555555"\n',
    }.items():
        path = stale / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return spec, stale, tasks


def test_hand_authored_files_move_to_the_new_shard(moved_task):
    spec, stale, _tasks = moved_task
    gen.sweep_stale_task_dirs(spec)

    assert not stale.exists(), "the copy on the old shard must not survive"
    new = gen.task_dir(spec, "awscdk")
    assert (new / "solution/solve.sh").read_text() == (
        "#!/usr/bin/env bash\nhand-authored reference\n"
    )
    assert (new / "solution/broken/ingress-widened-to-the-internet/solve.sh").exists()
    assert (new / "steps/01-first/solution/solve.sh").exists()
    assert (new / "tests/live_check.py").exists()


def test_generator_owned_files_are_not_carried_over(moved_task):
    """Only the destructive-safe set moves; everything else is rewritten by the
    next generate_arm, and the seed-unchanged fixture is generator-owned
    (specs/SCHEMA.md §2.7) so carrying it would preserve a stale copy."""
    spec, _stale, _tasks = moved_task
    gen.sweep_stale_task_dirs(spec)
    new = gen.task_dir(spec, "awscdk")
    assert not (new / f"solution/broken/{gen.SEED_UNCHANGED_FIXTURE}/solve.sh").exists()
    assert not (new / "tests/static_tiers.sh").exists()


def test_the_emptied_shard_directory_is_removed(moved_task):
    """A tasks/<shard>/ with no tasks left and no scenarios/<shard>/ beside it
    is the path-vs-field disagreement DECISIONS.md Amendment 33 forbids."""
    spec, _stale, tasks = moved_task
    gen.sweep_stale_task_dirs(spec)
    assert not (tasks / "anchor").exists()


def test_the_task_identity_travels_with_the_move(moved_task):
    """generate_arm reuses [metadata].id only from a task.toml at the new
    path, so the sweep carries the old one across; a shard move must not
    re-mint the identity of a task whose content did not change."""
    spec, _stale, _tasks = moved_task
    gen.sweep_stale_task_dirs(spec)
    new = gen.task_dir(spec, "awscdk")
    assert gen.existing_task_uuid(new / "task.toml") == "11111111-2222-4333-8444-555555555555"
