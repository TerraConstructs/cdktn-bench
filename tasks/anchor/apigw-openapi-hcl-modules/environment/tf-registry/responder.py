#!/usr/bin/env python3
"""Offline Terraform module registry over the vendored `modules/` tree.

Serves the module registry protocol (`versions`, `download`), a manifest-backed
`/v1/modules/search`, and an MCP `/mcp` skeleton, from `--root`'s
`manifest.json` alone. A CLI-config `host "registry.terraform.io"` block
overriding `modules.v1` at this server makes `source =
"terraform-aws-modules/<name>/aws"` resolve here over plain HTTP with no
discovery request and no change to what the agent writes
(docs/design/tf-module-registry-loopback.md §1).

Nothing here opens an outbound connection: the manifest is the whole world, so
an unvendored name or version is a 404 naming what exists rather than a
passthrough to upstream. That is the property the arm's offline guarantee rests
on, and gates/tests/test_tf_registry.py asserts it with an audit hook.

Runs both inside the arm image (the compose sidecar is this image with this
file as its command) and on the host as a gate subprocess
(gates/tf_registry.py). Prints `PORT=<n>` once listening, then one
`ACCESS <method> <path> <status>` line per request — the evidence that a module
came from here and not from the network. See docs/gates.md#tf-registry.
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

NAMESPACE = "terraform-aws-modules"
SYSTEM = "aws"
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "cdktn-bench-registry-index"

# The nine tools of terraform-mcp-server v1.3.0's `registry` toolset, names and
# required inputs copied from docs/design/registry-index-tool.md §1. The bodies
# are the phase-4 skeleton: every call declines, M2 fills them in.
_DOC_TYPES = ["resources", "data-sources", "functions", "guides", "overview", "actions", "list-resources"]


def _schema(required: dict[str, dict], optional: dict[str, dict] | None = None) -> dict:
    props = dict(required)
    props.update(optional or {})
    return {"type": "object", "properties": props, "required": sorted(required)}


TOOLS = [
    {
        "name": "search_modules",
        "description": "Search the Terraform registry for modules matching a query.",
        "inputSchema": _schema(
            {"module_query": {"type": "string", "description": "Module search query."}},
            {"current_offset": {"type": "number", "minimum": 0, "description": "Pagination offset."}},
        ),
    },
    {
        "name": "get_module_details",
        "description": "Fetch details for one module version.",
        "inputSchema": _schema(
            {"module_id": {"type": "string", "description": "namespace/name/provider/version."}}
        ),
    },
    {
        "name": "get_latest_module_version",
        "description": "Latest published version of one module.",
        "inputSchema": _schema({
            "module_publisher": {"type": "string"},
            "module_name": {"type": "string"},
            "module_provider": {"type": "string"},
        }),
    },
    {
        "name": "search_providers",
        "description": "Search a provider's registry documentation.",
        "inputSchema": _schema(
            {
                "provider_name": {"type": "string"},
                "provider_namespace": {"type": "string"},
                "service_slug": {"type": "string"},
                "provider_document_type": {"type": "string", "enum": _DOC_TYPES},
            },
            {"provider_version": {"type": "string"}},
        ),
    },
    {
        "name": "get_provider_details",
        "description": "Fetch one registry provider document by id.",
        "inputSchema": _schema({"provider_doc_id": {"type": "string"}}),
    },
    {
        "name": "get_latest_provider_version",
        "description": "Latest published version of one provider.",
        "inputSchema": _schema({"namespace": {"type": "string"}, "name": {"type": "string"}}),
    },
    {
        "name": "get_provider_capabilities",
        "description": "Resource, data-source and function names a provider version exposes.",
        "inputSchema": _schema(
            {"namespace": {"type": "string"}, "name": {"type": "string"}},
            {"version": {"type": "string"}},
        ),
    },
    {
        "name": "search_policies",
        "description": "Search the registry for Sentinel policy libraries.",
        "inputSchema": _schema({"policy_query": {"type": "string"}}),
    },
    {
        "name": "get_policy_details",
        "description": "Fetch one Sentinel policy library by id.",
        "inputSchema": _schema({"terraform_policy_id": {"type": "string"}}),
    },
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)
DECLINED = "{tool}: not available in this environment"


class Manifest:
    """The vendored tree's `manifest.json`, indexed by (name, version)."""

    def __init__(self, root: Path):
        self.root = root
        raw = json.loads((root / "manifest.json").read_text())
        entries = raw["modules"] if isinstance(raw, dict) else raw
        self.modules: dict[tuple[str, str], dict] = {}
        for m in entries:
            self.modules[(m["name"], str(m["version"]))] = m
        self.names = sorted({n for n, _ in self.modules})

    def versions(self, name: str) -> list[str]:
        """Newest last, ordered by numeric release components."""
        vs = [v for n, v in self.modules if n == name]
        return sorted(vs, key=_version_key)

    def newest(self, name: str) -> str | None:
        vs = self.versions(name)
        return vs[-1] if vs else None

    def dir_of(self, name: str, version: str) -> Path:
        return self.root / self.modules[(name, version)]["dir"]


def _version_key(v: str) -> tuple:
    parts = []
    for chunk in v.replace("-", ".").split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, 0))
    return tuple(parts)


def _tarball(manifest: Manifest, cache: Path, name: str, version: str) -> Path:
    """`<name>-<version>.tar.gz` of the module directory's CONTENTS.

    The vendored directory name is stripped rather than kept as the archive's
    top directory: go-getter extracts the archive as the module root itself, so
    a retained top directory puts every `.tf` file one level below where
    Terraform looks for it.
    """
    out = cache / f"{name}-{version}.tar.gz"
    if out.exists():
        return out
    src = manifest.dir_of(name, version)
    tmp = out.with_suffix(".tar.gz.partial")
    with tarfile.open(tmp, "w:gz") as tar:
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            tar.add(path, arcname=path.relative_to(src).as_posix())
    tmp.replace(out)
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    manifest: Manifest
    cache: Path
    sessions: set

    def _send(self, code: int, ctype: str | None, body: bytes, headers: dict | None = None) -> None:
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)
        print(f"ACCESS {self.command} {self.path} {code}", flush=True)

    def _json(self, code: int, payload: dict, headers: dict | None = None) -> None:
        self._send(code, "application/json", json.dumps(payload).encode(), headers)

    def _text_404(self, message: str) -> None:
        self._send(404, "text/plain; charset=utf-8", message.encode())

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/.well-known/terraform.json":
            return self._json(200, {"modules.v1": "/v1/modules/"})
        if path == "/v1/modules/search":
            return self._search(parse_qs(parsed.query).get("q", [""])[0])
        if path.startswith("/tarballs/"):
            return self._tarball_get(path.removeprefix("/tarballs/"))
        parts = path.strip("/").split("/")
        if parts[:2] == ["v1", "modules"] and len(parts) in (6, 7):
            return self._registry(parts[2:])
        self._text_404(f"no such endpoint: {path}")

    def _registry(self, parts: list[str]) -> None:
        ns, name, system = parts[0], parts[1], parts[2]
        if ns != NAMESPACE or system != SYSTEM:
            return self._text_404(
                f"{ns}/{name}/{system} is not available in this environment; this "
                f"registry serves only {NAMESPACE}/<name>/{SYSTEM}, with <name> one of: "
                + ", ".join(self.manifest.names)
            )
        if parts[3:] == ["versions"]:
            return self._versions(name)
        if len(parts) == 5 and parts[4] == "download":
            return self._download(name, parts[3])
        self._text_404(f"no such endpoint: {self.path}")

    def _versions(self, name: str) -> None:
        versions = self.manifest.versions(name)
        if not versions:
            return self._text_404(self._unknown_module(name))
        payload = {"modules": [{"versions": [{"version": v} for v in versions]}]}
        self._json(200, payload)

    def _download(self, name: str, version: str) -> None:
        if (name, version) not in self.manifest.modules:
            newest = self.manifest.newest(name)
            if newest is None:
                return self._text_404(self._unknown_module(name))
            return self._text_404(
                f"{NAMESPACE}/{name}/{SYSTEM} {version} is not available in this "
                f"environment; the newest available version is {newest}"
            )
        # Absolute rather than relative: a bare path in X-Terraform-Get is
        # resolved as a URL against the download endpoint, never as a
        # filesystem path (tf-module-registry-loopback.md §2).
        host = self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        url = f"http://{host}/tarballs/{name}-{version}.tar.gz"
        self._send(204, None, b"", {"X-Terraform-Get": url})

    def _unknown_module(self, name: str) -> str:
        return (
            f"{NAMESPACE}/{name}/{SYSTEM} is not available in this environment; "
            "available modules: " + ", ".join(self.manifest.names)
        )

    def _tarball_get(self, filename: str) -> None:
        for (name, version) in sorted(self.manifest.modules):
            if filename == f"{name}-{version}.tar.gz":
                body = _tarball(self.manifest, self.cache, name, version).read_bytes()
                return self._send(200, "application/gzip", body)
        self._text_404(f"no such archive: {filename}")

    def _search(self, query: str) -> None:
        """Manifest-backed, decoys unmarked: a decoy that advertised itself as
        one would hand the agent the selection answer the arm measures."""
        q = query.strip().lower()
        hits = []
        for name in self.manifest.names:
            versions = self.manifest.versions(name)
            entry = self.manifest.modules[(name, versions[-1])]
            description = entry.get("description") or entry.get("summary") or ""
            if q and q not in name.lower() and q not in description.lower():
                continue
            hits.append({
                "id": f"{NAMESPACE}/{name}/{SYSTEM}/{versions[-1]}",
                "source": f"{NAMESPACE}/{name}/{SYSTEM}",
                "versions": list(reversed(versions)),
                "description": description,
            })
        self._json(200, {"modules": hits})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/mcp":
            return self._text_404(f"no such endpoint: {self.path}")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(n) or b"null")
        except json.JSONDecodeError:
            return self._json(400, _rpc_error(None, -32700, "parse error"))
        if not isinstance(message, dict):
            return self._json(400, _rpc_error(None, -32600, "invalid request"))
        session = self.headers.get("Mcp-Session-Id")
        method = message.get("method")
        if method == "initialize":
            session = session or f"{SERVER_NAME}-{len(self.sessions) + 1}"
            self.sessions.add(session)
            return self._json(200, _rpc_ok(message.get("id"), {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": "0"},
            }), {"Mcp-Session-Id": session})
        headers = {"Mcp-Session-Id": session} if session else {}
        if str(method).startswith("notifications/"):
            return self._send(202, None, b"", headers)
        if method == "tools/list":
            return self._json(200, _rpc_ok(message.get("id"), {"tools": TOOLS}), headers)
        if method == "tools/call":
            name = (message.get("params") or {}).get("name")
            if name not in TOOL_NAMES:
                return self._json(200, _rpc_error(message.get("id"), -32602, f"unknown tool: {name}"), headers)
            # A declined call is a SUCCESSFUL result, not an error: an error
            # reads to an agent as an outage worth retrying, while this text
            # states the bound it is working inside.
            return self._json(200, _rpc_ok(message.get("id"), {
                "content": [{"type": "text", "text": DECLINED.format(tool=name)}],
                "isError": False,
            }), headers)
        self._json(200, _rpc_error(message.get("id"), -32601, f"method not found: {method}"), headers)

    def log_message(self, *args) -> None:
        """Silenced: the `ACCESS` lines `_send` prints are the record, and they
        carry the status every caller of this server asserts on."""


def _rpc_ok(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(root: Path, port: int, bind: str = "127.0.0.1") -> None:
    handler = type("BoundHandler", (Handler,), {
        "manifest": Manifest(root),
        "cache": Path(tempfile.mkdtemp(prefix="tf-registry-tarballs-")),
        "sessions": set(),
    })
    # Threaded: terraform holds HTTP/1.1 keep-alive connections open and fetches
    # modules in parallel, so a single-threaded server deadlocks on the first
    # idle socket.
    srv = ThreadingHTTPServer((bind, port), handler)
    srv.daemon_threads = True
    print(f"PORT={srv.server_address[1]}", flush=True)
    srv.serve_forever()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, type=Path, help="vendored module tree holding manifest.json")
    ap.add_argument("--port", type=int, default=0, help="0 binds an ephemeral port")
    ap.add_argument("--bind", default="127.0.0.1", help="0.0.0.0 for the compose sidecar")
    args = ap.parse_args(argv)
    if not (args.root / "manifest.json").is_file():
        print(f"no manifest.json under {args.root}", file=sys.stderr)
        return 2
    serve(args.root, args.port, args.bind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
