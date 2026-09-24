"""The verifier keeps the document it graded, so blast radius stays computable.

Blast radius (gates/blast_radius.py) counts `resource_changes[]`, which lives
only in the plan; a trial that keeps no plan can never have the field backfilled.
The verifier therefore copies the raw artifact -- and the normalised copy beside
it -- into Harbor's collection directory, which lands in the trial's own
`artifacts/`.

Offline and toolchain-free: the REAL emitted verifier with stub binaries on PATH
(generator/tests/verifier_harness.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gates.blast_radius import from_artifacts_dir  # noqa: E402
from spec_model import Spec, load_spec  # noqa: E402
from verifier_harness import stage  # noqa: E402

PLAN = {
    "format_version": "1.2",
    "resource_changes": [
        {"address": "aws_acm_certificate.this", "change": {"actions": ["create"]}},
        {"address": "aws_route53_record.validation", "change": {"actions": ["delete", "create"]}},
    ],
}
TEMPLATE = {"Resources": {"Cert": {"Type": "AWS::CertificateManager::Certificate"}}}


@pytest.fixture(scope="module")
def pilot() -> Spec:
    return load_spec(REPO_ROOT / "specs" / "acm-dns-validation-record-wiring.yaml")


def artifacts_dir(box) -> Path:
    """Where the verifier writes; `/logs/artifacts` in a real container, derived
    from the one repointed `/logs/verifier` export the harness rewrites."""
    return box.root / "logs" / "artifacts"


def graded_run(box, document) -> None:
    """A run whose verdict is 1.0 and whose only interesting output is what it
    kept: toolchain and preflight dropped, tier 0 forced green."""
    box.static_tiers("1.0")
    box.artifact(document)


@pytest.mark.parametrize(
    "arm,document,name",
    [
        ("hcl_raw", PLAN, "plan.json"),
        ("hcl_modules", PLAN, "plan.json"),
        ("terraconstructs", PLAN, "plan.json"),
        ("awscdk", TEMPLATE, "ScenarioStack.template.json"),
    ],
)
def test_the_graded_document_is_kept_byte_for_byte(tmp_path, pilot, arm, document, name) -> None:
    box = stage(tmp_path, pilot, arm)
    graded_run(box, document)
    source = box.artifact(document)

    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "1.0"
    kept = artifacts_dir(box) / name
    assert kept.is_file()
    assert kept.read_bytes() == source.read_bytes()


def test_the_normalised_copy_is_kept_beside_the_raw_one(tmp_path, pilot) -> None:
    """Both, because they answer different questions: the tiers graded the
    normalised document and blast radius is read from the raw one."""
    box = stage(tmp_path, pilot, "hcl_modules")
    graded_run(box, PLAN)
    box.artifact(PLAN)

    box.run("static_tiers.sh")

    kept = sorted(p.name for p in artifacts_dir(box).iterdir())
    assert kept == ["plan.json", "plan.normalised.json"]


def test_what_is_kept_is_what_blast_radius_reads(tmp_path, pilot) -> None:
    box = stage(tmp_path, pilot, "hcl_raw")
    graded_run(box, PLAN)
    box.artifact(PLAN)

    box.run("static_tiers.sh")

    radius, path = from_artifacts_dir(artifacts_dir(box))
    assert path.name == "plan.json"
    assert radius["total"] == 2
    assert radius["counts"]["replace"] == 1
    assert radius["counts"]["create"] == 1


def test_a_run_with_no_artifact_keeps_nothing_and_still_scores_zero(tmp_path, pilot) -> None:
    box = stage(tmp_path, pilot, "hcl_raw")
    box.static_tiers("1.0")
    box.patch_config(artifact="never-written.json")

    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "0.0"
    assert "MISSING ARTIFACT" in result.stdout
    assert not artifacts_dir(box).exists()


def test_a_copy_that_cannot_be_written_never_changes_the_reward(tmp_path, pilot) -> None:
    """The artifact is evidence for a measurement, never a grading input: a full
    disk must not turn a correct solution into a 0.0."""
    box = stage(tmp_path, pilot, "hcl_raw")
    graded_run(box, PLAN)
    box.artifact(PLAN)
    blocked = box.root / "blocked"
    blocked.write_text("not a directory\n")

    result = box.run(
        "static_tiers.sh",
        env={"CDKTN_VERIFIER_ARTIFACTS_DIR": str(blocked / "artifacts")},
    )

    assert result.reward.strip() == "1.0"
    assert "ARTIFACT NOT PERSISTED" in result.stdout


def test_the_kept_plan_is_json_the_reader_can_parse(tmp_path, pilot) -> None:
    box = stage(tmp_path, pilot, "hcl_raw")
    graded_run(box, PLAN)
    box.artifact(PLAN)

    box.run("static_tiers.sh")

    assert json.loads((artifacts_dir(box) / "plan.json").read_text()) == PLAN
