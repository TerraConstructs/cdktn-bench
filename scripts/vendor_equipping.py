#!/usr/bin/env python3
"""Vendor the M2 tuned-equipping material (prereg §2.2, ROADMAP M2).

The tree is COMMITTED under `equipping/` and the generator copies the level a
task opts into straight into that task's `environment/equipping/`, so the host
gates, the equipping hash and the container all read the same bytes and nothing
is fetched at image build time. The pin is the upstream COMMIT SHA plus a
per-file sha256: codeload's gzip bytes differ between a tag archive and a sha
archive of one identical tree, so a tarball digest is not a pin (the same
reasoning as `scripts/vendor_modules.py`).

Modes mirror that script:
  (default)         fetch every vendored pin from codeload and rewrite the tree
                    and `equipping/MANIFEST.json`. Network; owner-run on a bump.
  --verify          re-hash the tree under `--root` against its own MANIFEST.json
                    and fail on a changed, extra or missing file. Offline.
  --check-upstream   resolve each pinned tag to its commit through the GitHub API
                    and report disagreement. Reads only; a moved tag is a
                    finding, not a rewrite.

`bench/` packages carry no upstream commit -- they are written here -- but they
are hashed into MANIFEST.json exactly like a vendored one, because a silent edit
to a bench-written skill is the same integrity problem as a silent edit to a
vendored one.

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_PATH = Path(__file__).resolve().parent / "vendor_equipping.pins.json"
DEFAULT_ROOT = REPO_ROOT / "equipping"
MANIFEST_NAME = "MANIFEST.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digests(root: Path, rel: str) -> dict[str, str]:
    base = root / rel
    return {
        f.relative_to(base).as_posix(): sha256_file(f)
        for f in sorted(base.rglob("*"))
        if f.is_file()
    }


def vendored_packages(pins: dict) -> list[dict]:
    """Pins that name a directory in the tree. A pin with no `dir` is a pinned
    SERVER (an MCP version + launch form), recorded but never copied."""
    return [p for p in pins["packages"] if p.get("dir")]


def build_manifest(pins: dict, root: Path) -> dict:
    packages = []
    for pin in vendored_packages(pins):
        rel = pin["dir"] if "/" in pin["dir"] else f"vendor/{pin['dir']}"
        entry = {
            "name": pin["name"],
            "dir": rel,
            "level": pin["level"],
            "licence": pin["licence"].split(" --")[0],
            "files": tree_digests(root, rel),
        }
        for key in ("upstream_repo", "upstream_tag", "upstream_commit"):
            if pin.get(key):
                entry[key] = pin[key]
        packages.append(entry)
    servers = [
        {
            "name": p["name"],
            "distribution": p["distribution"],
            "version": p["version"],
            "licence": p["licence"],
            "transport": "stdio",
        }
        for p in pins["packages"]
        if p.get("distribution")
    ]
    return {
        "schema": 1,
        "generated_by": "scripts/vendor_equipping.py",
        "packages": sorted(packages, key=lambda e: e["dir"]),
        "servers": sorted(servers, key=lambda e: e["name"]),
    }


def verify(root: Path) -> int:
    manifest = json.loads((root / MANIFEST_NAME).read_text())
    problems: list[str] = []
    for pkg in manifest["packages"]:
        base = root / pkg["dir"]
        if not base.is_dir():
            problems.append(f"{pkg['dir']}: missing directory")
            continue
        on_disk = tree_digests(root, pkg["dir"])
        for rel, want in pkg["files"].items():
            got = on_disk.pop(rel, None)
            if got is None:
                problems.append(f"{pkg['dir']}/{rel}: missing")
            elif got != want:
                problems.append(f"{pkg['dir']}/{rel}: sha256 {got} != {want}")
        problems.extend(f"{pkg['dir']}/{rel}: not in manifest" for rel in sorted(on_disk))
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    if problems:
        return 1
    n = sum(len(p["files"]) for p in manifest["packages"])
    print(f"OK {n} file(s) across {len(manifest['packages'])} package(s) match {MANIFEST_NAME}")
    return 0


def fetch(pin: dict, root: Path) -> None:
    rel = pin["dir"] if "/" in pin["dir"] else f"vendor/{pin['dir']}"
    dest = root / rel
    url = f"https://codeload.github.com/{pin['upstream_repo']}/tar.gz/{pin['upstream_commit']}"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 -- pinned https host
        blob = resp.read()
    subtree = pin["subtree"].strip("./")
    # The skill itself, plus the licence texts from the repository ROOT: Apache-2.0
    # §4(a) requires the licence to accompany the copy, and the copy that ships is
    # the one the generator puts in the container.
    keep = ("SKILL.md", "references/")
    root_keep = ("LICENSE", "NOTICE")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            inner = member.name.split("/", 1)[1] if "/" in member.name else ""
            if inner in root_keep:
                out, data = dest / inner, tar.extractfile(member).read()
            else:
                if subtree and not inner.startswith(subtree + "/"):
                    continue
                tail = inner[len(subtree) + 1 :] if subtree else inner
                if not tail.startswith(keep):
                    continue
                out, data = dest / tail, tar.extractfile(member).read()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)


def check_upstream(pins: dict) -> int:
    rc = 0
    for pin in pins["packages"]:
        if not pin.get("upstream_tag"):
            continue
        url = f"https://api.github.com/repos/{pin['upstream_repo']}/git/ref/tags/{pin['upstream_tag']}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                obj = json.load(resp)["object"]
            if obj["type"] == "tag":
                # An ANNOTATED tag's ref points at the tag OBJECT, not the commit.
                # Reporting that sha as a moved tag is a false finding, which is
                # worse than no check at all.
                with urllib.request.urlopen(obj["url"], timeout=30) as resp:  # noqa: S310
                    obj = json.load(resp)["object"]
            sha = obj["sha"]
        except Exception as exc:  # noqa: BLE001 -- a lookup failure is a finding
            print(f"UNRESOLVED {pin['upstream_repo']}@{pin['upstream_tag']}: {exc}")
            rc = 1
            continue
        state = "OK" if sha == pin["upstream_commit"] else "MOVED"
        rc = rc or (state == "MOVED")
        print(f"{state} {pin['upstream_repo']}@{pin['upstream_tag']} -> {sha}")
    return int(rc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--pins", type=Path, default=PINS_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--check-upstream", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        return verify(args.root)
    pins = json.loads(args.pins.read_text())
    if args.check_upstream:
        return check_upstream(pins)
    for pin in vendored_packages(pins):
        if pin.get("upstream_commit", "").isalnum() and len(pin.get("upstream_commit", "")) == 40:
            fetch(pin, args.root)
    manifest = build_manifest(pins, args.root)
    (args.root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.root / MANIFEST_NAME}")
    return verify(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
