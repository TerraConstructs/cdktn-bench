"""Tests for gates/equipping.py — hash determinism, hash sensitivity.

Lives under gates/tests/ (not top-level gates/) so it resolves as
gates.tests.test_equipping alongside test_audit.py/test_emit_result.py/
test_preflight.py, per gates/tests/conftest.py's sys.path bootstrap — gates/
is a package (gates/__init__.py) as of this slice's audit/emit_result work,
so a top-level gates/test_equipping.py would try to import bare `equipping`
with only the repo root on sys.path and fail with ModuleNotFoundError.
"""

from __future__ import annotations

import json

import pytest

from gates.equipping import compute_equipping_hash

# A pre-pinned digest reference: compute_equipping_hash short-circuits
# docker entirely for "@sha256:" refs (see _resolve_image_digest), so these
# tests are hermetic — no Docker daemon required, and no risk of a
# same-inputs-different-machine mismatch coming from docker resolution.
IMAGE_REF = "cdktn-bench/awscdk@sha256:" + "ab" * 32
EXTRA_CFG = {"model": "claude-sonnet-5", "harness": "empty", "max_turns": 8}


def _make_task_dir(root, instruction: str = "Do the thing.\n") -> object:
    """Build a minimal task dir: instruction.md + one MCP config + one skill file."""
    task_dir = root / "task"
    task_dir.mkdir()
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")

    (task_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"aws-docs": {"command": "aws-docs-mcp"}}}),
        encoding="utf-8",
    )

    skill_dir = task_dir / "skills" / "iac-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# iac-helper\n\nSome skill body.\n", encoding="utf-8")

    # A plain file that is NOT equipping config (not under skills/, not a
    # recognized mcp/plugin filename) — must be ignored by the hash.
    (task_dir / "notes.txt").write_text("scratch notes, irrelevant to equipping\n", encoding="utf-8")

    return task_dir


class TestDeterminism:
    def test_identical_inputs_same_hash_across_two_temp_dirs(self, tmp_path):
        root_a = tmp_path / "machine_a"
        root_b = tmp_path / "machine_b"
        root_a.mkdir()
        root_b.mkdir()

        task_dir_a = _make_task_dir(root_a)
        task_dir_b = _make_task_dir(root_b)

        hash_a = compute_equipping_hash(task_dir_a, IMAGE_REF, EXTRA_CFG)
        hash_b = compute_equipping_hash(task_dir_b, IMAGE_REF, EXTRA_CFG)

        assert hash_a == hash_b
        assert len(hash_a) == 64
        assert all(c in "0123456789abcdef" for c in hash_a)

    def test_repeated_calls_are_stable(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        first = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)
        second = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)
        assert first == second

    def test_extra_cfg_key_order_does_not_matter(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        cfg_a = {"model": "claude-sonnet-5", "harness": "empty"}
        cfg_b = {"harness": "empty", "model": "claude-sonnet-5"}
        assert compute_equipping_hash(task_dir, IMAGE_REF, cfg_a) == compute_equipping_hash(
            task_dir, IMAGE_REF, cfg_b
        )

    def test_str_and_path_task_dir_agree(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        assert compute_equipping_hash(str(task_dir), IMAGE_REF, EXTRA_CFG) == compute_equipping_hash(
            task_dir, IMAGE_REF, EXTRA_CFG
        )


class TestSensitivity:
    def test_one_byte_instruction_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path, instruction="Do the thing.\n")
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        # Flip a single byte (period -> exclamation mark), same length.
        (task_dir / "instruction.md").write_text("Do the thing!\n", encoding="utf-8")
        changed = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert changed != baseline

    def test_skill_file_content_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (task_dir / "skills" / "iac-helper" / "SKILL.md").write_text(
            "# iac-helper\n\nA different skill body.\n", encoding="utf-8"
        )
        changed = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert changed != baseline

    def test_mcp_config_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (task_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"aws-docs": {"command": "different-binary"}}}),
            encoding="utf-8",
        )
        changed = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert changed != baseline

    def test_new_equipping_file_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (task_dir / "plugins.json").write_text(json.dumps({"plugins": ["a@b/c"]}), encoding="utf-8")
        changed = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert changed != baseline

    def test_irrelevant_file_does_not_change_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (task_dir / "notes.txt").write_text("completely different scratch notes\n", encoding="utf-8")
        unchanged = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert unchanged == baseline

    def test_image_ref_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        other_image = "cdktn-bench/awscdk@sha256:" + "cd" * 32
        changed = compute_equipping_hash(task_dir, other_image, EXTRA_CFG)

        assert changed != baseline

    def test_extra_cfg_value_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        changed_cfg = dict(EXTRA_CFG, harness="tuned")
        changed = compute_equipping_hash(task_dir, IMAGE_REF, changed_cfg)

        assert changed != baseline

    def test_model_change_changes_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        changed_cfg = dict(EXTRA_CFG, model="claude-haiku-4-5-20251001")
        changed = compute_equipping_hash(task_dir, IMAGE_REF, changed_cfg)

        assert changed != baseline


class TestErrorHandling:
    def test_missing_instruction_md_raises(self, tmp_path):
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

    def test_non_json_serializable_extra_cfg_raises(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        with pytest.raises(TypeError):
            compute_equipping_hash(task_dir, IMAGE_REF, {"model": object()})


class TestDockerFallback:
    def test_unresolvable_image_falls_back_to_tag_and_warns(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        bogus_image = "cdktn-bench/definitely-does-not-exist:dev"

        with pytest.warns(UserWarning, match="falling back to the bare tag string"):
            result = compute_equipping_hash(task_dir, bogus_image, EXTRA_CFG)

        assert len(result) == 64  # still produces a well-formed hash, just less rigorous
