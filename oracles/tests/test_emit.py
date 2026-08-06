"""Tests for oracles/emit.py.

Runs `emit_oracles` against the real `specs/_toy/toy-ssm-parameter.yaml`
spec (the same fixture `specs/SCHEMA.md` itself is written against), always
into a `tmp_path` — never the real `oracles/` tree, so this test suite has
no side effect on the repo (see `Design.md` note below / the response
accompanying this file's authoring turn for why a real, one-off population
of `oracles/toy-ssm-parameter/` was done separately, outside pytest).

Three layers:
  - content/idempotency: intent.md always regenerated; policy.rego/.guard
    scaffolded once and never clobbered.
  - `opa check` / `cfn-guard validate` on the emitted skeletons, skipped
    (not failed) when the tool isn't locally installed — see
    `oracles/tests/toolcheck.py`.
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
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def toy_spec() -> dict:
    return yaml.safe_load(TOY_SPEC_PATH.read_text())


class TestEmitOraclesContent:
    def test_writes_all_three_files(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        assert set(files.keys()) == {
            "oracles/toy-ssm-parameter/intent.md",
            "oracles/rego/toy-ssm-parameter/policy.rego",
            "oracles/cfn-guard/toy-ssm-parameter/policy.guard",
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

    def test_guard_skeleton_lists_tier1_asserts_and_hints(self, toy_spec, tmp_path):
        files = emit_oracles(toy_spec, root=tmp_path)
        guard = files["oracles/cfn-guard/toy-ssm-parameter/policy.guard"]
        assert "policy-resource-scoped-not-wildcard" in guard
        assert "policy-actions-read-only" in guard
        for hint in toy_spec["oracle"]["cfn_guard_hints"]:
            assert hint in guard

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

    def test_policy_guard_is_never_overwritten_once_it_exists(self, toy_spec, tmp_path):
        emit_oracles(toy_spec, root=tmp_path)
        guard_path = tmp_path / "oracles" / "cfn-guard" / "toy-ssm-parameter" / "policy.guard"
        guard_path.write_text("# HAND-AUTHORED GUARD RULES — must survive regeneration\n")
        files = emit_oracles(toy_spec, root=tmp_path)
        assert "HAND-AUTHORED GUARD RULES" in files["oracles/cfn-guard/toy-ssm-parameter/policy.guard"]
        assert "HAND-AUTHORED GUARD RULES" in guard_path.read_text()


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

    def test_guard_skeleton_passes_cfn_guard_validate(self, toy_spec, tmp_path):
        cfn_guard = find_tool("cfn-guard")
        if not cfn_guard:
            pytest.skip("cfn-guard not installed locally (tried PATH, mise shims, homebrew prefixes)")
        files = emit_oracles(toy_spec, root=tmp_path)
        guard_path = tmp_path / "oracles" / "cfn-guard" / "toy-ssm-parameter" / "policy.guard"
        assert guard_path.read_text() == files["oracles/cfn-guard/toy-ssm-parameter/policy.guard"]
        data_path = FIXTURES / "mini_cfn_good.json"
        # cfn-guard exits 19 on a non-compliant template and 0 on a fully
        # compliant one — either is a *syntactically valid* parse. Only a
        # parser/DSL error (a distinct, non-{0,19} exit + "Error parsing"
        # style stderr) means the skeleton itself is malformed.
        result = subprocess.run(
            [cfn_guard, "validate", "--rules", str(guard_path), "--data", str(data_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode in (0, 19), (
            f"cfn-guard validate reported a parse/DSL error, not just non-compliance:\n"
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
