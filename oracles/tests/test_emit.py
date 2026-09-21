"""Tests for oracles/emit.py.

Runs `emit_oracles` against the real `specs/_toy/toy-ssm-parameter.yaml`
spec (the same fixture `specs/SCHEMA.md` itself is written against), always
into a `tmp_path` — never the real `oracles/` tree, so this test suite has
no side effect on the repo.

Two layers:
  - content/idempotency: intent.md always regenerated; both policy.rego
    bundles scaffolded once and never clobbered.
  - `opa check` on the emitted skeletons, skipped (not failed) when opa
    isn't locally installed — see `oracles/tests/toolcheck.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from oracles.emit import emit_oracles
from oracles.tests.toolcheck import find_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
TOY_SPEC_PATH = REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml"


@pytest.fixture
def toy_spec() -> dict:
    return yaml.safe_load(TOY_SPEC_PATH.read_text())


class TestEmitOraclesContent:
    def test_writes_all_three_files(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        assert set(files.keys()) == {
            "oracles/toy-ssm-parameter/intent.md",
            "oracles/rego/toy-ssm-parameter/policy.rego",
            "oracles/rego-cfn/toy-ssm-parameter/policy.rego",
        }
        for relative_path in files:
            assert (tmp_path / relative_path).exists()

    def test_intent_md_contains_oracle_intent_verbatim(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        intent_md = files["oracles/toy-ssm-parameter/intent.md"]
        assert toy_spec["oracle"]["intent"].strip() in intent_md
        assert "Do not hand-edit" in intent_md

    def test_rego_skeleton_lists_tier1_asserts_and_hints(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        rego = files["oracles/rego/toy-ssm-parameter/policy.rego"]
        assert "policy-resource-scoped-not-wildcard" in rego
        assert "policy-actions-read-only" in rego
        assert "package cdktn_bench.toy_ssm_parameter" in rego
        for hint in toy_spec["oracle"]["rego_hints"]:
            assert hint in rego

    def test_rego_cfn_skeleton_lists_tier1_asserts_and_cfn_hints(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        cfn = files["oracles/rego-cfn/toy-ssm-parameter/policy.rego"]
        assert "policy-resource-scoped-not-wildcard" in cfn
        assert "policy-actions-read-only" in cfn
        assert "package cdktn_bench.toy_ssm_parameter" in cfn
        # The CFN-shape hints, never the plan-JSON ones: the awscdk bundle
        # reads a synthesized template, so rego_hints would mislead here.
        for hint in toy_spec["oracle"]["cfn_guard_hints"]:
            assert hint in cfn

    def test_intent_md_is_regenerated_every_call(self, toy_spec, tmp_path):
        emit_oracles(toy_spec, root=tmp_path)
        intent_path = tmp_path / "oracles" / "toy-ssm-parameter" / "intent.md"
        intent_path.write_text("HAND-EDITED CONTENT THAT SHOULD BE OVERWRITTEN")
        files = emit_oracles(toy_spec, root=tmp_path)
        assert "HAND-EDITED" not in files["oracles/toy-ssm-parameter/intent.md"]
        assert "HAND-EDITED" not in intent_path.read_text()

    def test_policy_rego_is_never_overwritten_once_it_exists(self, toy_spec, tmp_path):
        emit_oracles(toy_spec, root=tmp_path)
        rego_path = tmp_path / "oracles" / "rego" / "toy-ssm-parameter" / "policy.rego"
        rego_path.write_text("# HAND-AUTHORED POLICY — must survive regeneration\npackage x\n")
        files = emit_oracles(toy_spec, root=tmp_path)
        assert "HAND-AUTHORED POLICY" in files["oracles/rego/toy-ssm-parameter/policy.rego"]
        assert "HAND-AUTHORED POLICY" in rego_path.read_text()

    def test_rego_cfn_policy_is_never_overwritten_once_it_exists(self, toy_spec, tmp_path):
        emit_oracles(toy_spec, root=tmp_path)
        cfn_path = tmp_path / "oracles" / "rego-cfn" / "toy-ssm-parameter" / "policy.rego"
        cfn_path.write_text("# HAND-AUTHORED CFN RULES — must survive regeneration\npackage x\n")
        files = emit_oracles(toy_spec, root=tmp_path)
        assert "HAND-AUTHORED CFN RULES" in files["oracles/rego-cfn/toy-ssm-parameter/policy.rego"]
        assert "HAND-AUTHORED CFN RULES" in cfn_path.read_text()


class TestEmittedSkeletonsAreValidPolicySyntax:
    def test_rego_skeleton_passes_opa_check(self, toy_spec, tmp_path):
        opa = find_tool("opa")
        if not opa:
            pytest.skip("opa not installed locally (tried PATH, mise shims, homebrew prefixes)")
        files = emit_oracles(toy_spec, root=tmp_path)
        rego_path = tmp_path / "oracles" / "rego" / "toy-ssm-parameter" / "policy.rego"
        assert rego_path.read_text() == files["oracles/rego/toy-ssm-parameter/policy.rego"]
        result = subprocess.run([opa, "check", str(rego_path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"opa check failed:\nstdout={result.stdout}\nstderr={result.stderr}"

    def test_rego_cfn_skeleton_passes_opa_check(self, toy_spec, tmp_path):
        opa = find_tool("opa")
        if not opa:
            pytest.skip("opa not installed locally (tried PATH, mise shims, homebrew prefixes)")
        files = emit_oracles(toy_spec, root=tmp_path)
        cfn_path = tmp_path / "oracles" / "rego-cfn" / "toy-ssm-parameter" / "policy.rego"
        assert cfn_path.read_text() == files["oracles/rego-cfn/toy-ssm-parameter/policy.rego"]
        result = subprocess.run([opa, "check", str(cfn_path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"opa check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
