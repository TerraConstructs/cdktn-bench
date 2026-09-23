"""The probe image `ecr-repo-destroy-force-delete`'s live check pushes.

That push is not decoration: the teardown tier destroys what it leaves behind,
and "removing this configuration leaves the account clean" is only a real
question against a repository that CONTAINS something. If the manifest ECR is
handed does not describe the two blobs actually uploaded, `put-image` is
rejected, the live check reports fail_stale, and every trial on the scenario
scores 0.0 for a reason that is the harness's and not the agent's.

So these cases pin what a real push depends on: the manifest's digests and
sizes are those of the exact bytes uploaded, the config names the layer's
UNCOMPRESSED digest in `rootfs.diff_ids` as a Docker/OCI image config must,
and every byte is deterministic, so a re-run re-derives the same digests and
ECR answers "already exists" rather than accumulating images.

No `aws` CLI and no network: the pure builders are called directly, and the
one impure check exercised here (the lifecycle-policy verdict) is fed a
handwritten ECR response through its own call helper.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

import gen
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
# Resolved through the generator, never spelled out: a task's shard is
# `generator/shards.toml` arithmetic, so literal paths here go stale the next
# time a shard is added and the failure reads as a missing file.
_SPEC = load_spec(REPO_ROOT / "specs" / "ecr-repo-destroy-force-delete.yaml")
ARM_CHECKS = [
    gen.task_dir(_SPEC, arm) / "tests" / "live_check.py"
    for arm in _SPEC.arms.enabled_arms()
]


@pytest.fixture(scope="module")
def live_check(tmp_path_factory):
    """Imported from a COPY. The module puts its own directory on sys.path to
    reach tests/_live_lib.py, so importing it in place would leave a
    __pycache__ inside a generated task directory -- which is hashed against a
    provisioned account."""
    staged = tmp_path_factory.mktemp("live-check")
    shutil.copy(ARM_CHECKS[0], staged / "live_check.py")
    shutil.copy(ARM_CHECKS[0].parent / "_live_lib.py", staged / "_live_lib.py")
    spec = importlib.util.spec_from_file_location(
        "ecr_live_check", staged / "live_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_three_arms_ship_the_same_bytes() -> None:
    """A live oracle that could tell which arm produced the account state it is
    grading would be measuring the arms differently, which is the one thing
    this benchmark's headline number may never do."""
    bodies = {p: p.read_bytes() for p in ARM_CHECKS}
    assert len(set(bodies.values())) == 1, sorted(str(p) for p in bodies)


def test_the_layer_is_an_empty_tar_gzipped_deterministically(live_check) -> None:
    raw, compressed = live_check.layer_blob()
    assert raw == b"\x00" * 1024, "a tar with no members is two 512-byte zero blocks"
    assert gzip.decompress(compressed) == raw
    assert live_check.layer_blob()[1] == compressed, "gzip mtime must be pinned"


def test_the_config_names_the_uncompressed_layer_digest(live_check) -> None:
    raw, _ = live_check.layer_blob()
    config = json.loads(live_check.config_blob(live_check.digest(raw)))
    assert config["rootfs"] == {
        "type": "layers",
        "diff_ids": ["sha256:" + hashlib.sha256(raw).hexdigest()],
    }
    assert config["os"] == "linux"


def test_the_manifest_describes_the_bytes_that_were_uploaded(live_check) -> None:
    raw, compressed = live_check.layer_blob()
    config = live_check.config_blob(live_check.digest(raw))
    doc = json.loads(live_check.manifest(config, compressed))

    assert doc["schemaVersion"] == 2
    assert doc["mediaType"] == live_check.MANIFEST_MEDIA_TYPE
    assert doc["config"]["digest"] == "sha256:" + hashlib.sha256(config).hexdigest()
    assert doc["config"]["size"] == len(config)
    assert len(doc["layers"]) == 1
    assert doc["layers"][0]["digest"] == "sha256:" + hashlib.sha256(compressed).hexdigest()
    assert doc["layers"][0]["size"] == len(compressed)


def test_every_byte_is_deterministic(live_check) -> None:
    raw, compressed = live_check.layer_blob()
    config = live_check.config_blob(live_check.digest(raw))
    assert live_check.manifest(config, compressed) == live_check.manifest(config, compressed)
    assert live_check.config_blob(live_check.digest(raw)) == config


def test_an_error_that_answers_the_question_is_a_verdict_not_an_outage(live_check) -> None:
    """Fail-closed has a second half: a repository that is not there, or carries
    no lifecycle policy, is a real finding about the agent's work and must NOT
    be laundered into not_verifiable, which voids the row instead of scoring
    it."""
    assert "RepositoryNotFoundException" in live_check.VERDICT_ERRORS
    assert "LifecyclePolicyNotFoundException" in live_check.VERDICT_ERRORS
    assert set(live_check.IDEMPOTENT_ERRORS) == {
        "LayerAlreadyExistsException",
        "ImageAlreadyExistsException",
    }


# ---------------------------------------------------------------------------
# The retained count is a property of the WHOLE policy
# ---------------------------------------------------------------------------
# "Only the last 10 images are kept" is not "some rule keeps 10": a policy that
# keeps 10 untagged images and 100 tagged ones satisfies the second reading
# while retaining 100 -- the wrong-count catch, passing. Both this check and
# the tier-0 assert read every image-count rule for that reason, and these
# cases pin the two directions apart.


def _policy(rules):
    """Answer `get-lifecycle-policy` with `rules`, in ECR's own shape: the
    document arrives as a JSON STRING inside the response."""
    return {"lifecyclePolicyText": json.dumps({"rules": rules})}


def _rule(tag_status, count_type, count_number):
    return {
        "selection": {
            "tagStatus": tag_status,
            "countType": count_type,
            "countNumber": count_number,
        },
        "action": {"type": "expire"},
    }


@pytest.fixture
def policy_check(live_check, monkeypatch):
    """`check_lifecycle_policy` with its one AWS call replaced by a canned
    response, so the verdict logic is what is under test."""

    def run(rules):
        monkeypatch.setattr(
            live_check, "_aws", lambda *a, **kw: _policy(rules)
        )
        return live_check.check_lifecycle_policy("repo")

    return run


def test_the_asked_for_policy_passes(policy_check) -> None:
    assert policy_check([_rule("any", "imageCountMoreThan", 10)])


def test_a_second_rule_the_ticket_never_asked_for_is_not_punished(policy_check) -> None:
    """An age-based untagged cleanup is a free choice: it retains no images by
    count, and its `countNumber` is a number of DAYS."""
    assert policy_check(
        [
            _rule("any", "imageCountMoreThan", 10),
            _rule("untagged", "sinceImagePushed", 14),
        ]
    )


def test_a_second_image_count_rule_keeping_more_is_stale(live_check, policy_check) -> None:
    with pytest.raises(live_check.Stale, match="other than 10"):
        policy_check(
            [
                _rule("tagged", "imageCountMoreThan", 100),
                _rule("untagged", "imageCountMoreThan", 10),
            ]
        )


def test_no_image_count_rule_at_all_is_stale(live_check, policy_check) -> None:
    with pytest.raises(live_check.Stale, match="imageCountMoreThan"):
        policy_check([_rule("untagged", "sinceImagePushed", 14)])


def test_a_policy_that_is_not_a_document_with_rules_is_stale(
    live_check, monkeypatch
) -> None:
    monkeypatch.setattr(live_check, "_aws", lambda *a, **kw: {})
    with pytest.raises(live_check.Stale, match="not a document with rules"):
        live_check.check_lifecycle_policy("repo")
