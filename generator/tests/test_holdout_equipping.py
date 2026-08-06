"""generator/tests/test_holdout_equipping.py -- unit coverage for
generator/gen.py::enforce_no_holdout_equipping (DECISIONS.md Amendment 10):
the generator must hard-fail `make gen` if a HOLDOUT-split scenario's
generated task directory ever contains tuned-equipping material (skill/MCP/
plugin config, the same shapes gates/equipping.py's own equipping-hash
discovery already recognizes).

Uses synthetic task_dir trees under tmp_path (no real spec/generation
needed -- enforce_no_holdout_equipping only reads generated arm dirs off
disk and consults specs/split.yaml via split.spec_group), plus a fake
Spec-like stand-in (only `.id` is read).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from gen import HoldoutEquippingViolation, enforce_no_holdout_equipping


@dataclass
class _FakeSpec:
    id: str


def _make_arm_dir(root, name: str) -> object:
    d = root / name
    d.mkdir(parents=True)
    (d / "instruction.md").write_text("Do the thing.\n")
    return d


class TestHoldoutBlocksEquipping:
    def test_holdout_scenario_with_mcp_config_raises(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "awscdk")
        (arm_dir / "mcp.json").write_text("{}")
        spec = _FakeSpec(id="sfn-jsonata")  # real holdout scenario, specs/split.yaml
        with pytest.raises(HoldoutEquippingViolation) as exc:
            enforce_no_holdout_equipping(spec, {"awscdk": arm_dir})
        assert "sfn-jsonata" in str(exc.value)
        assert "mcp.json" in str(exc.value)

    def test_holdout_scenario_with_skills_dir_raises(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "hcl_raw")
        skill_dir = arm_dir / "skills" / "iac-helper"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# iac-helper\n")
        spec = _FakeSpec(id="s3-lambda-log-retention")  # real holdout scenario
        with pytest.raises(HoldoutEquippingViolation) as exc:
            enforce_no_holdout_equipping(spec, {"hcl_raw": arm_dir})
        assert "skills/iac-helper/SKILL.md" in str(exc.value)

    def test_holdout_scenario_with_plugin_config_raises(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "terraconstructs")
        (arm_dir / "plugins.json").write_text("{}")
        spec = _FakeSpec(id="sfn-jsonata")
        with pytest.raises(HoldoutEquippingViolation):
            enforce_no_holdout_equipping(spec, {"terraconstructs": arm_dir})

    def test_offending_file_named_per_arm(self, tmp_path):
        awscdk_dir = _make_arm_dir(tmp_path, "awscdk")
        hcl_dir = _make_arm_dir(tmp_path, "hcl_raw")
        (hcl_dir / "mcp.json").write_text("{}")
        spec = _FakeSpec(id="sfn-jsonata")
        with pytest.raises(HoldoutEquippingViolation) as exc:
            enforce_no_holdout_equipping(spec, {"awscdk": awscdk_dir, "hcl_raw": hcl_dir})
        assert "hcl_raw:" in str(exc.value)


class TestTrainAndUnknownAreSilent:
    def test_train_scenario_with_equipping_is_allowed(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "awscdk")
        (arm_dir / "mcp.json").write_text("{}")
        spec = _FakeSpec(id="ecs-swappiness")  # real train scenario
        enforce_no_holdout_equipping(spec, {"awscdk": arm_dir})  # must not raise

    def test_unclassified_scenario_is_allowed(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "awscdk")
        (arm_dir / "mcp.json").write_text("{}")
        spec = _FakeSpec(id="some-future-scenario-not-in-split-yaml-yet")
        enforce_no_holdout_equipping(spec, {"awscdk": arm_dir})  # must not raise

    def test_holdout_scenario_with_no_equipping_is_allowed(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "awscdk")
        spec = _FakeSpec(id="sfn-jsonata")
        enforce_no_holdout_equipping(spec, {"awscdk": arm_dir})  # must not raise

    def test_holdout_scenario_with_unrelated_files_is_allowed(self, tmp_path):
        arm_dir = _make_arm_dir(tmp_path, "awscdk")
        (arm_dir / "task.toml").write_text("[metadata]\n")
        (arm_dir / "notes.md").write_text("not equipping\n")
        spec = _FakeSpec(id="sfn-jsonata")
        enforce_no_holdout_equipping(spec, {"awscdk": arm_dir})  # must not raise
