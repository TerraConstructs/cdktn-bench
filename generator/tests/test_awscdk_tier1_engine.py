"""`oracle.awscdk_tier1_engine` — the M8 tier-1 engine selector (SCHEMA.md §4.5).

Two things need proving, and they pull in opposite directions:

  1. **Nothing changes by default.** The field exists, but every spec written
     before it did must regenerate byte-identically. `make gen-all` proves that
     over the whole tree; these tests pin it at the two emission sites that
     could drift silently (the tier-1 shell block and `task.toml`'s
     verification_explanation), so a future edit to either one fails here
     rather than in a whole-tree diff nobody re-runs.
  2. **Selecting `rego` really does swap the engine** — and swaps it to the
     *same* block the TF arms already run, not to a lookalike. The strongest
     form of "no failure semantics were weakened" is byte-equality with the
     block that already carries them, so that is what is asserted.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# generator/ is a script dir (no __init__.py); conftest.py puts it on sys.path.
import gen
import pytest
import yaml

from oracles.emit import emit_oracles

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# A real, shipped spec with a tier-"1" assert that applies to awscdk -- so
# HAS_TIER1_ASSERTS is true and every status branch is actually reachable.
SPEC_PATH = REPO_ROOT / "specs" / "ecs-swappiness.yaml"


def _tier1(spec, arm: str) -> dict:
    """The emitted verifier's tier-1 configuration: which engine grades this
    arm, with which policy file and query, and which statuses cost the reward."""
    return gen.build_verify_config(spec, arm)["tier1"]


@pytest.fixture
def spec():
    return gen.load_spec(SPEC_PATH)


@pytest.fixture
def spec_rego(spec):
    flipped = spec.model_copy(deep=True)
    object.__setattr__(flipped.oracle, "awscdk_tier1_engine", "rego")
    return flipped


class TestDefaultIsTheIncumbent:
    def test_field_defaults_to_cfn_guard(self, spec):
        assert spec.oracle.awscdk_tier1_engine == "cfn_guard"

    def test_default_awscdk_tier1_still_runs_cfn_guard(self, spec):
        tier1 = _tier1(spec, "awscdk")
        assert tier1["engine"] == "cfn_guard"
        assert tier1["header"] == "cfn-guard"
        assert tier1["policy"] == "policy.guard"
        assert tier1["query"] is None, "a cfn-guard arm declares no Rego query"

    def test_default_task_toml_explanation_names_cfn_guard(self, spec):
        chain = gen.verification_explanation(spec, "awscdk")
        assert "tier-1 cfn-guard (oracles/cfn-guard/ecs-swappiness/policy.guard" in chain


class TestRegoSelectionSwapsTheEngine:
    def test_awscdk_rego_block_is_byte_identical_to_the_tf_arms(self, spec, spec_rego):
        """The point of M8: one engine, one identity domain, parity by
        construction. If these two blocks ever diverge, awscdk is being graded
        at a different strictness than hcl_raw again -- the exact thing
        DECISIONS.md Amendment 29 §4 forbids."""
        assert _tier1(spec_rego, "awscdk") == _tier1(spec, "hcl_raw")

    def test_awscdk_rego_block_preserves_every_failure_semantic(self, spec_rego):
        """Every status the mechanism can report is one shared library's, so
        selecting an engine cannot weaken any of them -- and the engine the
        selector picked really is opa."""
        tier1 = _tier1(spec_rego, "awscdk")
        assert tier1["engine"] == "opa"
        assert tier1["policy"] == "policy.rego"
        assert tier1["has_asserts"] is True
        assert tier1["query"].endswith(".deny")
        assert tier1["not_verifiable_query"].endswith(".not_verifiable")
        for status in ("SKIPPED_NO_ASSERTS", "TOOL_MISSING", "SKIPPED_STUB",
                       "PASS", "FAIL"):
            assert status in gen.TIERS_PY, (
                f"{status} is not a status tests/tiers.py can report"
            )
        for marker in ("tier1-unavailable", "tier1-unauthored"):
            assert marker in gen.TIERS_PY

    def test_hard_failure_reward_gate_is_untouched(self, spec, spec_rego):
        """The same three statuses cost the reward on both engines, so a rego
        scenario cannot silently score a TOOL_MISSING/SKIPPED_STUB run as a
        pass."""
        for candidate in (spec, spec_rego):
            assert _tier1(candidate, "awscdk")["bad_statuses"] == [
                "FAIL", "TOOL_MISSING", "SKIPPED_STUB",
            ]

    def test_task_toml_explanation_names_the_rego_cfn_bundle(self, spec_rego):
        chain = gen.verification_explanation(spec_rego, "awscdk")
        assert "tier-1 OPA/Rego (oracles/rego-cfn/ecs-swappiness/policy.rego" in chain
        assert "cfn-guard" not in chain


class TestCanonicalBundlePlumbing:
    """`write_tests_dir` copies ONE canonical policy into the task's tests/."""

    def test_default_awscdk_copies_the_guard_bundle(self, tmp_path, spec):
        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec, "awscdk", tests_dir)
        assert (tests_dir / "policy.guard").exists()
        assert not (tests_dir / "policy.rego").exists()
        assert (tests_dir / "policy.guard").read_text() == (
            REPO_ROOT / "oracles" / "cfn-guard" / "ecs-swappiness" / "policy.guard"
        ).read_text()

    def test_tf_arm_copies_the_plan_shaped_rego_bundle(self, tmp_path, spec):
        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec, "hcl_raw", tests_dir)
        assert (tests_dir / "policy.rego").read_text() == (
            REPO_ROOT / "oracles" / "rego" / "ecs-swappiness" / "policy.rego"
        ).read_text()

    def test_rego_engine_copies_the_cfn_shaped_bundle_not_the_plan_shaped_one(
        self, tmp_path, spec_rego, monkeypatch
    ):
        """The whole point of the separate tree: awscdk must NOT be handed
        oracles/rego/<id>/policy.rego, which is written against `terraform show
        -json` and would silently evaluate to an empty deny set (=> PASS) on a
        CloudFormation template."""
        fake_oracles = tmp_path / "oracles"
        (fake_oracles / "rego-cfn" / "ecs-swappiness").mkdir(parents=True)
        (fake_oracles / "rego-cfn" / "ecs-swappiness" / "policy.rego").write_text(
            "# CFN-SHAPED BUNDLE\n"
        )
        (fake_oracles / "rego" / "ecs-swappiness").mkdir(parents=True)
        (fake_oracles / "rego" / "ecs-swappiness" / "policy.rego").write_text(
            "# PLAN-SHAPED BUNDLE\n"
        )
        monkeypatch.setattr(gen, "ORACLES_DIR", fake_oracles)

        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec_rego, "awscdk", tests_dir)
        assert (tests_dir / "policy.rego").read_text() == "# CFN-SHAPED BUNDLE\n"
        assert not (tests_dir / "policy.guard").exists()

    def test_flipping_the_engine_removes_the_previous_engines_stale_bundle(
        self, tmp_path, spec, spec_rego, monkeypatch
    ):
        fake_oracles = tmp_path / "oracles"
        for rel, body in (
            ("cfn-guard/ecs-swappiness/policy.guard", "# GUARD\n"),
            ("rego-cfn/ecs-swappiness/policy.rego", "# CFN-SHAPED\n"),
        ):
            path = fake_oracles / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        monkeypatch.setattr(gen, "ORACLES_DIR", fake_oracles)

        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec, "awscdk", tests_dir)
        assert (tests_dir / "policy.guard").exists()

        gen.write_tests_dir(spec_rego, "awscdk", tests_dir)
        assert (tests_dir / "policy.rego").read_text() == "# CFN-SHAPED\n"
        assert not (tests_dir / "policy.guard").exists(), (
            "the previous engine's bundle must not linger in a task dir that no "
            "longer runs it"
        )


class TestEmitOraclesScaffolding:
    @pytest.fixture
    def spec_dict(self):
        return yaml.safe_load(SPEC_PATH.read_text())

    def test_default_scaffolds_the_guard_bundle_and_no_rego_cfn_tree(
        self, spec_dict, tmp_path
    ):
        files = emit_oracles(spec_dict, root=tmp_path)
        assert "oracles/cfn-guard/ecs-swappiness/policy.guard" in files
        assert "oracles/rego-cfn/ecs-swappiness/policy.rego" not in files
        assert not (tmp_path / "oracles" / "rego-cfn").exists()

    def test_rego_engine_scaffolds_rego_cfn_and_no_guard_bundle(
        self, spec_dict, tmp_path
    ):
        spec_dict["oracle"]["awscdk_tier1_engine"] = "rego"
        files = emit_oracles(spec_dict, root=tmp_path)
        assert set(files) == {
            "oracles/ecs-swappiness/intent.md",
            "oracles/rego/ecs-swappiness/policy.rego",
            "oracles/rego-cfn/ecs-swappiness/policy.rego",
        }
        assert not (tmp_path / "oracles" / "cfn-guard").exists()

    def test_rego_cfn_skeleton_is_a_stub_and_documents_the_cfn_input_shape(
        self, spec_dict, tmp_path
    ):
        spec_dict["oracle"]["awscdk_tier1_engine"] = "rego"
        body = emit_oracles(spec_dict, root=tmp_path)[
            "oracles/rego-cfn/ecs-swappiness/policy.rego"
        ]
        # is_stub_policy() in the generated tests/static_tiers.sh greps for this
        # literal; without it a scaffold would start gating trials.
        assert "GENERATOR-STUB" in body
        assert "package cdktn_bench.ecs_swappiness" in body
        assert "input.Resources[<LogicalId>]" in body
        assert "cfn_jsonpath:" in body
        assert "tf_jsonpath" not in body

    def test_rego_cfn_bundle_is_never_overwritten_once_hand_authored(
        self, spec_dict, tmp_path
    ):
        spec_dict["oracle"]["awscdk_tier1_engine"] = "rego"
        path = tmp_path / "oracles" / "rego-cfn" / "ecs-swappiness" / "policy.rego"
        path.parent.mkdir(parents=True)
        path.write_text("# HAND-AUTHORED CFN REGO — must survive regeneration\n")
        files = emit_oracles(spec_dict, root=tmp_path)
        assert "HAND-AUTHORED CFN REGO" in files[
            "oracles/rego-cfn/ecs-swappiness/policy.rego"
        ]

    def test_intent_md_points_at_the_bundle_the_scenario_actually_runs(
        self, spec_dict, tmp_path
    ):
        default = emit_oracles(spec_dict, root=tmp_path)["oracles/ecs-swappiness/intent.md"]
        assert "../cfn-guard/ecs-swappiness/policy.guard" in default

        spec_dict["oracle"]["awscdk_tier1_engine"] = "rego"
        flipped = emit_oracles(spec_dict, root=tmp_path / "other")[
            "oracles/ecs-swappiness/intent.md"
        ]
        assert "../rego-cfn/ecs-swappiness/policy.rego" in flipped
        assert "policy.guard" not in flipped


class TestSkeletonIsValidRego:
    def test_rego_cfn_skeleton_passes_opa_check(self, tmp_path):
        opa = shutil.which("opa")
        if opa is None:
            mise = Path.home() / ".local" / "share" / "mise" / "shims" / "opa"
            opa = str(mise) if mise.exists() else None
        if opa is None:
            pytest.skip("opa not installed locally")
        import subprocess

        spec_dict = yaml.safe_load(SPEC_PATH.read_text())
        spec_dict["oracle"]["awscdk_tier1_engine"] = "rego"
        emit_oracles(spec_dict, root=tmp_path)
        path = tmp_path / "oracles" / "rego-cfn" / "ecs-swappiness" / "policy.rego"
        result = subprocess.run(
            [opa, "check", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
