"""generator/tests/test_vendored_modules.py — the committed `terraform-aws-modules`
tree the `hcl_modules` arm serves offline (DECISIONS.md Amendment 46 (b),
`docs/design/hcl-modules-spec-matrix.md` §4, `docs/hcl-modules-vendoring.md`).

Four things are checked, and the deny-list one is narrower than the other three
on purpose — see THE DENY-LIST SCOPE below.

1. THE THREE AGREE — pins, manifest and tree. A version an agent asks the
   responder for is answered from a directory that exists, at a sha someone
   pinned; `scripts/vendor_modules.py --verify` is the same check and runs
   again inside the image, so the host and the container cannot disagree.
2. TRANSITIVE CLOSURE — every non-relative `source` inside a vendored module is
   itself vendored at the exact version its caller pins (`apigateway-v2` calls
   `acm` 6.2.0 unconditionally; `eks` and `route53` both call `kms` 4.0.0).
   A miss here is an `init` that reaches the network, which is the failure this
   whole arm is built to make impossible.
3. CONSTRAINTS — every `required_providers`/`required_version` floor in the
   tree is satisfied by the pinned `hashicorp/aws` and `terraform`, so no
   vendored module can be selected and then fail to install.
4. THE MANIFEST CARRIES NO BENCH TEXT — the responder answers
   `/v1/modules/search` out of `manifest.json`, so that file is an
   AGENT-VISIBLE surface and is swept with the generator's own deny list.

THE DENY-LIST SCOPE, and why the tree is not swept for scenario vocabulary.
The deny list (`spec_model.identity_deny_hits`) exists to stop the BENCH's own
authored text handing an agent a scenario's answer. Upstream Terraform source
is not bench-authored text: `lifecycle`, `create_before_destroy` and
`throttling_burst_limit` are the library's public surface, and discovering
them is the skill this arm measures, not a leak. Asserting their absence would
be asserting that `terraform-aws-modules` is written in some other language.
What IS assertable — and is asserted — is that no vendored byte is ours: every
file's sha256 is in the manifest, and the manifest's commit is the pinned tag's
commit, so the tree's vocabulary is upstream's by construction. The one
bench-authored file in the tree is `manifest.json`, and that is swept in full.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from spec_model import Spec, identity_deny_hits, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULES_ROOT = REPO_ROOT / "arms" / "hcl-modules" / "environment" / "modules"
MANIFEST_PATH = MODULES_ROOT / "manifest.json"
VENDOR_SCRIPT = REPO_ROOT / "scripts" / "vendor_modules.py"

# The arm inherits `arms/hcl-raw`'s image and therefore its pins
# (DECISIONS.md Amendment 48: the mirror moved to 6.66.0 so `eks` 21.25.1's
# `>= 6.59` floor is satisfiable). Read from the Dockerfile rather than
# restated, so a bump cannot leave this file asserting the old pair.
DOCKERFILE = REPO_ROOT / "arms" / "hcl-raw" / "environment" / "Dockerfile"

ALL_SPEC_PATHS = sorted(
    [p for p in (REPO_ROOT / "specs").glob("*.yaml") if p.name != "split.yaml"]
    + list((REPO_ROOT / "specs" / "_toy").glob("*.yaml"))
)
ALL_SPECS: list[Spec] = [load_spec(p) for p in ALL_SPEC_PATHS]

MANIFEST_TEXT: str = MANIFEST_PATH.read_text()
MANIFEST: dict = json.loads(MANIFEST_TEXT)
PINS: dict = json.loads((REPO_ROOT / "scripts" / "vendor_modules.pins.json").read_text())
ENTRIES: list[dict] = MANIFEST["modules"]

# `source = "namespace/name/provider"` inside a module: a REGISTRY call, which
# `init` resolves through the responder. A relative `./`/`../` source is
# satisfied by the tree itself and is not a closure obligation.
REGISTRY_SOURCE_RE = re.compile(
    r'source\s*=\s*"(?P<ns>[\w.-]+)/(?P<name>[\w.-]+)/(?P<prov>[\w.-]+)"'
)
VERSION_ARG_RE = re.compile(r'version\s*=\s*"(?P<v>[^"]+)"')
REQUIRED_VERSION_RE = re.compile(r'required_version\s*=\s*"(?P<v>[^"]+)"')
# A PROVIDER source is two-part (`hashicorp/aws`) and is resolved by the
# image's filesystem mirror, not by the responder — a different regex from
# REGISTRY_SOURCE_RE, which a two-part string cannot match at all.
AWS_PROVIDER_RE = re.compile(
    r'source\s*=\s*"hashicorp/aws"\s+version\s*=\s*"(?P<v>[^"]+)"'
)


def _arg(name: str) -> str:
    """The value of an `ARG <name>=<value>` line in the hcl-raw Dockerfile."""
    match = re.search(rf"^ARG {name}=(\S+)$", DOCKERFILE.read_text(), re.M)
    assert match, f"{DOCKERFILE.name} declares no ARG {name}"
    return match.group(1)


AWS_PROVIDER_VERSION = _arg("AWS_PROVIDER_VERSION")
TERRAFORM_VERSION = _arg("TERRAFORM_VERSION")


def _semver(text: str) -> tuple[int, ...]:
    """A dotted version as a comparable tuple, padded to three parts so
    `>= 6.29` and `6.66.0` compare as the same shape terraform gives them."""
    parts = [int(p) for p in re.findall(r"\d+", text)][:3]
    return tuple(parts + [0] * (3 - len(parts)))


def _satisfies(version: str, constraint: str) -> bool:
    """Terraform's comma-joined constraint syntax, over the operators these
    trees actually use. `~>` is the pessimistic operator: it pins every part
    but the last one the constraint names."""
    target = _semver(version)
    for term in (t.strip() for t in constraint.split(",")):
        match = re.match(r"^(>=|<=|!=|~>|>|<|=)?\s*v?([\d.]+)$", term)
        assert match, f"unparsed version constraint {term!r}"
        op, want_text = match.group(1) or "=", match.group(2)
        want = _semver(want_text)
        if op == ">=" and not target >= want:
            return False
        if op == ">" and not target > want:
            return False
        if op == "<=" and not target <= want:
            return False
        if op == "<" and not target < want:
            return False
        if op == "=" and target != want:
            return False
        if op == "!=" and target == want:
            return False
        if op == "~>":
            named = len(want_text.split("."))
            if target < want or target[: named - 1] != want[: named - 1]:
                return False
    return True


def _entry_id(entry: dict) -> str:
    return f"{entry['name']}@{entry['version']}"


def _tf_files(entry: dict):
    base = MODULES_ROOT / entry["dir"]
    return sorted(p for p in base.rglob("*.tf") if p.is_file())


# ---------------------------------------------------------------------------
# 1. pins, manifest and tree agree
# ---------------------------------------------------------------------------


def test_verify_mode_is_green() -> None:
    """The contract the image build runs: `--verify` recomputes every sha256
    over the committed tree and exits nonzero on drift, on a missing file or
    on one the manifest never listed. Run here as a subprocess, with the same
    argument shape the Dockerfile uses, so the thing the build depends on is
    the thing the suite exercises."""
    proc = subprocess.run(
        [sys.executable, str(VENDOR_SCRIPT), "--verify", "--root", str(MODULES_ROOT)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_pin_is_in_the_manifest_at_its_pinned_commit() -> None:
    by_key = {(e["name"], e["version"]): e for e in ENTRIES}
    for pin in PINS["modules"]:
        entry = by_key.get((pin["name"], pin["version"]))
        assert entry is not None, f"{pin['name']}@{pin['version']} pinned, not vendored"
        assert entry["upstream_commit"] == pin["commit"]
        assert entry["upstream_tag"] == pin["tag"]
    assert len(ENTRIES) == len(PINS["modules"])


def test_the_manifest_does_not_say_which_modules_are_decoys() -> None:
    """The pin file marks four modules as decoys; the manifest must not. It
    ships in the agent image, which runs as root, so a `decoy` flag there is a
    machine-readable answer key for the module-selection skill this arm was
    built to measure — the pilot's bait, labelled as bait."""
    assert any(pin["decoy"] for pin in PINS["modules"])
    assert "decoy" not in MANIFEST_TEXT


def test_every_manifest_entry_is_a_directory_on_disk() -> None:
    for entry in ENTRIES:
        base = MODULES_ROOT / entry["dir"]
        assert base.is_dir(), f"{entry['dir']}: in the manifest, not on disk"
        assert entry["dir"] == f"{entry['name']}-{entry['version']}"
        assert (base / "LICENSE").is_file(), (
            f"{entry['dir']}: Apache-2.0 redistribution inside the image needs "
            "the LICENSE retained through the prune"
        )


def test_every_directory_on_disk_is_in_the_manifest() -> None:
    """The other direction, which is the one a stale refresh breaks: a module
    dropped from the pins leaves its tree behind, and the responder would go on
    serving a version nobody pinned."""
    vendored = {p.name for p in MODULES_ROOT.iterdir() if p.is_dir()}
    assert vendored == {e["dir"] for e in ENTRIES}


def test_pruned_paths_are_absent_from_the_tree() -> None:
    """The prune is what takes 17 MB to about 4; it is also what keeps every
    module's `examples/` — full working configurations — out of the agent's
    reach."""
    pruned_dirs = set(MANIFEST["prune"]["dirs"])
    pruned_suffixes = set(MANIFEST["prune"]["suffixes"])
    for path in MODULES_ROOT.rglob("*"):
        rel = path.relative_to(MODULES_ROOT)
        if path.is_dir():
            assert path.name not in pruned_dirs, f"{rel}: pruned directory present"
        else:
            assert path.suffix.lower() not in pruned_suffixes, f"{rel}: pruned file"


# ---------------------------------------------------------------------------
# 2. transitive closure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_registry_sources_inside_the_tree_are_themselves_vendored(entry: dict) -> None:
    """A module calling another module by registry source sends `init` back to
    the responder, which can only answer from the manifest. `apigateway-v2`'s
    `acm` call carries no `count`/`for_each`, so the dependency is
    unconditional even for a config that never asks for a certificate."""
    vendored = {(e["source"], e["version"]) for e in ENTRIES}
    for path in _tf_files(entry):
        text = path.read_text(errors="ignore")
        for match in REGISTRY_SOURCE_RE.finditer(text):
            source = f"{match['ns']}/{match['name']}/{match['prov']}"
            if match["ns"] != MANIFEST["registry_namespace"]:
                # `hashicorp/aws` inside required_providers is a PROVIDER
                # source in the same three-part shape, served by the image's
                # filesystem mirror rather than by the responder.
                continue
            tail = text[match.end() : match.end() + 200]
            version = VERSION_ARG_RE.search(tail)
            assert version, f"{path}: module call {source} pins no version"
            assert (source, version["v"]) in vendored, (
                f"{path.relative_to(MODULES_ROOT)} calls {source} "
                f"{version['v']}, which is not vendored — `init` would have to "
                "reach the public registry"
            )


def test_the_known_transitive_calls_are_the_ones_found() -> None:
    """Teeth for the sweep above, which checks nothing on the eighteen modules
    that call no other module: the three calls `tf-module-registry-loopback.md`
    §6 found by hand must be exactly the three this regex finds. A fourth
    appearing is a new vendoring obligation; a disappearance is a dead regex."""
    found = set()
    for entry in ENTRIES:
        for path in _tf_files(entry):
            text = path.read_text(errors="ignore")
            for match in REGISTRY_SOURCE_RE.finditer(text):
                if match["ns"] != MANIFEST["registry_namespace"]:
                    continue
                version = VERSION_ARG_RE.search(text[match.end() : match.end() + 200])
                found.add((entry["dir"], match["name"], version["v"] if version else None))
    assert found == {
        ("apigateway-v2-6.1.1", "acm", "6.2.0"),
        ("eks-21.25.1", "kms", "4.0.0"),
        ("route53-6.5.1", "kms", "4.0.0"),
    }


# ---------------------------------------------------------------------------
# 3. constraints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ENTRIES, ids=_entry_id)
def test_provider_and_terraform_floors_are_satisfiable(entry: dict) -> None:
    checked = 0
    for path in _tf_files(entry):
        text = path.read_text(errors="ignore")
        for match in REQUIRED_VERSION_RE.finditer(text):
            checked += 1
            assert _satisfies(TERRAFORM_VERSION, match["v"]), (
                f"{path.relative_to(MODULES_ROOT)}: terraform "
                f"{TERRAFORM_VERSION} does not satisfy {match['v']!r}"
            )
        for match in AWS_PROVIDER_RE.finditer(text):
            checked += 1
            assert _satisfies(AWS_PROVIDER_VERSION, match["v"]), (
                f"{path.relative_to(MODULES_ROOT)}: hashicorp/aws "
                f"{AWS_PROVIDER_VERSION} does not satisfy {match['v']!r}"
            )
    # Every vendored module declares at least one floor. Counting them is what
    # separates "satisfiable" from "the regex matched nothing".
    assert checked, f"{_entry_id(entry)}: no version constraint found to check"


def test_the_pinned_pair_is_the_arm_image_pair() -> None:
    """The floors above are only meaningful against the versions the image
    installs; this pins that the pair was read, not guessed."""
    assert _semver(AWS_PROVIDER_VERSION) >= (6, 59, 0), (
        "eks 21.25.1 constrains hashicorp/aws >= 6.59 (Amendment 48)"
    )
    assert _semver(TERRAFORM_VERSION) >= (1, 11, 1), (
        "rds 7.2.2 constrains terraform >= 1.11.1"
    )


# ---------------------------------------------------------------------------
# 4. the manifest is an agent-visible surface
# ---------------------------------------------------------------------------


HEX_DIGEST_RE = re.compile(r"\b[0-9a-f]{40,64}\b")


def _manifest_authored_text() -> str:
    """The manifest minus its digests. A sha256 is 64 uniformly random hex
    characters, so it contains every short literal eventually — one really does
    contain `429`, a scenario's reserved HTTP status. Scanning machine-generated
    hashes for authored vocabulary is the `package-lock.json` exclusion in
    `test_scenario_identity.py`: noise that would make the scan mean nothing.
    Names, versions, sources, tags, paths and flags all stay in scope."""
    return HEX_DIGEST_RE.sub("<digest>", MANIFEST_PATH.read_text())


def test_manifest_carries_no_scenario_vocabulary() -> None:
    """`manifest.json` is the responder's own database — `/v1/modules/versions`
    and `/v1/modules/search` answer out of it — so every byte in it can reach
    the agent. It is therefore held to the same deny list as `environment/`:
    no mechanism or foreshadowing vocabulary, and none of any scenario's own
    reserved words. Keeping it to names, versions and hashes is what makes
    that pass; a `why this module is here` field would not."""
    text = _manifest_authored_text()
    for spec in ALL_SPECS:
        hits = spec.identity_leaks(text)
        assert not hits, (
            f"manifest.json matches {hits} against {spec.id}'s deny list. The "
            "responder serves this file to the agent; the reasoning belongs in "
            "scripts/vendor_modules.pins.json, which ships in no image."
        )


def test_manifest_names_no_scenario() -> None:
    """The exact, judgment-free half: no spec id and no agent-visible workspace
    identity appears in the manifest, whatever vocabulary it is built from."""
    text = MANIFEST_PATH.read_text().lower()
    for spec in ALL_SPECS:
        assert spec.id not in text, f"manifest.json names the scenario {spec.id}"


def test_the_deny_list_sweep_is_the_generators_own() -> None:
    """The sweep above must stay the function the generator validates specs
    with: a second copy would be a second blind spot, which is the lesson
    `test_scenario_identity.py` was written from."""
    assert ALL_SPECS[0].identity_leaks("create-before-destroy") == identity_deny_hits(
        "create-before-destroy", tuple(ALL_SPECS[0].agent_deny_vocab)
    )
