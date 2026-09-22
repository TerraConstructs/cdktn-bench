#!/usr/bin/env python3
"""Vendor the `terraform-aws-modules` set the `hcl_modules` arm serves offline.

The tree is COMMITTED under `arms/hcl-modules/environment/modules/` and the
image COPYs it, so the host gates and the container share bytes by
construction and no module byte is fetched at image build time (DECISIONS.md
Amendment 46 (b)). The pin is the upstream COMMIT SHA plus a per-file sha256
over the pruned tree: codeload's gzip bytes differ between the `refs/tags/vX`
and `<sha>` archives of one identical tree, so a tarball digest is not a pin
(`docs/design/tf-module-registry-loopback.md` §5).

Modes:
  (default)         fetch every pin from codeload, prune, write the tree and
                    `manifest.json`. Network; owner-run on a version bump.
  --verify          re-hash the tree under `--root` against its own
                    `manifest.json` and fail on drift, on an extra file or on
                    a missing one. Offline, stdlib only, no pin file needed —
                    this is the mode the image build runs against
                    `/opt/terraform-modules`.
  --check-upstream  resolve each pinned tag to its commit through the GitHub
                    API and report disagreement with the pinned sha. Reads
                    only; a moved tag is a finding, not a rewrite.

Stdlib only and no non-`--root` path assumptions in `--verify`, because that
mode runs inside the arm image where this file is the only Python that ships.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_PATH = Path(__file__).resolve().parent / "vendor_modules.pins.json"
DEFAULT_ROOT = REPO_ROOT / "arms" / "hcl-modules" / "environment" / "modules"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1

CODELOAD = "https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
GITHUB_TAG_REF = "https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag}"

# The prune list of `tf-module-registry-loopback.md` §5, which took the pruned
# tree through a real offline `init` + `validate`. Everything a module needs at
# plan time is `.tf`/`.tftpl` plus the odd bundled `.json`/`.py`/`.sh`; what
# goes is documentation and the module's own test/example scaffolding, which is
# most of the 17 MB. LICENSE is retained in every tree — Apache-2.0 asks for it
# and redistribution inside the image is the whole point.
PRUNE_DIRS = frozenset({"examples", "tests", "wrappers", "docs", ".github"})
PRUNE_SUFFIXES = frozenset({".md", ".png"})

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _fail(msg: str) -> None:
    print(f"vendor_modules: {msg}", file=sys.stderr)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(url: str, *, accept: str | None = None, auth: bool = False) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cdktn-bench-vendor"})
    if accept:
        req.add_header("Accept", accept)
    # Unauthenticated api.github.com allows 60 requests an hour per IP, which
    # 21 tag lookups can exhaust; the token is read from the environment and
    # never recorded. Absent, the request is simply made anonymously.
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")) if auth else None
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# pins
# ---------------------------------------------------------------------------


def load_pins(path: Path = PINS_PATH) -> dict:
    pins = json.loads(path.read_text())
    seen: set[tuple[str, str]] = set()
    for mod in pins["modules"]:
        key = (mod["name"], mod["version"])
        if key in seen:
            raise ValueError(f"duplicate pin {key[0]}@{key[1]} in {path}")
        seen.add(key)
        if not SHA_RE.match(mod["commit"]):
            raise ValueError(f"{key[0]}@{key[1]}: commit must be a 40-hex sha")
    return pins


def module_dirname(name: str, version: str) -> str:
    return f"{name}-{version}"


def registry_source(pins: dict, name: str) -> str:
    return f"{pins['registry_namespace']}/{name}/{pins['registry_provider']}"


def repo_name(pins: dict, name: str) -> str:
    return f"{pins['repo_prefix']}{name}"


# ---------------------------------------------------------------------------
# prune + extract
# ---------------------------------------------------------------------------


def is_pruned(relpath: str) -> bool:
    """True for a path the vendored tree drops. Directory names match at ANY
    depth: `modules/x/examples/` is example scaffolding exactly as the root's
    `examples/` is."""
    parts = relpath.split("/")
    if any(part in PRUNE_DIRS for part in parts[:-1]):
        return True
    return Path(parts[-1]).suffix.lower() in PRUNE_SUFFIXES


def extract_pruned(tar_bytes: bytes) -> dict[str, bytes]:
    """The pruned tree of one codeload archive, as {relative posix path: bytes}.

    Members are read one by one rather than `extractall`ed: the destination is
    built from a path this function has already checked, so a crafted archive
    cannot write outside the module directory.
    """
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                # Symlinks and devices never appear in these trees; a new one
                # would change what the image ships, so it is refused loudly.
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError(f"unsupported archive member: {member.name}")
                continue
            # codeload wraps everything in one `<repo>-<sha>/` directory.
            rel = member.name.split("/", 1)[1] if "/" in member.name else ""
            if not rel or rel.startswith("../") or "/../" in rel:
                raise ValueError(f"unsafe archive member: {member.name}")
            if is_pruned(rel):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"unreadable archive member: {member.name}")
            files[rel] = extracted.read()
    return files


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def manifest_entry(pins: dict, mod: dict, files: dict[str, bytes]) -> dict:
    """One module's row. Deliberately carries NO bench-authored judgement about
    a module: the responder answers `/v1/modules/search` out of this file, and
    the file itself is readable in the agent container (Amendment 46 (c)'s
    "unreadable to the agent user" is void while every arm runs as root). A
    `why` field naming a scenario would leak that scenario's reserved
    vocabulary, and a `decoy` flag is the selection answer outright — the arm
    measures whether a model picks the right module, so a machine-readable list
    of the wrong ones is that measurement handed away. Both live only in the
    pin file, which is a host-side input and reaches no build context."""
    return {
        "name": mod["name"],
        "version": mod["version"],
        "source": registry_source(pins, mod["name"]),
        "dir": module_dirname(mod["name"], mod["version"]),
        "upstream_repo": f"{pins['repo_owner']}/{repo_name(pins, mod['name'])}",
        "upstream_tag": mod["tag"],
        "upstream_commit": mod["commit"],
        "files": {path: _sha256(files[path]) for path in sorted(files)},
    }


def write_manifest(root: Path, pins: dict, entries: list[dict]) -> None:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_by": "scripts/vendor_modules.py",
        "registry_namespace": pins["registry_namespace"],
        "registry_provider": pins["registry_provider"],
        "prune": {
            "dirs": sorted(PRUNE_DIRS),
            "suffixes": sorted(PRUNE_SUFFIXES),
        },
        "modules": sorted(entries, key=lambda e: (e["name"], e["version"])),
    }
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")


def read_manifest(root: Path) -> dict:
    manifest = json.loads((root / MANIFEST_NAME).read_text())
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(
            f"{root / MANIFEST_NAME}: schema {manifest.get('schema')!r}, "
            f"this script writes and reads {MANIFEST_SCHEMA}"
        )
    return manifest


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------


def cmd_fetch(root: Path, pins: dict) -> int:
    entries: list[dict] = []
    total_bytes = 0
    for mod in pins["modules"]:
        repo = repo_name(pins, mod["name"])
        url = CODELOAD.format(
            owner=pins["repo_owner"], repo=repo, ref=mod["commit"]
        )
        try:
            tar_bytes = _get(url)
        except urllib.error.URLError as exc:
            _fail(f"{mod['name']}@{mod['version']}: {url}: {exc}")
            return 1
        files = extract_pruned(tar_bytes)
        if "LICENSE" not in files:
            _fail(f"{mod['name']}@{mod['version']}: no LICENSE in the pruned tree")
            return 1
        target = root / module_dirname(mod["name"], mod["version"])
        _replace_tree(target, files)
        total_bytes += sum(len(b) for b in files.values())
        entries.append(manifest_entry(pins, mod, files))
        print(
            f"{mod['name']}@{mod['version']} {mod['commit'][:12]} "
            f"{len(files)} files {sum(len(b) for b in files.values()) // 1024} KiB"
        )
    write_manifest(root, pins, entries)
    print(
        f"{len(entries)} modules, {total_bytes // 1024} KiB pruned, "
        f"manifest at {root / MANIFEST_NAME}"
    )
    return 0


def _replace_tree(target: Path, files: dict[str, bytes]) -> None:
    """Write the pruned tree, removing whatever stood there first: a refresh
    that only overwrote would leave a file the new version deleted behind, and
    `--verify` would then fail on the stale extra."""
    if target.exists():
        _rmtree(target)
    for rel, data in files.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _rmtree(path: Path) -> None:
    for child in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        child.rmdir() if child.is_dir() else child.unlink()
    path.rmdir()


def cmd_verify(root: Path) -> int:
    manifest = read_manifest(root)
    problems: list[str] = []
    expected_dirs = {entry["dir"] for entry in manifest["modules"]}
    for entry in manifest["modules"]:
        base = root / entry["dir"]
        if not base.is_dir():
            problems.append(f"{entry['dir']}: missing from the tree")
            continue
        on_disk = {
            str(p.relative_to(base).as_posix())
            for p in base.rglob("*")
            if p.is_file()
        }
        for rel, want in entry["files"].items():
            path = base / rel
            if not path.is_file():
                problems.append(f"{entry['dir']}/{rel}: missing")
                continue
            got = _sha256(path.read_bytes())
            if got != want:
                problems.append(f"{entry['dir']}/{rel}: sha256 {got} != {want}")
        for rel in sorted(on_disk - set(entry["files"])):
            problems.append(f"{entry['dir']}/{rel}: not in the manifest")
        if "LICENSE" not in entry["files"]:
            problems.append(f"{entry['dir']}: manifest lists no LICENSE")
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in expected_dirs:
            problems.append(f"{child.name}: directory not in the manifest")
    for problem in problems:
        _fail(problem)
    if problems:
        _fail(f"{len(problems)} problem(s) under {root}")
        return 1
    files = sum(len(entry["files"]) for entry in manifest["modules"])
    print(f"verify OK: {len(manifest['modules'])} modules, {files} files, {root}")
    return 0


def cmd_check_upstream(pins: dict) -> int:
    drift = 0
    for mod in pins["modules"]:
        repo = repo_name(pins, mod["name"])
        url = GITHUB_TAG_REF.format(
            owner=pins["repo_owner"], repo=repo, tag=mod["tag"]
        )
        try:
            ref = json.loads(
                _get(url, accept="application/vnd.github+json", auth=True)
            )
        except urllib.error.URLError as exc:
            _fail(f"{mod['name']}@{mod['version']}: {url}: {exc}")
            return 2
        obj = ref["object"]
        # An annotated tag's ref points at the tag object, whose own sha is not
        # the commit; these repos tag lightweight, so anything else is drift to
        # look at rather than a sha to compare.
        if obj["type"] != "commit":
            print(f"DRIFT {mod['name']}@{mod['version']}: {mod['tag']} is a "
                  f"{obj['type']}, not a lightweight tag")
            drift += 1
        elif obj["sha"] != mod["commit"]:
            print(f"DRIFT {mod['name']}@{mod['version']}: {mod['tag']} -> "
                  f"{obj['sha']}, pinned {mod['commit']}")
            drift += 1
        else:
            print(f"ok    {mod['name']}@{mod['version']} {mod['tag']} {obj['sha']}")
    if drift:
        _fail(f"{drift} pin(s) disagree with upstream")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="the directory holding <name>-<version>/ and manifest.json "
        f"(default: {DEFAULT_ROOT.relative_to(REPO_ROOT)}; "
        "/opt/terraform-modules inside the arm image)",
    )
    parser.add_argument("--pins", type=Path, default=PINS_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--check-upstream", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return cmd_verify(args.root)
    pins = load_pins(args.pins)
    if args.check_upstream:
        return cmd_check_upstream(pins)
    args.root.mkdir(parents=True, exist_ok=True)
    return cmd_fetch(args.root, pins)


if __name__ == "__main__":
    sys.exit(main())
