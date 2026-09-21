"""generator/tests/test_aws_preflight.py -- the AWS PREFLIGHT contract
(DECISIONS.md Amendment 32 "live AWS is the only trial mode", aws-access.html).

A missing ambient credential chain is test INFRASTRUCTURE failing, not a bad
solution: it must VOID the row -- no reward file at all, so harbor raises
RewardFileNotFoundError -- rather than score 0.0, which is indistinguishable
from a wrong answer. Three things hold that together:

  1. the verifier defaults a region, then preflights
     `aws sts get-caller-identity`, in every arm whose verifier reaches AWS --
     both Terraform-shaped arms always, awscdk whenever the spec enables a
     live check. Without the region the preflight itself dies `NoRegion` and
     voids every row, perfect solutions included.
  2. The preflight writes NO reward.txt and runs BEFORE any toolchain command.
  3. The whole verifier short-circuits on the marker, so the void cannot decay
     into a zero via the live_check / idempotence gating blocks that write `0.0`.

Offline and toolchain-free: the real emitted verifier, with stub binaries on
PATH (generator/tests/verifier_harness.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import build_verify_config, step_live_check  # noqa: E402
from spec_model import Spec, load_spec  # noqa: E402
from verifier_harness import stage  # noqa: E402

SPEC_PATH = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
PREFLIGHT_CMD = "aws sts get-caller-identity"
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


def _static_tiers_variants(spec: Spec, arm: str) -> list[tuple[str, dict]]:
    """(label, config) for the single-step verifier or every step's."""
    if spec.is_multi_step():
        return [
            (f"{spec.id}[{arm}][step {s.name}]", build_verify_config(spec, arm, s))
            for s in (spec.steps or [])
        ]
    return [(f"{spec.id}[{arm}]", build_verify_config(spec, arm))]


def _live_variants(spec: Spec, arm: str, *, live: bool) -> list[tuple[str, dict]]:
    """The verifiers whose own resolved live check is (or is not) enabled --
    per STEP, since a step may opt out of the spec-level one."""
    if spec.is_multi_step():
        return [
            (f"{spec.id}[{arm}][step {s.name}]", build_verify_config(spec, arm, s))
            for s in (spec.steps or [])
            if step_live_check(spec, s).enabled is live
        ]
    if spec.verifier.live_check.enabled is not live:
        return []
    return [(f"{spec.id}[{arm}]", build_verify_config(spec, arm))]


# --------------------------------------------------------------------------
# 1. Emission
# --------------------------------------------------------------------------


def test_every_terraform_shaped_static_tiers_preflights_aws() -> None:
    for spec in _all_specs():
        for arm in spec.arms.enabled_arms():
            if arm not in PREFLIGHT_ARMS:
                continue
            for label, cfg in _static_tiers_variants(spec, arm):
                assert cfg["aws_preflight"], (
                    f"{label}: {arm} runs terraform against live AWS but its "
                    f"verifier declares no `{PREFLIGHT_CMD}` preflight, so a "
                    "broken credential chain reaches the toolchain and is "
                    "graded as a wrong answer"
                )


def test_awscdk_without_a_live_check_has_no_preflight() -> None:
    """`cdk synth --no-lookups` makes no AWS call: a preflight there would make
    awscdk rows void on a credential failure that could not have affected
    them."""
    for spec in _all_specs():
        if "awscdk" not in spec.arms.enabled_arms():
            continue
        for label, cfg in _live_variants(spec, "awscdk", live=False):
            assert not cfg["aws_preflight"], f"{label}: unexpected preflight"


def test_awscdk_with_a_live_check_preflights_too() -> None:
    """A live check calls AWS from the awscdk verifier as well. Without the
    preflight, the same credential fault that VOIDS an hcl_raw row reaches
    live_check.py as an api-error and test.sh's gating block publishes it as
    reward 0.0 -- one arm scored as an agent failure for the infrastructure
    fault the other arm is excused for."""
    checked = 0
    for spec in _all_specs():
        if "awscdk" not in spec.arms.enabled_arms():
            continue
        for label, cfg in _live_variants(spec, "awscdk", live=True):
            assert cfg["aws_preflight"], (
                f"{label}: this awscdk verifier runs a live check that calls "
                "AWS, but declares no preflight, so a broken credential chain "
                "is graded as a wrong answer"
            )
            checked += 1
    assert checked, "no awscdk arm with a live check -- this test would be vacuous"


# --------------------------------------------------------------------------
# 2. Execution -- the real emitted verifier, with stub binaries
# --------------------------------------------------------------------------


def _failing_aws(box, record: Path):
    """An `aws` that records the region it was handed and then fails, so one run
    answers both "was a region set" and "what does a credential failure do"."""
    box.stub("aws", f'echo "$AWS_DEFAULT_REGION" > "{record}"\nexit 255')


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_the_region_precedes_the_preflight(tmp_path: Path, arm: str) -> None:
    """The staged credentials file carries keys only; nothing else in the
    container sets a region, so without this the `aws` call dies with exit 253
    (NoRegion) before reaching AWS and voids every row."""
    box = stage(tmp_path, load_spec(SPEC_PATH), arm)
    region = box.root / "region"
    _failing_aws(box, region)
    box.run("static_tiers.sh")
    assert region.read_text().strip() == "us-east-1"


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_a_failing_preflight_voids_the_row_and_runs_no_toolchain(
    tmp_path: Path, arm: str
) -> None:
    """THE TEST. No credentials => no reward file, a run_invalid marker, and not
    one toolchain command attempted."""
    box = stage(tmp_path, load_spec(SPEC_PATH), arm)
    ran = box.root / "toolchain-ran"
    _failing_aws(box, box.root / "region")
    for tool in ("terraform", "npx", "npm", "node"):
        box.stub(tool, f'echo "$@" >> "{ran}"\nexit 0')

    res = box.run("static_tiers.sh")

    assert res.rc != 0
    assert res.reward is None, (
        "the preflight left a reward file -- harbor would record a SCORE for a "
        "trial whose toolchain never ran, instead of RewardFileNotFoundError"
    )
    assert not ran.exists(), "a toolchain command ran after the preflight failed"
    assert res.marker("aws-unavailable") is not None
    marker = res.result_json("aws-unavailable.json")
    assert marker["outcome"] == "run_invalid"
    assert marker["status"] == "run_invalid"
    assert res.summary is None, "the tiers ran after the preflight failed"


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_the_marker_makes_the_verifier_refuse_to_grade(
    tmp_path: Path, arm: str
) -> None:
    """With gating armed -- the configuration every live-checked task ships --
    the marker must still produce NO reward, not the 0.0 those blocks write."""
    box = stage(tmp_path, load_spec(SPEC_PATH), arm)
    _failing_aws(box, box.root / "region")
    box.seed_receipt(outcome="seed_deployed")
    res = box.run("test.sh", env=_GATING_ARMED)
    assert res.rc != 0
    assert res.reward is None, (
        "the verifier graded a trial whose credentials were unavailable -- an "
        "infrastructure failure wearing the costume of a wrong answer"
    )


@pytest.mark.parametrize("arm", PREFLIGHT_ARMS)
def test_without_the_marker_the_same_run_scores_zero(tmp_path: Path, arm: str) -> None:
    """The positive control. Identical inputs minus the marker: the gating
    blocks DO write 0.0, which is what the short-circuit above prevents."""
    box = stage(tmp_path, load_spec(SPEC_PATH), arm)
    box.seed_receipt(outcome="seed_deployed")
    # A legitimate non-pass live verdict, so the gating path is what decides.
    box.tests.joinpath("live_check.py").write_text(
        "import json\nprint(json.dumps({'outcome': 'fail_stale'}))\n"
    )
    res = box.run("test.sh", env=_GATING_ARMED)
    assert res.rc != 0
    assert res.reward == "0.0\n"


_GATING_ARMED = {
    "SPEC_SEED_DEPLOY_REQUIRED": "true",
    "SPEC_LIVE_CHECK_ENABLED": "true",
    "SPEC_LIVE_CHECK_GATING": "true",
    "SPEC_IDEMPOTENCE_ENABLED": "true",
    "SPEC_IDEMPOTENCE_GATING": "true",
}
