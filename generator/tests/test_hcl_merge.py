"""The HCL pre-parser is a FILE, not a heredoc.

`oracle.hcl_traversal`'s `.tf` -> JSON pre-parse is a generated
tests/hcl_merge.py that tests/tiers.py invokes. Two properties are
pinned here because both are silent when they break:

  * the emitted program's bytes and what it may read -- only sys.argv[1] and
    sys.argv[2], never argv[0], __file__ or sys.path -- so the program cannot
    depend on how it is delivered and /logs/verifier/oracle-input.json cannot
    move for any fixture (gates/hcl_merge_bytes.py proves that per fixture);
  * the invocation and the arms that get the file, because a task dir missing
    it must report the fail-closed LIB_MISSING status rather than grade a
    document nothing parsed.

Offline and toolchain-free: reads the real generated task dirs and calls the
emitters directly.
"""

from __future__ import annotations

import copy
import stat
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import (  # noqa: E402
    HCL_MERGE_PY,
    TIERS_PY,
    build_hcl_merge_py,
    build_verify_config,
    task_dir,
    write_tests_dir,
)
from spec_model import Spec, load_spec  # noqa: E402
from verifier_harness import stage  # noqa: E402

# The one spec with `oracle.hcl_traversal: true`. A second one joins this list
# rather than getting its own copy of these tests.
HCL_SPEC = REPO_ROOT / "specs" / "s3-notification-authoritative-singleton.yaml"


@pytest.fixture(scope="module")
def spec() -> Spec:
    return load_spec(HCL_SPEC)


def test_the_emitted_program_is_the_one_source_plus_a_header() -> None:
    """One owner for the program text. A second copy -- a stale heredoc, a
    hand-tweaked task file -- is exactly the drift the byte gate cannot see,
    because it compares what ONE writer produced against itself."""
    emitted = build_hcl_merge_py()
    assert emitted.endswith(HCL_MERGE_PY)
    header = emitted[: -len(HCL_MERGE_PY)]
    assert header.startswith("#!/usr/bin/env python3\n")
    assert "Generated -- generator/gen.py" in header
    assert all(line.startswith("#") or not line for line in header.splitlines())


def test_the_program_carries_no_backslash_escape() -> None:
    """A literal escape would have to survive the template's own quoting to
    arrive intact. An escape-free program has nothing to survive, and its bytes
    stay comparable across any delivery."""
    assert "\\" not in HCL_MERGE_PY


def test_the_program_is_stdlib_only_and_reads_its_two_arguments() -> None:
    """The two arguments and NOTHING about where the program lives. `python3 -`
    and `python3 path/to/prog.py` differ only in argv[0], __file__ and
    sys.path[0], so a program that reads none of them writes the same
    /logs/verifier/oracle-input.json however it is delivered."""
    assert "sys.argv[1]" in HCL_MERGE_PY
    assert "sys.argv[2]" in HCL_MERGE_PY
    for location in ("sys.argv[0]", "sys.argv[3]", "__file__", "sys.path"):
        assert location not in HCL_MERGE_PY
    for third_party in ("import hcl2", "import boto3", "import requests", "import yaml"):
        assert third_party not in HCL_MERGE_PY


def test_the_verifier_invokes_the_file_and_holds_no_heredoc(spec: Spec) -> None:
    assert build_verify_config(spec, "hcl_raw")["tier1"]["hcl"] == "merge"
    assert 'DIR / "hcl_merge.py"' in TIERS_PY
    assert '["python3", str(merge), str(artifact), str(merged)]' in TIERS_PY
    assert "import glob" not in TIERS_PY


def test_a_missing_pre_parser_is_lib_missing_not_a_verdict(
    spec: Spec, tmp_path: Path
) -> None:
    """Fail-closed, and through the SAME status as a missing resolver: the
    pre-parser is part of the oracle, so its absence can only mean the document
    was never readable -- never that the solution is wrong."""
    box = stage(tmp_path, spec, "hcl_raw")
    artifact = box.artifact({"planned_values": {}})
    tiers = box.tiers()
    cfg = box.config()["tier1"]
    assert tiers._hcl_input(cfg, artifact) == ("OK", box.logs / "oracle-input.json")
    box.drop("hcl_merge.py")
    assert tiers._hcl_input(cfg, artifact)[0] == "LIB_MISSING"
    box.drop("hcl_traversal.rego")
    assert tiers._hcl_input(cfg, artifact)[0] == "LIB_MISSING"


def test_the_real_generated_task_ships_it_on_hcl_raw_only(spec: Spec) -> None:
    hcl_raw = task_dir(spec, "hcl_raw") / "tests" / "hcl_merge.py"
    assert hcl_raw.is_file(), "regenerate: make gen SPEC=specs/{}.yaml".format(spec.id)
    assert hcl_raw.read_text() == build_hcl_merge_py()
    assert hcl_raw.stat().st_mode & stat.S_IXUSR
    # terraconstructs synthesizes cdk.tf.json and has no .tf source; emitting
    # the parser there would write an EMPTY `_hcl`, which the policy's own
    # fail-closed deny reads as "no .tf source was supplied" and scores a
    # correct solution 0.0.
    for arm in ("terraconstructs", "awscdk"):
        assert not (task_dir(spec, arm) / "tests" / "hcl_merge.py").exists()


def test_turning_the_flag_off_removes_a_stale_copy(tmp_path: Path) -> None:
    """A task dir must never keep claiming an oracle component the emitted
    verifier no longer calls: a leftover hcl_merge.py beside a verify.py that
    declares no merge reads as a working pre-parse to anyone auditing the
    directory."""
    raw = yaml.safe_load(HCL_SPEC.read_text())
    on = Spec.model_validate(raw)
    tests = tmp_path / "tests"
    write_tests_dir(on, "hcl_raw", tests)
    assert (tests / "hcl_merge.py").is_file()

    off_raw = copy.deepcopy(raw)
    off_raw["oracle"]["hcl_traversal"] = False
    write_tests_dir(Spec.model_validate(off_raw), "hcl_raw", tests)
    assert not (tests / "hcl_merge.py").exists()
    assert not (tests / "hcl_traversal.rego").exists()
