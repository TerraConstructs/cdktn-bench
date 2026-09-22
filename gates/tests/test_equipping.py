"""Tests for gates/equipping.py — hash determinism, hash sensitivity.

Lives under gates/tests/ (not top-level gates/) so it resolves as
gates.tests.test_equipping alongside test_audit.py/test_emit_result.py/
test_preflight.py, per gates/tests/conftest.py's sys.path bootstrap — gates/
is a package (gates/__init__.py) as of this slice's audit/emit_result work,
so a top-level gates/test_equipping.py would try to import bare `equipping`
with only the repo root on sys.path and fail with ModuleNotFoundError.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from gates import equipping
from gates.equipping import (
    COMPOSE_REL_PATH,
    HASH_SCHEME_VERSION,
    cli_equipping_digests,
    compute_equipping_hash,
    harbor_declared_equipping,
    harbor_equipping_offenders,
)

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


# ---------------------------------------------------------------------------
# HASH SCHEME 2 (DECISIONS.md Amendment 47): Harbor's own equipping channels
# ---------------------------------------------------------------------------


def _write_task_toml(task_dir, body: str) -> None:
    (task_dir / "task.toml").write_text(body, encoding="utf-8")


class TestSchemeTwoChannels:
    """Each channel changes the trial without touching any file scheme 1 hashed:
    an `environment/docker-compose.yaml` adds a sidecar service the agent and the
    verifier both reach, and `task.toml [environment] mcp_servers`/`skills_dir`
    are read by Harbor when it builds the agent.
    """

    def test_scheme_version_is_two(self):
        assert HASH_SCHEME_VERSION == 2

    def test_byte_identical_inputs_hash_alike_with_every_channel_populated(self, tmp_path):
        hashes = set()
        for name in ("machine_a", "machine_b"):
            root = tmp_path / name
            root.mkdir()
            task_dir = _make_task_dir(root)
            (task_dir / "environment").mkdir()
            (task_dir / COMPOSE_REL_PATH).write_text(
                "services:\n  tf-registry:\n    command: [responder]\n", encoding="utf-8"
            )
            _write_task_toml(
                task_dir,
                '[environment]\nskills_dir = "/opt/skills"\n'
                '[[environment.mcp_servers]]\nname = "tf-index"\n'
                'transport = "streamable-http"\nurl = "http://tf-registry:8082/mcp"\n',
            )
            (task_dir / "skills" / "iac-helper" / "extra.md").write_text("more\n", encoding="utf-8")
            hashes.add(compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG))
        assert len(hashes) == 1

    def test_adding_a_compose_file_changes_the_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (task_dir / "environment").mkdir()
        (task_dir / COMPOSE_REL_PATH).write_text("services:\n  main: {}\n", encoding="utf-8")

        assert compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG) != baseline

    def test_editing_the_compose_file_changes_the_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        (task_dir / "environment").mkdir()
        compose = task_dir / COMPOSE_REL_PATH
        compose.write_text("services:\n  main: {}\n", encoding="utf-8")
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        compose.write_text("services:\n  main: {}\n  tf-registry: {}\n", encoding="utf-8")

        assert compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG) != baseline

    def test_an_mcp_servers_entry_changes_the_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(task_dir, '[metadata]\nname = "t"\n')
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        _write_task_toml(
            task_dir,
            '[metadata]\nname = "t"\n[[environment.mcp_servers]]\n'
            'name = "aws-docs"\ntransport = "stdio"\ncommand = "aws-docs-mcp"\n',
        )

        assert compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG) != baseline

    def test_a_skills_dir_declaration_changes_the_hash(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(task_dir, '[metadata]\nname = "t"\n')
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        _write_task_toml(task_dir, '[metadata]\nname = "t"\n[environment]\nskills_dir = "/opt/skills"\n')

        assert compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG) != baseline

    def test_a_skill_file_under_a_declared_skills_dir_changes_the_hash(self, tmp_path):
        """The declared path is a CONTAINER path; it is resolved by basename to the
        one tree of that name shipping in the task dir, so editing the vendored
        skill moves the hash through this channel too."""
        task_dir = _make_task_dir(tmp_path)
        vendored = task_dir / "environment" / "tuned-skills"
        vendored.mkdir(parents=True)
        (vendored / "SKILL.md").write_text("# authoring\n", encoding="utf-8")
        _write_task_toml(task_dir, '[environment]\nskills_dir = "/opt/tuned-skills"\n')
        baseline = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        (vendored / "SKILL.md").write_text("# authoring, revised\n", encoding="utf-8")

        assert compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG) != baseline

    def test_an_unreadable_skills_dir_is_recorded_as_declared_only(self, tmp_path):
        """No tree of that name ships in the task dir: the declaration is still in
        the hash, its file list is null, and no guess is made between candidates."""
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(task_dir, '[environment]\nskills_dir = "/opt/absent"\n')

        declared = harbor_declared_equipping(task_dir)

        assert declared["skills_dir"] == {"declared": "/opt/absent", "files": None}

    def test_a_malformed_task_toml_reads_as_nothing_declared(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(task_dir, "this is not toml = = =\n")

        assert harbor_declared_equipping(task_dir) == {"mcp_servers": None, "skills_dir": None}

    def test_scheme_one_and_scheme_two_differ_for_the_same_inputs(self, tmp_path, monkeypatch):
        """Intended and recorded: a scheme-1 row and a scheme-2 row for
        byte-identical inputs are not comparable by hash. The asset-mirror image
        change already moved every arm's hash, so the boundary costs nothing extra
        (DECISIONS.md Amendment 47)."""
        task_dir = _make_task_dir(tmp_path)
        under_two = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        monkeypatch.setattr(equipping, "HASH_SCHEME_VERSION", 1)
        under_one = compute_equipping_hash(task_dir, IMAGE_REF, EXTRA_CFG)

        assert under_one != under_two


class TestHoldoutChannel:
    """`generator/gen.py::enforce_no_holdout_equipping` reads this, so the holdout
    rule covers an MCP server declared inline in `task.toml` and not only a
    skill/MCP file it can glob for."""

    def test_declared_servers_and_skills_are_named_as_offenders(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(
            task_dir,
            '[environment]\nskills_dir = "/opt/skills"\n'
            '[[environment.mcp_servers]]\nname = "tf-index"\ntransport = "stdio"\n',
        )

        offenders = harbor_equipping_offenders(task_dir)

        assert any("mcp_servers (tf-index)" in o for o in offenders)
        assert any("skills_dir = /opt/skills" in o for o in offenders)

    def test_a_task_declaring_neither_has_no_offenders(self, tmp_path):
        task_dir = _make_task_dir(tmp_path)
        _write_task_toml(task_dir, '[metadata]\nname = "t"\n')

        assert harbor_equipping_offenders(task_dir) == []


class TestCliEquippingDigests:
    """`scripts/run-bench.sh` records these in `jobs/*/budget.json`: content, not
    the flag's path, because two different files at one path hashed alike while it
    held the flag string."""

    def test_a_file_flag_records_its_content_digest_and_no_path(self, tmp_path):
        cfg = tmp_path / "mcp.json"
        cfg.write_text('{"mcpServers": {}}', encoding="utf-8")

        entries = cli_equipping_digests([f"--mcp-config={cfg}"])

        assert entries == [
            {"flag": "--mcp-config", "sha256": hashlib.sha256(cfg.read_bytes()).hexdigest()}
        ]

    def test_two_identical_files_at_different_paths_digest_alike(self, tmp_path):
        first = tmp_path / "a" / "mcp.json"
        second = tmp_path / "b" / "mcp.json"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text('{"mcpServers": {}}', encoding="utf-8")

        assert cli_equipping_digests([f"--mcp-config={first}"]) == cli_equipping_digests(
            [f"--mcp-config={second}"]
        )

    def test_a_skill_dir_digest_follows_its_bytes(self, tmp_path):
        skill = tmp_path / "skills" / "tf-authoring"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# tf authoring\n", encoding="utf-8")
        baseline = cli_equipping_digests([f"--skill={skill}"])

        (skill / "REFERENCE.md").write_text("more\n", encoding="utf-8")

        assert cli_equipping_digests([f"--skill={skill}"]) != baseline

    def test_an_unreadable_argument_is_null_not_absent(self, tmp_path):
        """A typo'd flag must read as unhashable equipping, never as no equipping."""
        entries = cli_equipping_digests([f"--skill={tmp_path / 'nope'}"])

        assert entries == [{"flag": "--skill", "sha256": None}]
