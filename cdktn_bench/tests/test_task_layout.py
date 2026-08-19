"""The multi-step task-directory contract, pinned against a toy fixture.

``docs/design/multistep-trial-investigation.md`` §5 derives four generator rules
from one property of the runtime: **the task directory is never uploaded to the
agent container** — only ``environment/`` (as the Docker build context) and, at
verification time, ``tests/``. That is what makes step-2's prompt invisible
during step 1. The rules exist because there are exactly three places where a
step's material WOULD become visible early, and the generator (a separate
slice) has to avoid all three.

Nothing in Harbor or aws-bench enforces these rules; this is where they live
until the generator emits ``steps/`` for real. The fixture is hand-authored on
purpose — ``tasks/**`` is generator-owned (CLAUDE.md: "Hand-edit generated
tasks/** — never").
"""

from __future__ import annotations

from pathlib import Path

from aws_bench.dataset.task_config import AwsBenchTask
from harbor.models.task.paths import TaskPaths
from harbor.models.task.task import Task


def test_fixture_is_a_valid_task_for_both_harbor_and_aws_bench(
    multistep_task_dir: Path,
) -> None:
    """Construction is the real validation gate (Task._validate_tests +
    AwsBenchTask._validate_layout both run in __init__)."""
    task = AwsBenchTask(multistep_task_dir)
    assert task.has_steps
    assert Task.is_valid_dir(multistep_task_dir)


def test_every_step_owns_its_oracle_and_the_shared_tests_dir_is_empty(
    multistep_task_dir: Path,
) -> None:
    """Rule 1 — the one hole in the no-foreshadowing guarantee.

    ``harbor/verifier/verifier.py::_resolve_tests`` uploads the SHARED
    ``tests/`` *and* the step's own tests into ``/tests`` for every step, and in
    shared-verifier mode ``/tests`` is only emptied at the start of the NEXT
    step's verification — i.e. after that step's agent has already run. So a
    step-2 oracle placed in the shared ``tests/`` is readable by step 1's agent.
    """
    paths = TaskPaths(multistep_task_dir)
    for step in ("01-initial", "02-change-request"):
        assert paths.discovered_step_test_path_for(step, None) is not None, step

    shared = [p for p in paths.tests_dir.iterdir() if p.name != ".gitkeep"]
    assert shared == [], (
        f"shared tests/ must stay empty or strictly step-agnostic; found {shared}"
    )


def test_step_instructions_exist_host_side_and_nowhere_else(
    multistep_task_dir: Path,
) -> None:
    """Rules 2 and 3 — the two places that ARE uploaded.

    ``environment/`` becomes the image the agent lives in, and
    ``steps/01-*/workdir/`` is copied into the agent's cwd before step 1 runs.
    Step-2 material in either is visible from the first second of the trial.
    """
    paths = TaskPaths(multistep_task_dir)
    for step in ("01-initial", "02-change-request"):
        assert paths.step_instruction_path(step).is_file(), step

    later_step_marker = "change-request"
    for uploaded in (
        multistep_task_dir / "environment",
        multistep_task_dir / "steps" / "01-initial" / "workdir",
    ):
        if not uploaded.exists():
            continue
        for path in uploaded.rglob("*"):
            if not path.is_file():
                continue
            assert later_step_marker not in path.name, path
            assert later_step_marker not in path.read_text(errors="replace"), path


def test_no_root_instruction_for_a_steps_task(multistep_task_dir: Path) -> None:
    """``Task.__init__`` sets ``instruction = ""`` when steps exist, so a root
    instruction.md would be dead weight that reads like the real prompt."""
    assert not (multistep_task_dir / "instruction.md").exists()
    assert AwsBenchTask(multistep_task_dir).instruction == ""


def test_step_instructions_are_read_on_demand_not_at_construction(
    multistep_task_dir: Path, tmp_path: Path
) -> None:
    """The mechanism behind the guarantee, asserted rather than trusted.

    ``Task.step_instruction`` reads ``steps/<n>/instruction.md`` from disk at
    the moment the step's agent phase starts. Nothing caches it at
    construction, so nothing can leak it earlier.
    """
    import shutil

    copy = tmp_path / "task"
    shutil.copytree(multistep_task_dir, copy)
    task = AwsBenchTask(copy)

    target = copy / "steps" / "02-change-request" / "instruction.md"
    target.write_text("REWRITTEN AFTER CONSTRUCTION")
    assert task.step_instruction("02-change-request").strip() == (
        "REWRITTEN AFTER CONSTRUCTION"
    )


def test_the_harness_action_lives_under_the_step(multistep_task_dir: Path) -> None:
    """The cdktn extension to Harbor's layout.

    Named ``pre_invoke`` to match aws-bench's own phase-script convention (the
    directory and entry-script names ScriptRunner derives from
    ``ScriptType.PRE_INVOKE``), and placed under the step rather than the task
    so it can be re-based per step. NOTE the naming warning in memo §4(b): the
    task-level ``[post_invoke]`` is the account-teardown script, and that name
    must not be reused for a per-step hook.
    """
    script = (
        multistep_task_dir / "steps" / "02-change-request" / "pre_invoke" / "pre_invoke.sh"
    )
    assert script.is_file()
    assert (multistep_task_dir / "steps" / "01-initial" / "pre_invoke").exists() is False


def test_min_reward_gate_is_declared_on_the_first_step(multistep_task_dir: Path) -> None:
    """The hard green gate (deliverable 5 / Amendment 26): step 2's prompt never
    fires unless step 1 verified green."""
    task = AwsBenchTask(multistep_task_dir)
    first, second = task.config.steps
    assert first.min_reward == 1.0
    assert second.min_reward is None
