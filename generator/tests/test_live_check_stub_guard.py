"""A declared hand-authored live oracle is never replaced by the stub.

The generator's stub live_check.py prints `{"status": "not_implemented"}` and
no `outcome` at all. The verifier reads a missing `outcome` as
"not_verifiable", and under gating that forces reward 0.0 for EVERY solution
on that arm, correct ones included, with exit 0 everywhere and nothing in the
logs naming the cause. Two guards keep that from being reachable: generation
refuses to write the stub over a spec that declares a hand-authored check, and
the verifier refuses to grade a stub that reached the container anyway (the
same rule as its is_stub_policy for tier-1 bundles).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gen import write_tests_dir
from spec_model import load_spec
from verifier_harness import stage

REPO_ROOT = Path(__file__).resolve().parents[2]
SFN_JSONATA = REPO_ROOT / "specs" / "sfn-jsonata.yaml"
HAND_AUTHORED = REPO_ROOT / "tasks/anchor/sfn-jsonata-hcl-raw/tests/live_check.py"


def test_a_missing_hand_authored_live_check_is_a_generation_error(tmp_path: Path) -> None:
    spec = load_spec(SFN_JSONATA)
    with pytest.raises(RuntimeError, match="hand_authored"):
        write_tests_dir(spec, "hcl_raw", tmp_path / "tests")
    assert not (tmp_path / "tests" / "live_check.py").exists()


def test_an_existing_hand_authored_live_check_survives(tmp_path: Path) -> None:
    spec = load_spec(SFN_JSONATA)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    body = HAND_AUTHORED.read_bytes()
    (tests_dir / "live_check.py").write_bytes(body)
    write_tests_dir(spec, "hcl_raw", tests_dir)
    assert (tests_dir / "live_check.py").read_bytes() == body


def test_the_verifier_refuses_to_grade_a_stub_live_check(tmp_path: Path) -> None:
    """A stub VOIDS the row -- no reward file, so harbor reports INVALID --
    instead of publishing the 0.0 the gating block would otherwise write. Run
    WITH gating armed, since that is the configuration where the difference
    between voiding and scoring is the whole point."""
    spec = load_spec(SFN_JSONATA)
    box = stage(tmp_path, spec, "awscdk")
    box.artifact({"Resources": {}})
    box.tests.joinpath("live_check.py").write_text(
        'import json\nprint(json.dumps({"status": "not_implemented"}))\n'
    )
    res = box.run("test.sh", env={"SPEC_LIVE_CHECK_ENABLED": "true",
                                  "SPEC_LIVE_CHECK_GATING": "true"})
    assert res.rc != 0
    assert res.reward is None, "a stub oracle published a score"
    assert "GENERATOR STUB" in res.stderr
