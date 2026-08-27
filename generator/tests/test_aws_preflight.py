"""generator/tests/test_aws_preflight.py -- the AWS PREFLIGHT contract
(DECISIONS.md Amendment 32, aws-access.html).

Live AWS is the only trial mode, so both Terraform-shaped arms need a working
ambient credential chain before any toolchain command is worth running. A
missing chain is test INFRASTRUCTURE failing, not a bad solution, and must VOID
the row -- no reward file at all, so harbor raises RewardFileNotFoundError --
rather than score 0.0, which is indistinguishable from a wrong answer.

Three things have to hold together, and only one of them is visible in
`static_tiers.sh` alone:

  1. `static_tiers.sh` preflights `aws sts get-caller-identity` on hcl_raw and
     terraconstructs (awscdk's chain makes no AWS call) and exports a region
     first -- without the region the preflight itself dies `NoRegion` and would
     void every row, perfect solutions included.
  2. The preflight writes NO reward.txt and runs BEFORE any toolchain command.
  3. `test.sh` short-circuits on the marker. It does not abort on
     static_tiers.sh's exit code, and its live_check / idempotence gating
     blocks write `0.0` -- so without the short-circuit the void becomes a
     zero. The positive control below proves those blocks really would.

Offline and toolchain-free: `bash` and `jq` only, with stub binaries on PATH.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import build_static_tiers_sh, build_test_sh  # noqa: E402
from spec_model import Spec, load_spec  # noqa: E402

SPEC_PATH = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
PREFLIGHT_CMD = "aws sts get-caller-identity"
MARKER = "/logs/verifier/aws-unavailable"
PREFLIGHT_ARMS = ("hcl_raw", "terraconstructs")


def _all_specs() -> list[Spec]:
    """Discovered, never listed -- a spec added tomorrow is covered today."""
    specs = [
        load_spec(p)
        for p in sorted((REPO_ROOT / "specs").glob("*.yaml"))
        if p.name != "split.yaml"  # the split manifest, not a scenario
    ]
    assert specs, "no specs found -- this module would be vacuous"
    return specs


def _static_tiers_variants(spec: Spec, arm: str) -> list[tuple[str, str]]:
    """(label, body) for the single-step script or every step's script."""
    if spec.is_multi_step():
        return [
            (f"{spec.id}[{arm}][step {s.name}]", build_static_tiers_sh(spec, arm, s))
            for s in (spec.steps or [])
        ]
    return [(f"{spec.id}[{arm}]", build_static_tiers_sh(spec, arm))]


# --------------------------------------------------------------------------
# 1. Emission
# --------------------------------------------------------------------------


def test_every_terraform_shaped_static_tiers_preflights_aws() -> None:
    for spec in _all_specs():
        for arm in spec.arms.enabled_arms():
            if arm not in PREFLIGHT_ARMS:
                continue
            for label, body in _static_tiers_variants(spec, arm):
                assert PREFLIGHT_CMD in body, (
                    f"{label}: {arm} runs terraform against live AWS but its "
                    f"static_tiers.sh has no `{PREFLIGHT_CMD}` preflight, so a "
                    "broken credential chain reaches the toolchain and is "
                    "graded as a wrong answer"
                )


def test_awscdk_static_tiers_has_no_preflight() -> None:
    """`cdk synth --no-lookups` makes no AWS call: a preflight there would make
    awscdk rows void on a credential failure that could not have affected
    them."""
    for spec in _all_specs():
        for arm in spec.arms.enabled_arms():
            if arm != "awscdk":
                continue
            for label, body in _static_tiers_variants(spec, arm):
                assert PREFLIGHT_CMD not in body, f"{label}: unexpected preflight"
                assert MARKER not in body, f"{label}: unexpected aws-unavailable marker"


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_the_region_export_precedes_the_preflight(arm: str) -> None:
    """The staged credentials file carries keys only; nothing else in the
    container sets a region."""
    body = build_static_tiers_sh(load_spec(SPEC_PATH), arm)
    export = body.index('export AWS_DEFAULT_REGION')
    default = body.index(': "${AWS_DEFAULT_REGION:=us-east-1}"')
    call = body.index(PREFLIGHT_CMD)
    assert default < export < call, (
        "AWS_DEFAULT_REGION must be defaulted and exported BEFORE the preflight "
        "-- without a region the `aws` call dies with exit 253 (NoRegion) "
        "before reaching AWS and voids every row"
    )


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_the_preflight_runs_before_any_toolchain_command(arm: str) -> None:
    body = build_static_tiers_sh(load_spec(SPEC_PATH), arm)
    first_tier = body.index("== ")  # every toolchain step announces itself
    assert body.index(PREFLIGHT_CMD) < first_tier
    before = body[: body.index(PREFLIGHT_CMD)]
    assert "> /logs/verifier/reward.txt" not in before, (
        "a reward write precedes the preflight -- a credential failure could "
        "then leave a score behind"
    )


def test_test_sh_short_circuits_on_the_marker_before_any_gating_block() -> None:
    """test.sh does not abort on static_tiers.sh's exit code, so the marker
    check has to sit above every block that can write a reward."""
    for arm in PREFLIGHT_ARMS:
        body = build_test_sh(load_spec(SPEC_PATH), arm)
        guard = body.index(f'if [ -f {MARKER} ]; then')
        call = body.index('"$DIR/static_tiers.sh"')
        assert call < guard, "the marker is only written by static_tiers.sh"
        rewards = [m.start() for m in re.finditer(r"> /logs/verifier/reward\.txt", body)]
        assert rewards, "test.sh writes no reward at all -- rewrite this test"
        assert min(rewards) > guard, (
            f"{arm}: a reward write precedes the aws-unavailable short-circuit, "
            "so an infrastructure failure would be scored instead of voided"
        )


# --------------------------------------------------------------------------
# 2. Execution
# --------------------------------------------------------------------------


def _stage(tmp_path: Path, arm: str) -> tuple[Path, Path, Path]:
    """<root>/tests, <root>/logs, <root>/bin, with /logs and /app/project moved."""
    root = tmp_path / arm
    tests = root / "tests"
    logs = root / "logs"
    bins = root / "bin"
    project = root / "app" / "project"
    for d in (tests, logs / "verifier", bins, project):
        d.mkdir(parents=True, exist_ok=True)
    return tests, logs, bins


def _relocate(body: str, logs: Path, root: Path) -> str:
    moved = body.replace("/logs/", f"{logs}/").replace(
        "/app/project", str(root / "app" / "project")
    )
    assert re.search(r"(?<![\w/])/logs/", moved) is None, (
        "an absolute /logs path survived the rewrite; the test would read or "
        "write the real container paths"
    )
    return moved


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_a_failing_preflight_voids_the_row_and_runs_no_toolchain(
    tmp_path: Path, arm: str
) -> None:
    """THE TEST. No credentials => no reward file, a run_invalid marker, and
    not one toolchain command attempted."""
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    tests, logs, bins = _stage(tmp_path, arm)
    root = tmp_path / arm
    body = _relocate(build_static_tiers_sh(load_spec(SPEC_PATH), arm), logs, root)
    _write_stub(tests / "static_tiers.sh", body)
    (tests / "_assert_lib.sh").write_text("# stub\n")
    ran = root / "toolchain-ran"
    _write_stub(
        bins / "aws",
        f'echo "$AWS_DEFAULT_REGION" > "{root}/region"\nexit 255\n',
    )
    for tool in ("terraform", "npx", "npm", "node"):
        _write_stub(bins / tool, f'echo "$@" >> "{ran}"\nexit 0\n')

    proc = subprocess.run(
        ["bash", str(tests / "static_tiers.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bins}{os.pathsep}{os.environ['PATH']}"},
    )

    assert proc.returncode != 0
    assert not (logs / "verifier" / "reward.txt").exists(), (
        "the preflight left a reward file -- harbor would record a SCORE for a "
        "trial whose toolchain never ran, instead of RewardFileNotFoundError"
    )
    assert not ran.exists(), "a toolchain command ran after the preflight failed"
    assert (logs / "verifier" / "aws-unavailable").is_file()
    marker = json.loads((logs / "verifier" / "aws-unavailable.json").read_text())
    assert marker["outcome"] == "run_invalid"
    assert marker["status"] == "run_invalid"
    assert (root / "region").read_text().strip() == "us-east-1", (
        "the preflight called `aws` with no region -- it would die NoRegion "
        "and void every row"
    )


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_the_marker_makes_test_sh_refuse_to_grade(tmp_path: Path, arm: str) -> None:
    """With gating armed -- the configuration every live-checked task ships --
    the marker must still produce NO reward, not the 0.0 those blocks write."""
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh(tmp_path, arm, aws_available=False)
    assert rc != 0
    assert not (logs / "verifier" / "reward.txt").exists(), (
        "test.sh graded a trial whose credentials were unavailable -- an "
        "infrastructure failure wearing the costume of a wrong answer"
    )


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_without_the_marker_the_same_run_scores_zero(tmp_path: Path, arm: str) -> None:
    """The positive control. Identical inputs minus the marker: the gating
    blocks DO write 0.0, which is what the short-circuit above prevents."""
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh(tmp_path, arm, aws_available=True)
    assert rc != 0
    assert (logs / "verifier" / "reward.txt").read_text().strip() == "0.0"


def _run_test_sh(tmp_path: Path, arm: str, aws_available: bool) -> tuple[int, Path]:
    """Run the REAL emitted test.sh with a stubbed static_tiers.sh that either
    reports AWS unavailable or grades the solution 0.0."""
    tests, logs, _bins = _stage(tmp_path, f"{arm}-{aws_available}")
    root = tests.parent
    body = _relocate(build_test_sh(load_spec(SPEC_PATH), arm), logs, root)
    _write_stub(tests / "test.sh", body)
    if aws_available:
        stub = f'echo "0.0" > "{logs}/verifier/reward.txt"\nexit 1\n'
    else:
        stub = (
            f'echo "aws-unavailable" > "{logs}/verifier/aws-unavailable"\nexit 1\n'
        )
    _write_stub(tests / "static_tiers.sh", stub)
    (logs / "seed-deploy-receipt.json").write_text(
        json.dumps({"outcome": "seed_deployed"})
    )
    proc = subprocess.run(
        ["bash", str(tests / "test.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SPEC_SEED_DEPLOY_REQUIRED": "true",
            "SPEC_LIVE_CHECK_ENABLED": "true",
            "SPEC_LIVE_CHECK_GATING": "true",
            "SPEC_IDEMPOTENCE_ENABLED": "true",
            "SPEC_IDEMPOTENCE_GATING": "true",
        },
    )
    return proc.returncode, logs
