#!/usr/bin/env python3
"""Live, GATING oracle of `ecr-repo-destroy-force-delete` (SCHEMA.md §5).

HAND-AUTHORED: `make gen` never overwrites it, and its bytes must stay
IDENTICAL across the three arms (generator/tests/test_ecr_probe_image.py pins
that). It reads the account, never the workspace or any plan artifact, so it
cannot tell which arm produced the state it grades.

Asserted of the ACCOUNT: exactly one repository scans images on push; every
lifecycle rule expiring by image count keeps 10, of any tag status; an image
built here from two uploaded blobs is accepted and listed. That push is what
makes the teardown tier (SCHEMA.md §5.2) mean anything: the destroy that
follows destroys a NON-EMPTY repository.

Fail-closed. Stdout carries a JSON `outcome`: "pass", "fail_stale" (ECR
contradicted an assertion, or answered an error that IS a verdict) or
"not_verifiable" (`not_verifiable_kind` says why it could not be run). Anything
but "pass" scores 0.0 and an unanswered check voids the row, so an outage is
never scored as a wrong solution. `--expect {ok,stale}` adds a fixture's
non-zero exit; unflagged, `.outcome` is the verdict, not the exit code.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _live_lib import TransientExhausted, run_aws  # noqa: E402

IMAGE_TAG = "verifier-probe"
EXPECTED_COUNT_TYPE = "imageCountMoreThan"
EXPECTED_COUNT_NUMBER = 10
EXPECTED_TAG_STATUS = "any"

MANIFEST_MEDIA_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
CONFIG_MEDIA_TYPE = "application/vnd.docker.container.image.v1+json"
LAYER_MEDIA_TYPE = "application/vnd.docker.image.rootfs.diff.tar.gzip"

# An ECR error that ANSWERS the question is a verdict about the agent's work,
# not an outage: the repository is not there, or it carries no lifecycle policy.
# Everything else resolved is AwsUnavailable, and everything transient is
# retried by _live_lib before it ever reaches here.
VERDICT_ERRORS = ("RepositoryNotFoundException", "LifecyclePolicyNotFoundException")
# Both are re-runs of a call this check already made: the same deterministic
# blobs, the same manifest. Success and "already there" are the same fact.
IDEMPOTENT_ERRORS = ("LayerAlreadyExistsException", "ImageAlreadyExistsException")


class AwsUnavailable(RuntimeError):
    """The `aws` CLI could not be run, or refused the call -- NOT a verdict."""


class Stale(RuntimeError):
    """ECR answered, and the answer contradicts the ticket -- a real verdict."""


def _aws(*args: str, tolerate: tuple[str, ...] = ()) -> Any:
    """One ECR call through the shared transient-retry runner.

    A transient failure is retried inside run_aws and surfaces here only as
    TransientExhausted, once its budget is spent. A resolved failure is mapped
    by its own error code: `tolerate`d codes return None (the call's effect is
    already in place), the codes that answer the question raise Stale, and
    everything else raises AwsUnavailable. Nothing here ever guesses."""
    rc, stdout, stderr = run_aws(list(args))
    if rc != 0:
        if any(code in stderr for code in tolerate):
            return None
        if any(code in stderr for code in VERDICT_ERRORS):
            raise Stale(f"aws {' '.join(args)}: {stderr.strip()[:400]}")
        raise AwsUnavailable(
            f"aws {' '.join(args)}: exit {rc}: {stderr.strip()[:400]}"
        )
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: unparseable output") from exc


# --- the image, built from nothing --------------------------------------
# Two blobs and a Docker schema-2 manifest referencing both, all deterministic:
# re-running this check re-derives the same digests, so ECR answers the second
# push with LayerAlreadyExists / ImageAlreadyExists rather than duplicating it.


def digest(blob: bytes) -> str:
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def layer_blob() -> tuple[bytes, bytes]:
    """`(uncompressed, compressed)` for one empty tar layer.

    A tar archive with no members is two 512-byte zero blocks; gzipped with a
    fixed mtime so the compressed bytes -- and therefore the layer digest -- do
    not move between runs."""
    raw = b"\x00" * 1024
    return raw, gzip.compress(raw, mtime=0)


def config_blob(diff_id: str) -> bytes:
    """The image config the manifest points at: a real, minimal OCI/Docker image
    config naming the one layer's UNCOMPRESSED digest, which is what `diff_ids`
    holds."""
    return json.dumps(
        {
            "architecture": "amd64",
            "os": "linux",
            "config": {},
            "rootfs": {"type": "layers", "diff_ids": [diff_id]},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def manifest(config: bytes, layer: bytes) -> str:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": CONFIG_MEDIA_TYPE,
                "size": len(config),
                "digest": digest(config),
            },
            "layers": [
                {
                    "mediaType": LAYER_MEDIA_TYPE,
                    "size": len(layer),
                    "digest": digest(layer),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _upload_blob(repository: str, blob: bytes) -> None:
    """initiate -> upload part -> complete, the three calls `docker push` makes
    for one blob. A blob ECR already holds completes with
    LayerAlreadyExistsException, which is the same end state."""
    started = _aws("ecr", "initiate-layer-upload", "--repository-name", repository)
    upload_id = started.get("uploadId")
    if not upload_id:
        raise AwsUnavailable(
            f"ecr initiate-layer-upload on {repository!r} returned no uploadId"
        )
    with tempfile.TemporaryDirectory(prefix="ecr-live-check-") as tmp:
        part = os.path.join(tmp, "part.bin")
        with open(part, "wb") as fh:
            fh.write(blob)
        _aws(
            "ecr", "upload-layer-part",
            "--repository-name", repository,
            "--upload-id", upload_id,
            "--part-first-byte", "0",
            "--part-last-byte", str(len(blob) - 1),
            "--layer-part-blob", f"fileb://{part}",
        )
    _aws(
        "ecr", "complete-layer-upload",
        "--repository-name", repository,
        "--upload-id", upload_id,
        "--layer-digests", digest(blob),
        tolerate=IDEMPOTENT_ERRORS,
    )


def push_probe_image(repository: str) -> str:
    """Put one image into `repository` and return its manifest digest.

    Plain ECR API calls, not `docker push`: no arm image ships docker. What the
    teardown tier destroys after this is a repository with an image in it."""
    raw, compressed = layer_blob()
    config = config_blob(digest(raw))
    _upload_blob(repository, config)
    _upload_blob(repository, compressed)
    _aws(
        "ecr", "put-image",
        "--repository-name", repository,
        "--image-tag", IMAGE_TAG,
        "--image-manifest", manifest(config, compressed),
        "--image-manifest-media-type", MANIFEST_MEDIA_TYPE,
        tolerate=IDEMPOTENT_ERRORS,
    )
    return digest(manifest(config, compressed).encode())


# --- the three assertions ------------------------------------------------


def find_repository() -> tuple[str, list[str]]:
    """The one repository this deployment created, found by a property the
    ticket fixes rather than by a name it never chose.

    Scan-on-push is the discriminator, and it is one because of what the
    baseline holds: the shard account's only ECR repository before the agent
    starts is the CDK bootstrap container-assets repository
    (`cdk-hnb659fds-container-assets-<account>-<region>`), whose template sets
    an image-tag-mutability, a lifecycle policy and a repository policy but NO
    image-scanning configuration. So a repository that scans on push is
    necessarily the deployed one, while "the only repository" would be
    ambiguous. Zero and more than one are both verdicts -- ambiguity is
    reported, never resolved by picking the first."""
    data = _aws("ecr", "describe-repositories")
    repos = data.get("repositories", [])
    scanning = [
        r
        for r in repos
        if (r.get("imageScanningConfiguration") or {}).get("scanOnPush") is True
    ]
    names = sorted(str(r.get("repositoryName")) for r in repos)
    if not repos:
        raise Stale("this account holds no ECR repository at all")
    if not scanning:
        raise Stale(
            f"no ECR repository in this account scans images on push (found: {names})"
        )
    if len(scanning) > 1:
        raise Stale(
            "more than one ECR repository scans images on push "
            f"({sorted(str(r.get('repositoryName')) for r in scanning)}) -- which "
            "one the ticket asked for cannot be decided"
        )
    return str(scanning[0]["repositoryName"]), names


def check_lifecycle_policy(repository: str) -> list[dict]:
    """The policy must expire by IMAGE COUNT, and EVERY rule that does so must
    keep exactly 10 across images of any tag status.

    "Only the last 10 images are kept" is a property of the WHOLE policy. A
    check for "some rule keeps 10" is satisfied by a two-rule policy that keeps
    10 untagged images and 100 tagged ones, which retains 100 images -- the
    exact mistake this scenario's wrong-count catch names, passing. A count of
    10 also bounds only the tag class its own rule selects, so a lone
    `untagged`-scoped rule leaves tagged images unbounded while every count in
    the document reads 10; the tag status is checked for that reason. Rules
    that expire by anything other than image count (an age-based untagged
    cleanup, say) are a free choice the ticket never made and are left alone.

    A repository with no policy at all answers with
    LifecyclePolicyNotFoundException, which _aws maps to Stale -- a verdict,
    not an outage."""
    data = _aws("ecr", "get-lifecycle-policy", "--repository-name", repository)
    try:
        rules = json.loads(data.get("lifecyclePolicyText") or "")["rules"]
    except (ValueError, KeyError, TypeError) as exc:
        raise Stale(
            f"the lifecycle policy on {repository!r} is not a document with rules: {exc}"
        ) from exc
    selections = [r.get("selection") or {} for r in rules]
    by_count = [s for s in selections if s.get("countType") == EXPECTED_COUNT_TYPE]
    if not by_count:
        raise Stale(
            f"no lifecycle rule on {repository!r} expires by {EXPECTED_COUNT_TYPE} "
            f"(rules: {selections})"
        )
    wrong = [s for s in by_count if s.get("countNumber") != EXPECTED_COUNT_NUMBER]
    if wrong:
        raise Stale(
            f"a lifecycle rule on {repository!r} expires by {EXPECTED_COUNT_TYPE} at "
            f"a count other than {EXPECTED_COUNT_NUMBER}, so more than "
            f"{EXPECTED_COUNT_NUMBER} images are retained (rules: {selections})"
        )
    scoped = [s for s in by_count if s.get("tagStatus") != EXPECTED_TAG_STATUS]
    if scoped:
        raise Stale(
            f"a lifecycle rule on {repository!r} expires by {EXPECTED_COUNT_TYPE} but "
            f"only for tagStatus other than {EXPECTED_TAG_STATUS!r}, so the images it "
            f"does not select are retained without bound (rules: {selections})"
        )
    return rules


def check_image_listed(repository: str) -> list[str]:
    """`list-images` rather than `describe-images --image-ids imageTag=...`: the
    latter raises ImageNotFoundException for the one answer this check most
    needs to state as a VERDICT, and a raised error would void the row instead
    of scoring it."""
    data = _aws("ecr", "list-images", "--repository-name", repository)
    tags = sorted(
        str(i["imageTag"]) for i in data.get("imageIds", []) if i.get("imageTag")
    )
    if IMAGE_TAG not in tags:
        raise Stale(
            f"the image pushed to {repository!r} is not listed there (tags: {tags})"
        )
    return tags


def observe() -> dict:
    """One pass over the three assertions. Every step fails closed: a resolved
    ECR error that answers the question is Stale, anything else is
    AwsUnavailable, and neither is ever silently continued past."""
    repository, all_repositories = find_repository()
    rules = check_lifecycle_policy(repository)
    manifest_digest = push_probe_image(repository)
    tags = check_image_listed(repository)
    return {
        "outcome": "pass",
        "failures": [],
        "repository": repository,
        "all_repositories": all_repositories,
        "lifecycle_rules": rules,
        "pushed_manifest_digest": manifest_digest,
        "image_tags": tags,
    }


def run() -> dict:
    try:
        return observe()
    except Stale as exc:
        return {"outcome": "fail_stale", "failures": [str(exc)]}
    except TransientExhausted as exc:
        return {
            "outcome": "not_verifiable",
            "not_verifiable_kind": exc.kind,
            "reason": str(exc),
            "failures": [],
        }
    except AwsUnavailable as exc:
        return {
            "outcome": "not_verifiable",
            "not_verifiable_kind": "api-error",
            "reason": str(exc),
            "failures": [],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        choices=["ok", "stale"],
        default=None,
        help="fixture-invoked shape: assert the observed outcome. Exits non-zero "
        "when the account contradicts the assertion.",
    )
    args = parser.parse_args()

    result = run()
    result["scenario"] = "ecr-repo-destroy-force-delete"
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.expect is None:
        # Verifier-invoked: `.outcome` is the verdict, the exit code is not.
        return 0
    if result["outcome"] == "not_verifiable":
        print(
            "live_check: could not read the account -- refusing to confirm or "
            "deny the fixture's assertion",
            file=sys.stderr,
        )
        return 2
    expected = "pass" if args.expect == "ok" else "fail_stale"
    if result["outcome"] != expected:
        print(
            f"live_check: expected outcome {expected!r}, observed "
            f"{result['outcome']!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
