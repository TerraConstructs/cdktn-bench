"""The asset mirror must cover every pinned build-time download.

`scripts/asset_mirror.py` derives its manifest by parsing the arm Dockerfiles,
so the pins have one owner. These tests are the tripwire for a Dockerfile
rewrite the parser stops recognising: a pin that disappears from the manifest
would silently leave that asset unmirrorable, and the build would go back to
fetching it upstream.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import asset_mirror  # noqa: E402

DOCKERFILES = sorted((REPO_ROOT / "arms").glob("*/environment/Dockerfile"))


@pytest.fixture(scope="module")
def manifest():
    return asset_mirror.derive_manifest()


def test_every_arm_has_a_dockerfile():
    assert len(DOCKERFILES) == 3


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.parent.name)
def test_every_dockerfile_pin_is_in_the_manifest(dockerfile, manifest):
    pins = set(re.findall(r'_SHA256="([0-9a-f]{64})"', dockerfile.read_text()))
    assert pins, f"{dockerfile} declares no sha256 pin"
    mirrored = {a["sha256"] for a in manifest["assets"] if a["sha256"]}
    assert pins <= mirrored, f"pins missing from the manifest: {pins - mirrored}"


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.parent.name)
def test_asset_mirror_default_is_the_fixed_url(dockerfile):
    """One cache key for every builder.

    BuildKit expands ASSET_MIRROR into each RUN string before hashing it, so a
    build that passes the arg and a build that passes none produce different
    layers from this line onward. Nothing passes it: the default below is what
    `make build-arms`, scripts/prebuild-tasks.sh and Harbor's own no-build-arg
    `docker compose build` all hash, which is why a prebuild warms Harbor's
    build at all. scripts/asset-mirror-up.sh serves the same port.
    """
    assert f"ARG ASSET_MIRROR={asset_mirror.DEFAULT_MIRROR_URL}\n" in dockerfile.read_text()


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.parent.name)
def test_every_fetch_probes_the_mirror_then_falls_back(dockerfile):
    """A fetch that skips the probe hits upstream even with a mirror running;
    one that skips the fallback fails the build when no mirror is up."""
    text = dockerfile.read_text()
    fetches = text.count("curl -fsSL --http1.1 --retry 5 --retry-all-errors")
    assert fetches, f"{dockerfile} has no mirror-able fetch"

    candidates = text.count('ASSET_MIRROR_URL="$ASSET_MIRROR/')
    probes = len(re.findall(
        r'curl -fsI --connect-timeout 2 --max-time 5 "\$ASSET_MIRROR_URL"', text))
    assert candidates == fetches, f"{fetches} fetches, {candidates} mirror URLs"
    assert probes == fetches, f"{fetches} fetches, {probes} probes"

    # The upstream URL has to survive a failed probe, which it only does if the
    # mirror URL lands in its own variable that the probe conditionally adopts.
    adoptions = text.count('URL="$ASSET_MIRROR_URL"')
    assert adoptions == fetches, f"{fetches} fetches, {adoptions} fallbacks"


def test_manifest_covers_both_arches_of_every_asset(manifest):
    per_name = {}
    for asset in manifest["assets"]:
        per_name.setdefault(re.sub(r"(aarch64|x86_64|arm64|amd64)", "*", asset["name"]), set()).add(
            asset["arch"]
        )
    for name, arches in per_name.items():
        assert arches == {"amd64", "arm64"}, f"{name} only covers {arches}"


def test_unpinned_assets_are_only_the_aws_cli(manifest):
    """The AWS CLI zip is unversioned upstream; everything else must carry a
    pin, because the pin is what the mirror can never bypass."""
    unpinned = {a["name"] for a in manifest["assets"] if a["sha256"] is None}
    assert unpinned == {"awscli-exe-linux-aarch64.zip", "awscli-exe-linux-x86_64.zip"}


def test_committed_manifest_matches_the_dockerfiles(manifest):
    """assets/manifest.json is a snapshot, never a second source of truth."""
    if not asset_mirror.MANIFEST_PATH.exists():
        pytest.skip("no committed manifest snapshot")
    import json

    snapshot = json.loads(asset_mirror.MANIFEST_PATH.read_text())
    derived = {(a["name"], a["sha256"], a["url"]) for a in manifest["assets"]}
    stored = {(a["name"], a["sha256"], a["url"]) for a in snapshot["assets"]}
    assert derived == stored, "run `python3 scripts/asset_mirror.py manifest --write`"


def test_manifest_subcommand_emits_json():
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "asset_mirror.py"), "manifest"],
        capture_output=True, text=True, check=True,
    ).stdout
    import json

    assert json.loads(out)["assets"]
