"""The equipping LEVEL a row is labelled with, and the material behind the label.

Two things are under test, and they are the two halves of ROADMAP M2's signature
failure mode -- a mislabelled tuned row:

  * `gates/equipping.py::equipping_level` / `harness_for_task`: the level name
    comes off the task directory, the fact that the task is equipped at all comes
    off the same `task.toml [environment]` channel the equipping hash folds in,
    and a disagreement is refused.
  * `gates/tuned_equipping.py`: the declaration is checked against the artifact,
    because Harbor installs skills with `cp ... || true` and tolerates an
    unstartable MCP server, so both failures are otherwise silent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gates.equipping import (  # noqa: E402
    LEVEL_TO_HARNESS,
    EquippingLabelMismatch,
    compute_equipping_hash,
    equipping_level,
    harness_for_task,
)
from gates.tuned_equipping import (  # noqa: E402
    CONTAINER_EQUIPPING_ROOT,
    LEVEL_OWNED_PATHS,
    oracle_identity_defects,
    static_defects,
    stdio_commands,
    tuned_task_dirs,
)

import equipping as equipping_material  # noqa: E402
import gen  # noqa: E402

TUNED_SPEC_TASKS = tuned_task_dirs()
# The corpus's own bare tasks, one per arm of the spec that opts into the
# factorial: the level labelling has to be right on both sides of the axis.
BARE_SIBLINGS = sorted(
    {
        p.parent / p.name.removesuffix("-tuned-stale").removesuffix("-tuned")
        for p in TUNED_SPEC_TASKS
    }
)


def _write_task(tmp_path: Path, *, name: str, environment: str = "") -> Path:
    task = tmp_path / name
    task.mkdir()
    (task / "instruction.md").write_text("do the thing\n")
    (task / "task.toml").write_text(
        'schema_version = "1.1"\n\n[environment]\ncpus = 1\n' + environment
    )
    return task


# --- the level map itself ----------------------------------------------------


def test_level_map_covers_every_level_the_generator_can_emit():
    assert set(LEVEL_TO_HARNESS) == {
        equipping_material.BARE,
        *equipping_material.TUNED_LEVELS,
    }


def test_harness_values_are_distinct_so_no_two_levels_pool():
    assert len(set(LEVEL_TO_HARNESS.values())) == len(LEVEL_TO_HARNESS)


def test_the_result_schema_accepts_exactly_these_harness_values():
    schema = json.loads((REPO_ROOT / "metrics" / "result_schema.json").read_text())
    assert set(schema["properties"]["harness"]["enum"]) == set(LEVEL_TO_HARNESS.values())


def test_generator_and_gates_agree_on_the_container_equipping_root():
    assert CONTAINER_EQUIPPING_ROOT == equipping_material.CONTAINER_EQUIPPING_ROOT


# --- derivation and its two refusals ----------------------------------------


def test_bare_task_derives_empty(tmp_path):
    task = _write_task(tmp_path, name="widget-awscdk")
    assert equipping_level(task) == "bare"
    assert harness_for_task(task) == "empty"


@pytest.mark.parametrize("level", ["tuned", "tuned-stale"])
def test_suffix_names_the_level_when_equipping_is_declared(tmp_path, level):
    task = _write_task(
        tmp_path,
        name=f"widget-awscdk-{level}",
        environment=f'skills_dir = "{CONTAINER_EQUIPPING_ROOT}/skills"\n',
    )
    assert equipping_level(task) == level
    assert harness_for_task(task) == LEVEL_TO_HARNESS[level]


def test_tuned_suffix_with_no_declared_equipping_is_refused(tmp_path):
    task = _write_task(tmp_path, name="widget-awscdk-tuned")
    with pytest.raises(EquippingLabelMismatch, match="cannot be published as tuned"):
        equipping_level(task)


def test_bare_name_carrying_declared_equipping_is_refused(tmp_path):
    task = _write_task(
        tmp_path,
        name="widget-awscdk",
        environment='skills_dir = "/opt/equipping/skills"\n',
    )
    with pytest.raises(EquippingLabelMismatch, match="Unregistered equipping"):
        equipping_level(task)


def test_an_inline_mcp_server_alone_is_enough_to_refuse_a_bare_name(tmp_path):
    task = _write_task(
        tmp_path,
        name="widget-awscdk",
        environment='\n[[environment.mcp_servers]]\nname = "x"\ntransport = "stdio"\ncommand = "x"\n',
    )
    with pytest.raises(EquippingLabelMismatch, match="Unregistered equipping"):
        equipping_level(task)


# --- the emitted corpus ------------------------------------------------------


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", TUNED_SPEC_TASKS, ids=lambda p: p.name)
def test_every_generated_tuned_task_is_statically_sound(task_dir):
    assert static_defects(task_dir) == []


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", TUNED_SPEC_TASKS, ids=lambda p: p.name)
def test_every_generated_tuned_task_declares_the_level_its_name_claims(task_dir):
    assert harness_for_task(task_dir) != LEVEL_TO_HARNESS["bare"]


@pytest.mark.skipif(not BARE_SIBLINGS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", BARE_SIBLINGS, ids=lambda p: p.name)
def test_the_bare_sibling_is_still_bare(task_dir):
    assert harness_for_task(task_dir) == "empty"
    assert static_defects(task_dir) == []


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
def test_stale_and_fresh_levels_declare_the_same_mcp_commands():
    """H2 isolates ONE variable: the skill's own facts. A level that also changed
    the tool list would measure two things at once, and the level would become
    observable from inside the container."""
    fresh = {p.name: stdio_commands(p) for p in TUNED_SPEC_TASKS if p.name.endswith("-tuned")}
    for name, commands in fresh.items():
        stale = next(p for p in TUNED_SPEC_TASKS if p.name == f"{name}-stale")
        assert stdio_commands(stale) == commands


# --- equipping moves the prompt surface, never the oracle -------------------


def test_gates_and_generator_agree_on_which_paths_a_level_owns():
    assert LEVEL_OWNED_PATHS == gen._LEVEL_OWNED_PATHS


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", TUNED_SPEC_TASKS, ids=lambda p: p.name)
def test_a_tuned_task_grades_exactly_as_its_bare_sibling(task_dir):
    """`instruction.md`, `tests/` and `solution/` byte-identical across levels: a
    tuned-vs-bare difference in the data must not be a difference in the oracle.
    Not automatic -- `solution/solve.sh` and `solution/broken/` are hand-authored
    and destructive-safe, so a new tuned dir would otherwise get a stub that exits
    1 and no negative fixtures (gen.py::mirror_bare_task_material)."""
    assert oracle_identity_defects(task_dir) == []


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", TUNED_SPEC_TASKS, ids=lambda p: p.name)
def test_the_reference_solution_reached_the_tuned_task(task_dir):
    """The one failure mode the byte comparison above would MISS: if both levels
    carried the same scaffolded stub, they would be identical and both useless."""
    solve = task_dir / "solution" / "solve.sh"
    assert solve.is_file()
    assert "not yet authored" not in solve.read_text()


# --- the published row's own label ------------------------------------------


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
@pytest.mark.parametrize("task_dir", [*TUNED_SPEC_TASKS, *BARE_SIBLINGS], ids=lambda p: p.name)
def test_the_published_row_carries_the_level_the_task_declares(task_dir):
    """End to end through the schema's only producer: no flag reaches `harness`."""
    from gates.emit_result import to_result_row
    from metrics.validate_result import validate_result

    row = to_result_row(
        {
            "arm": "awscdk",
            "task_dir": str(task_dir),
            "validity_class": "valid",
            "equipping_hash": "a" * 64,
            "scenario_form": "greenfield",
            "reward": 1.0,
            "n_input_tokens": 10,
            "n_output_tokens": 1,
        },
        model="claude-sonnet-5",
        oracle_version="oracles@fixture",
    )
    assert row["harness"] == harness_for_task(task_dir)
    assert validate_result(row) == []


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
def test_a_wrong_harness_flag_is_refused_rather_than_used():
    from gates.emit_result import to_result_row

    with pytest.raises(ValueError, match="read off the hashed channel"):
        to_result_row(
            {
                "arm": "awscdk",
                "task_dir": str(TUNED_SPEC_TASKS[0]),
                "validity_class": "valid",
                "equipping_hash": "a" * 64,
                "scenario_form": "greenfield",
                "reward": 1.0,
                "n_input_tokens": 10,
                "n_output_tokens": 1,
            },
            model="claude-sonnet-5",
            harness="empty",
            oracle_version="oracles@fixture",
        )


# --- the hash moves per level and per byte ----------------------------------


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
def test_the_equipping_hash_is_distinct_for_every_level_of_every_arm():
    hashes = {
        p.name: compute_equipping_hash(p, "img@sha256:" + "0" * 64, {})
        for p in [*TUNED_SPEC_TASKS, *BARE_SIBLINGS]
    }
    assert len(set(hashes.values())) == len(hashes), hashes


@pytest.mark.skipif(not TUNED_SPEC_TASKS, reason="no spec opts into a tuned level yet")
def test_one_byte_of_skill_text_moves_the_hash(tmp_path):
    """The tuned material is IN the hash, not merely alongside it: editing a
    vendored skill must mint a new hash, or two different equippings pool."""
    import shutil

    src = TUNED_SPEC_TASKS[0]
    before = compute_equipping_hash(src, "img@sha256:" + "0" * 64, {})
    copy = tmp_path / src.name
    shutil.copytree(src, copy)
    skill = next((copy / "environment" / "equipping" / "skills").rglob("SKILL.md"))
    skill.write_text(skill.read_text() + "x")
    after = compute_equipping_hash(copy, "img@sha256:" + "0" * 64, {})
    assert after != before
