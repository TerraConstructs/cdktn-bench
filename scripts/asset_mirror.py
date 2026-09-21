#!/usr/bin/env python3
"""Local mirror for the build-time assets the arm images download.

The arm Dockerfiles are the single source of truth: every pinned fetch is
parsed out of `arms/*/environment/Dockerfile` (URL, per-arch sha256, the
container path curl writes to), so this file can never drift from a pin.

The mirror is a SOURCE, never an authority. A Dockerfile fetching through
`ASSET_MIRROR` still runs the same hardcoded `sha256sum -c`, so a corrupt or
substituted mirror file fails the build exactly as a corrupt download does.
The AWS CLI zip is unpinned upstream and stays unpinned here; the sha this
mirror observed is recorded in the written manifest as information only.

Subcommands:
  manifest [--write]   derive the asset list (optionally snapshot it to
                       assets/manifest.json with observed AWS CLI shas)
  populate             download into $CDKTN_ASSET_DIR (default
                       ~/.cdktn-bench/assets), keeping only sha-verified files
  serve --port N       http.server over the asset dir on 0.0.0.0 (default
                       port: the one the Dockerfiles probe)
  verify               re-hash every file in the asset dir against the pins
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARMS_DIR = REPO_ROOT / "arms"
MANIFEST_PATH = REPO_ROOT / "assets" / "manifest.json"
ARCHES = ("amd64", "arm64")

# The one URL every arm Dockerfile defaults `ARG ASSET_MIRROR` to. Nothing
# overrides it, so every build of a Dockerfile hashes the same RUN strings and
# shares one layer cache -- including the no-build-arg `docker compose build`
# the harness runs, which is what makes a prebuild warm it. host.lima.internal
# is how colima publishes the macOS host inside a build container.
# test/test_asset_mirror.py fails if a Dockerfile drifts from this.
DEFAULT_MIRROR_PORT = 8899
DEFAULT_MIRROR_URL = f"http://host.lima.internal:{DEFAULT_MIRROR_PORT}"

# Bare binaries land on PATH; archives land in /tmp and are unpacked by the
# Dockerfile. Only the first kind can be recovered out of a built image.
BINARY_PREFIX = "/usr/local/bin/"


def asset_dir() -> Path:
    env = os.environ.get("CDKTN_ASSET_DIR")
    return Path(env).expanduser() if env else Path.home() / ".cdktn-bench" / "assets"


def host_arch() -> str:
    return "arm64" if platform.machine() in ("arm64", "aarch64") else "amd64"


# --- manifest derivation ---------------------------------------------------


def _logical_lines(text: str) -> list[str]:
    """Dockerfile instructions with backslash continuations joined."""
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        if buf.strip():
            out.append(buf)
        buf = ""
    if buf.strip():
        out.append(buf)
    return out


def _arg_defaults(lines: list[str]) -> dict[str, str]:
    args: dict[str, str] = {}
    for line in lines:
        m = re.match(r'\s*ARG\s+([A-Z_][A-Z0-9_]*)=(?:"([^"]*)"|(\S+))\s*$', line)
        if m:
            args[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return args


def _case_vars(block: str, arch: str) -> dict[str, str]:
    """Assignments from the `case "${TARGETARCH}" in <arch>) … ;;` branch."""
    m = re.search(rf'(?<![\w-]){re.escape(arch)}\)(.*?);;', block, re.S)
    if not m:
        return {}
    return dict(re.findall(r'([A-Z_][A-Z0-9_]*)="([^"]*)"', m.group(1)))


def _plain_vars(block: str) -> dict[str, str]:
    """Every assignment in the block, in order. Applied BEFORE the per-arch
    ones so the right branch wins. Mirror overrides are skipped: this parser
    derives the UPSTREAM url, which is what a mirror has to be populated from."""
    return {
        name: value
        for name, value in re.findall(r'([A-Z_][A-Z0-9_]*)="([^"]*)"', block)
        if "ASSET_MIRROR" not in value
    }


def _uname_vars(block: str, arch: str) -> dict[str, str]:
    """Assignments from the AWS CLI block's `uname -m` if/else, which names the
    machine arch (aarch64/x86_64) rather than Docker's TARGETARCH."""
    machine = "aarch64" if arch == "arm64" else "x86_64"
    out: dict[str, str] = {}
    for name, value in re.findall(r'([A-Z_][A-Z0-9_]*)="(https://[^"]*)"', block):
        if machine in value:
            out[name] = value
    return out


def _expand(value: str, env: dict[str, str]) -> str:
    """Shell parameter expansion to a fixed point: a URL held in a shell
    variable expands to a value that itself still names ${TARGETARCH}."""

    def sub(m: re.Match) -> str:
        return env.get(m.group(1) or m.group(2), "")

    pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)'
    for _ in range(5):
        expanded = re.sub(pattern, sub, value)
        if expanded == value:
            break
        value = expanded
    return value


def _curl_fetches(block: str) -> list[tuple[str, str]]:
    """(dest, url-expression) for every curl in the block, either argument order."""
    out = []
    for m in re.finditer(r'curl\s+[^;&]*?-o\s+(\S+)\s+"?(\$?\{?[A-Za-z_][^"\s;]*|https://[^"\s;]+)"?', block):
        out.append((m.group(1), m.group(2)))
    for m in re.finditer(r'curl\s+[^;&]*?"(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)"\s+-o\s+(\S+)', block):
        out.append((m.group(2), m.group(1)))
    return out


def parse_dockerfile(path: Path) -> list[dict]:
    """Every sha-pinned (or deliberately unpinned) download in one arm image."""
    text = path.read_text()
    lines = _logical_lines(text)
    args = _arg_defaults(lines)
    assets: list[dict] = []
    for line in lines:
        if not line.lstrip().startswith("RUN") or "curl" not in line:
            continue
        for arch in ARCHES:
            env = dict(args)
            env["TARGETARCH"] = arch
            env.update(_plain_vars(line))
            env.update(_case_vars(line, arch))
            env.update(_uname_vars(line, arch))
            for dest, url_expr in _curl_fetches(line):
                url = _expand(url_expr, env)
                if not url.startswith("https://"):
                    continue
                sha = next(
                    (v for k, v in env.items() if k.endswith("_SHA256") and re.fullmatch(r"[0-9a-f]{64}", v)),
                    None,
                )
                assets.append(
                    {
                        "name": url.rsplit("/", 1)[-1],
                        "arch": arch,
                        "url": url,
                        "sha256": sha,
                        "container_path": dest,
                        "binary": dest.startswith(BINARY_PREFIX),
                        "arms": [path.parent.parent.name],
                    }
                )
    return assets


def derive_manifest() -> dict:
    merged: dict[tuple[str, str], dict] = {}
    for dockerfile in sorted(ARMS_DIR.glob("*/environment/Dockerfile")):
        for asset in parse_dockerfile(dockerfile):
            key = (asset["name"], asset["arch"])
            if key in merged:
                prev = merged[key]
                if prev["sha256"] != asset["sha256"] or prev["url"] != asset["url"]:
                    raise SystemExit(
                        f"pin conflict for {asset['name']} between "
                        f"{prev['arms']} and {asset['arms']}"
                    )
                prev["arms"] = sorted(set(prev["arms"]) | set(asset["arms"]))
            else:
                merged[key] = dict(asset)
    assets = sorted(merged.values(), key=lambda a: (a["name"], a["arch"]))
    return {"assets": assets}


def load_observed() -> dict[str, str]:
    if MANIFEST_PATH.exists():
        doc = json.loads(MANIFEST_PATH.read_text())
        return {a["name"]: a["observed_sha256"] for a in doc["assets"] if a.get("observed_sha256")}
    return {}


def manifest_with_observed() -> dict:
    doc = derive_manifest()
    observed = load_observed()
    here = asset_dir()
    for asset in doc["assets"]:
        if asset["sha256"]:
            continue
        path = here / asset["name"]
        if path.exists():
            asset["observed_sha256"] = sha256_file(path)
        elif asset["name"] in observed:
            asset["observed_sha256"] = observed[asset["name"]]
    return doc


# --- populate --------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(partial(fh.read, 1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> bool:
    """HTTP/1.1 with retries: this network's HTTP/2 path truncates or resets
    large GitHub release assets."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        "curl", "-fSL", "--http1.1", "--retry", "5", "--retry-all-errors",
        "--connect-timeout", "20", "-o", str(tmp), url,
    ]
    print(f"    curl {url}")
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        tmp.unlink(missing_ok=True)
        print(f"    FAILED (curl exit {rc})")
        return False
    tmp.replace(dest)
    return True


def extract_from_image(asset: dict) -> bool:
    """Recover a bare binary out of an already-built arm image. Archives have
    no counterpart inside the image, so they are only ever fetched upstream."""
    if not asset["binary"]:
        return False
    for arm in asset["arms"]:
        image = f"cdktn-bench/{arm}:dev"
        probe = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
        if probe.returncode != 0:
            continue
        created = subprocess.run(
            ["docker", "create", image], capture_output=True, text=True
        )
        if created.returncode != 0:
            continue
        cid = created.stdout.strip()
        try:
            dest = asset_dir() / asset["name"]
            cp = subprocess.run(
                ["docker", "cp", f"{cid}:{asset['container_path']}", str(dest)],
                capture_output=True,
            )
            if cp.returncode != 0:
                continue
            print(f"    extracted from {image}:{asset['container_path']}")
            return True
        finally:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    return False


def cmd_populate(args: argparse.Namespace) -> int:
    here = asset_dir()
    here.mkdir(parents=True, exist_ok=True)
    arches = ARCHES if args.arch == "all" else (args.arch,)
    doc = derive_manifest()
    failed: list[str] = []
    for asset in doc["assets"]:
        if asset["arch"] not in arches:
            continue
        path = here / asset["name"]
        print(f"==> {asset['name']} ({asset['arch']})")
        if path.exists():
            if asset["sha256"] is None or sha256_file(path) == asset["sha256"]:
                print("    already present, verified")
                continue
            print("    present but sha256 mismatch, refetching")
            path.unlink()
        got = False
        if args.from_images:
            got = extract_from_image(asset)
        if not got:
            got = download(asset["url"], path)
        if not got:
            failed.append(f"{asset['name']} ({asset['arch']})")
            continue
        if asset["sha256"] is None:
            print(f"    unpinned upstream; observed sha256 {sha256_file(path)}")
            continue
        actual = sha256_file(path)
        if actual != asset["sha256"]:
            print(f"    sha256 MISMATCH: got {actual}, pinned {asset['sha256']}")
            path.unlink()
            failed.append(f"{asset['name']} ({asset['arch']}) sha256 mismatch")
        else:
            print("    verified")
    cmd_manifest(argparse.Namespace(write=True))
    if failed:
        print("\nnot mirrored:")
        for item in failed:
            print(f"  {item}")
        return 1
    return 0


# --- verify / serve / manifest --------------------------------------------


def cmd_verify(_args: argparse.Namespace) -> int:
    here = asset_dir()
    doc = derive_manifest()
    by_name = {a["name"]: a for a in doc["assets"]}
    bad = 0
    seen = set()
    for path in sorted(here.iterdir()):
        if not path.is_file() or path.name.endswith(".part"):
            continue
        seen.add(path.name)
        asset = by_name.get(path.name)
        actual = sha256_file(path)
        if asset is None:
            print(f"UNKNOWN  {path.name} ({actual})")
            continue
        if asset["sha256"] is None:
            print(f"UNPINNED {path.name} ({actual})")
        elif actual == asset["sha256"]:
            print(f"OK       {path.name}")
        else:
            print(f"MISMATCH {path.name}: {actual} != {asset['sha256']}")
            bad += 1
    for name in sorted(set(by_name) - seen):
        print(f"ABSENT   {name}")
    return 1 if bad else 0


def cmd_serve(args: argparse.Namespace) -> int:
    here = asset_dir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(here))
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    port = server.server_address[1]
    print(f"serving {here} on 0.0.0.0:{port}")
    print(f"  from a build container: http://host.lima.internal:{port}")
    print(f"  from this host:         http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    doc = manifest_with_observed()
    text = json.dumps(doc, indent=2) + "\n"
    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(text)
        print(f"wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_manifest = sub.add_parser("manifest", help="print the derived asset list")
    p_manifest.add_argument("--write", action="store_true", help="snapshot to assets/manifest.json")
    p_manifest.set_defaults(func=cmd_manifest)

    p_populate = sub.add_parser("populate", help="fill the asset dir")
    p_populate.add_argument("--from-images", action="store_true",
                            help="prefer extracting bare binaries from built arm images")
    p_populate.add_argument("--arch", choices=(*ARCHES, "all"), default=host_arch())
    p_populate.set_defaults(func=cmd_populate)

    p_serve = sub.add_parser("serve", help="serve the asset dir over HTTP")
    p_serve.add_argument("--port", type=int, default=DEFAULT_MIRROR_PORT)
    p_serve.set_defaults(func=cmd_serve)

    sub.add_parser("verify", help="re-hash the asset dir").set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
