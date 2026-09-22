"""`oracle.awscdk_tier1_engine` — the tier-1 engine selector (SCHEMA.md §4.5).

OPA/Rego grades tier 1 on every arm, awscdk included (ROADMAP.md M8), so
`rego` is the field's only value and its default. These tests pin the three
things a future edit could silently undo:

  1. The retired `cfn_guard` value is REJECTED at spec load, with a message
     naming M8 — not silently accepted, and not rejected with a bare
     "Input should be 'rego'" a reader cannot act on.
  2. The awscdk tier-1 block is byte-identical to the TF arms', so the two
     arms cannot drift to different strictness — DECISIONS.md Amendment 29's
     binding rule that arms are graded at equal strictness.
  3. Every shipped spec that declares a tier-"1" awscdk assert has a
     hand-authored `oracles/rego-cfn/<id>/policy.rego` — not a stub, which
     the verifier reports as SKIPPED_STUB and scores as a hard failure.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# generator/ is a script dir (no __init__.py); conftest.py puts it on sys.path.
import gen
import pytest
import yaml
from spec_model import Oracle

from oracles.emit import emit_oracles

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# A real, shipped spec with a tier-"1" assert that applies to awscdk -- so
# HAS_TIER1_ASSERTS is true and every status branch is actually reachable.
SPEC_PATH = REPO_ROOT / "specs" / "ecs-swappiness.yaml"


def shipped_specs() -> list[Path]:
    """Every scenario spec. `split.yaml` is the generated train/holdout
    assignment table living in the same directory, not a scenario."""
    return [
        p for p in sorted((REPO_ROOT / "specs").glob("*.yaml"))
        if p.name != "split.yaml"
    ]


def _tier1(spec, arm: str) -> dict:
    """The emitted verifier's tier-1 configuration: which engine grades this
    arm, with which policy file and query, and which statuses cost the reward."""
    return gen.build_verify_config(spec, arm)["tier1"]


@pytest.fixture
def spec():
    return gen.load_spec(SPEC_PATH)


class TestRegoIsTheOnlyEngine:
    def test_field_defaults_to_rego(self):
        assert Oracle(intent="x", structural_asserts=[]).awscdk_tier1_engine == "rego"

    def test_cfn_guard_is_rejected_with_a_message_naming_the_reason(self):
        with pytest.raises(ValueError) as excinfo:
            Oracle(
                intent="x", structural_asserts=[], awscdk_tier1_engine="cfn_guard"
            )
        message = str(excinfo.value)
        assert "retired" in message
        assert "ROADMAP.md M8" in message
        assert "oracles/rego-cfn" in message

    def test_every_shipped_spec_selects_rego(self):
        for path in shipped_specs():
            assert gen.load_spec(path).oracle.awscdk_tier1_engine == "rego", path.name


class TestOneEngineOnEveryArm:
    def test_awscdk_tier1_block_is_byte_identical_to_the_tf_arms(self, spec):
        """One engine, one identity domain, parity by construction. If these
        two blocks ever diverge, awscdk is being graded at a different
        strictness than hcl_raw again."""
        assert _tier1(spec, "awscdk") == _tier1(spec, "hcl_raw")

    def test_awscdk_tier1_block_preserves_every_failure_semantic(self, spec):
        tier1 = _tier1(spec, "awscdk")
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

    def test_tiers_py_runs_no_engine_but_opa(self):
        """cfn-guard stays installed in the awscdk image as an arm capability
        an agent may run; the verifier must never invoke it."""
        assert "cfn-guard" not in gen.TIERS_PY
        assert "cfn_guard" not in gen.TIERS_PY

    def test_hard_failure_reward_gate_is_untouched(self, spec):
        """ENGINE_ERROR -- "the oracle did not run" -- is listed on every arm,
        including the arms that cannot report it: the list is the
        equal-strictness contract, so an arm that later gains an engine able to
        abort must not gain a silent pass with it."""
        assert _tier1(spec, "awscdk")["bad_statuses"] == [
            "FAIL", "TOOL_MISSING", "SKIPPED_STUB", "ENGINE_ERROR",
        ]

    def test_task_toml_explanation_names_the_rego_cfn_bundle(self, spec):
        chain = gen.verification_explanation(spec, "awscdk")
        assert "tier-1 OPA/Rego (oracles/rego-cfn/ecs-swappiness/policy.rego" in chain
        assert "cfn-guard" not in chain


class TestCanonicalBundlePlumbing:
    """`write_tests_dir` copies ONE canonical policy into the task's tests/."""

    def test_tf_arm_copies_the_plan_shaped_rego_bundle(self, tmp_path, spec):
        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec, "hcl_raw", tests_dir)
        assert (tests_dir / "policy.rego").read_text() == (
            REPO_ROOT / "oracles" / "rego" / "ecs-swappiness" / "policy.rego"
        ).read_text()

    def test_awscdk_copies_the_cfn_shaped_bundle_not_the_plan_shaped_one(
        self, tmp_path, spec, monkeypatch
    ):
        """The whole point of the separate tree: awscdk must NOT be handed
        oracles/rego/<id>/policy.rego, which is written against `terraform show
        -json` and would silently evaluate to an empty deny set (=> PASS) on a
        CloudFormation template."""
        fake_oracles = tmp_path / "oracles"
        for rel, body in (
            ("rego-cfn/ecs-swappiness/policy.rego", "# CFN-SHAPED BUNDLE\n"),
            ("rego/ecs-swappiness/policy.rego", "# PLAN-SHAPED BUNDLE\n"),
        ):
            path = fake_oracles / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        monkeypatch.setattr(gen, "ORACLES_DIR", fake_oracles)

        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec, "awscdk", tests_dir)
        assert (tests_dir / "policy.rego").read_text() == "# CFN-SHAPED BUNDLE\n"

    def test_no_task_dir_carries_a_retired_guard_bundle(self):
        stale = sorted((REPO_ROOT / "tasks").rglob("policy.guard"))
        assert stale == [], stale


class TestEveryGradingSpecHasAHandAuthoredBundle:
    """A stub policy reports SKIPPED_STUB, which the reward gate scores as a
    hard failure. A spec with awscdk tier-1 asserts and a stub bundle would
    therefore fail every awscdk trial, including its own reference solution."""

    def test_no_stub_bundle_backs_an_awscdk_tier1_assert(self):
        for path in shipped_specs():
            spec = gen.load_spec(path)
            asserts = [
                a
                for a in spec.oracle.structural_asserts
                if a.tier == "1" and (not a.applies_to or "awscdk" in a.applies_to)
            ]
            bundle = REPO_ROOT / "oracles" / "rego-cfn" / spec.id / "policy.rego"
            assert bundle.exists(), f"{spec.id}: no awscdk tier-1 bundle"
            if not asserts:
                continue
            assert "GENERATOR-STUB" not in bundle.read_text(), (
                f"{spec.id} declares awscdk tier-1 asserts "
                f"{[a.name for a in asserts]} but its bundle is still a stub"
            )


class TestEmitOraclesScaffolding:
    @pytest.fixture
    def spec_dict(self):
        return yaml.safe_load(SPEC_PATH.read_text())

    def test_emit_writes_exactly_the_three_oracle_files(self, spec_dict, tmp_path):
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
        body = emit_oracles(spec_dict, root=tmp_path)[
            "oracles/rego-cfn/ecs-swappiness/policy.rego"
        ]
        # is_stub_policy() in the generated tests/tiers.py greps for this
        # literal; without it a scaffold would start gating trials.
        assert "GENERATOR-STUB" in body
        assert "package cdktn_bench.ecs_swappiness" in body
        assert "input.Resources[<LogicalId>]" in body
        assert "cfn_jsonpath:" in body
        assert "tf_jsonpath" not in body

    def test_rego_cfn_bundle_is_never_overwritten_once_hand_authored(
        self, spec_dict, tmp_path
    ):
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
        intent = emit_oracles(spec_dict, root=tmp_path)[
            "oracles/ecs-swappiness/intent.md"
        ]
        assert "../rego-cfn/ecs-swappiness/policy.rego" in intent
        assert "policy.guard" not in intent


class TestSkeletonIsValidRego:
    def test_rego_cfn_skeleton_passes_opa_check(self, tmp_path):
        opa = shutil.which("opa")
        if opa is None:
            mise = Path.home() / ".local" / "share" / "mise" / "shims" / "opa"
            opa = str(mise) if mise.exists() else None
        if opa is None:
            pytest.skip("opa not installed locally")
        import subprocess

        emit_oracles(yaml.safe_load(SPEC_PATH.read_text()), root=tmp_path)
        path = tmp_path / "oracles" / "rego-cfn" / "ecs-swappiness" / "policy.rego"
        result = subprocess.run(
            [opa, "check", str(path)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
