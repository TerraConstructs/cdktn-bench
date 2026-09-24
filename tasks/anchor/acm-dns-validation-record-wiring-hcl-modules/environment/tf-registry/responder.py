#!/usr/bin/env python3
"""Offline Terraform module registry over the vendored `modules/` tree.

Serves the module registry protocol (`versions`, `download`), a manifest-backed
`/v1/modules/search`, and the bench-owned index tool over MCP at `/mcp`, from
`--root`'s `manifest.json` plus `--mirror-root`'s provider mirror. A CLI-config
`host "registry.terraform.io"` block overriding `modules.v1` at this server makes
`source =
"terraform-aws-modules/<name>/aws"` resolve here over plain HTTP with no
discovery request and no change to what the agent writes
(docs/design/tf-module-registry-loopback.md §1).

The index tool is the tuned equipping row of docs/design/registry-index-tool.md
design B: the nine tool names of terraform-mcp-server's `registry` toolset,
answered from this manifest and this mirror, because v1.3.0 hard-codes the public
registry URL and can neither be redirected here nor run offline.

Nothing here opens an outbound connection: the manifest is the whole world, so
an unvendored name or version is a 404 -- or, over MCP, a successful result --
naming what exists rather than a passthrough to upstream. That is the property
the arm's offline guarantee rests on, and both test files assert it by driving
every endpoint and every tool under a `socket.connect` audit hook.

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
# The mirror the arm image bakes (arms/hcl-modules/environment/terraformrc).
MIRROR_ROOT = Path("/opt/terraform-plugin-mirror")
SYSTEM = "aws"
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "cdktn-bench-registry-index"

# The nine tools of terraform-mcp-server v1.3.0's `registry` toolset, names and
# required inputs copied from docs/design/registry-index-tool.md §1. The names and
# schemas are upstream's so that an agent or skill tuned against the real server
# calls the same tools with the same arguments; `Index` below is what answers.
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
# Every refusal, over either channel, ends on this one phrase, so a skill or a
# grader can match one string: `<what> is not available in this environment`.
UNAVAILABLE = "{what} is not available in this environment"
DECLINED = UNAVAILABLE.format(what="{tool}") + "; {reason}"


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


# ---------------------------------------------------------------------------
# A minimal HCL reader: enough of the syntax to read a module's own interface
# out of its `.tf` files, and honest about the rest. It reports ATTRIBUTE SOURCE
# TEXT verbatim and never evaluates an expression, so a `default` this reader
# shows is what the module file says; what it cannot delimit at all is named in
# a `not_shown` list instead of being guessed (an input whose type the tool
# invented is worse than one it admits it cannot read).
# ---------------------------------------------------------------------------

_IDENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class HclError(Exception):
    """A construct this reader does not implement. Caught per file and per
    block, so one unreadable variable costs that variable and not the module."""


def _skip_gap(text: str, i: int) -> int:
    """Past whitespace, `#`/`//` and `/* */` comments, and the commas an object
    constructor separates its attributes with."""
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise HclError("unterminated block comment")
            i = end + 2
        else:
            break
    return i


def _read_quoted(text: str, i: int) -> tuple[str | None, int]:
    """`(value, end)`; value is None for an interpolated string, whose value
    depends on evaluation this reader does not do."""
    if text[i : i + 1] != '"':
        raise HclError("expected a quoted string")
    out: list[str] = []
    interpolated = False
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            nxt = text[i + 1 : i + 2]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            i += 2
            continue
        if c == '"':
            return (None if interpolated else "".join(out)), i + 1
        if c == "\n":
            raise HclError("newline inside a quoted string")
        if c == "$" and text[i + 1 : i + 2] == "{":
            interpolated = True
        out.append(c)
        i += 1
    raise HclError("unterminated quoted string")


def _read_value(text: str, i: int) -> tuple[str, int]:
    """The source text of one attribute value, ending at the newline that
    closes it. Brackets, strings and heredocs are tracked so that a newline
    inside a multi-line `default` or an object type does not end it early."""
    start, depth, n = i, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            _, i = _read_quoted(text, i)
            continue
        if text.startswith("<<", i):
            i = _skip_heredoc(text, i)
            # A heredoc consumes its own terminating newline, so at depth 0 it
            # IS the end of the value -- without this the next attribute line is
            # swallowed into it and reported as part of the value.
            if depth == 0:
                return text[start:i].strip(), i
            continue
        if c == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif c == "\n" and depth == 0:
            break
        i += 1
    return text[start:i].strip(), i


def _skip_heredoc(text: str, i: int) -> int:
    n = len(text)
    marker_start = i + 3 if text[i + 2 : i + 3] == "-" else i + 2
    header_end = text.find("\n", marker_start)
    if header_end < 0:
        raise HclError("unterminated heredoc header")
    marker = text[marker_start:header_end].strip()
    if not marker:
        raise HclError("heredoc with no marker")
    i = header_end + 1
    while i < n:
        line_end = text.find("\n", i)
        line = text[i : (n if line_end < 0 else line_end)]
        i = n if line_end < 0 else line_end + 1
        if line.strip() == marker:
            return i
    raise HclError(f"unterminated heredoc {marker}")


def _read_ident(text: str, i: int) -> tuple[str, int]:
    end = i
    while end < len(text) and text[end] in _IDENT_CHARS:
        end += 1
    if end == i:
        raise HclError(f"expected an identifier at offset {i}")
    return text[i:end], end


def _read_body(text: str, i: int) -> tuple[dict, int]:
    """One `{ … }` body, starting after its brace: attribute source text by
    name, plus nested `(type, labels, body)` blocks."""
    attributes: dict[str, str] = {}
    blocks: list[tuple[str, list[str], dict]] = []
    while True:
        i = _skip_gap(text, i)
        if i >= len(text):
            raise HclError("unterminated block body")
        if text[i] == "}":
            return {"attributes": attributes, "blocks": blocks}, i + 1
        name, i = _read_ident(text, i)
        i = _skip_gap(text, i)
        if text[i : i + 1] == "=":
            attributes[name], i = _read_value(text, i + 1)
            continue
        labels = []
        while text[i : i + 1] == '"':
            label, i = _read_quoted(text, i)
            labels.append(label or "")
            i = _skip_gap(text, i)
        if text[i : i + 1] != "{":
            raise HclError(f"expected a body for block {name}")
        body, i = _read_body(text, i + 1)
        blocks.append((name, labels, body))


def hcl_blocks(text: str) -> list[tuple[str, list[str], dict]]:
    """Every top-level block of one `.tf` file, as `(type, labels, body)`."""
    out: list[tuple[str, list[str], dict]] = []
    i = 0
    while True:
        i = _skip_gap(text, i)
        if i >= len(text):
            return out
        name, i = _read_ident(text, i)
        i = _skip_gap(text, i)
        labels = []
        while text[i : i + 1] == '"':
            label, i = _read_quoted(text, i)
            labels.append(label or "")
            i = _skip_gap(text, i)
        if text[i : i + 1] != "{":
            raise HclError(f"expected a body for block {name}")
        body, i = _read_body(text, i + 1)
        out.append((name, labels, body))


def _literal(raw: str) -> str | None:
    """The string a `description = "…"` attribute holds, or None when this
    reader cannot read it as one plain string (a heredoc, an interpolation, a
    concatenation) -- the caller reports those as not shown."""
    try:
        value, end = _read_quoted(raw, 0)
    except HclError:
        return None
    return value if end == len(raw) else None


def _declared(attributes: dict[str, str], key: str, row: dict, missing: list[str]) -> None:
    """Copy one attribute's SOURCE TEXT into `row`, or name it in `missing`."""
    if key in attributes:
        row[key] = attributes[key]
    else:
        missing.append(key)


def module_interface(module_dir: Path, relpaths: list[str]) -> dict:
    """Inputs, outputs, provider requirements and submodules of one vendored
    module version, read from its ROOT `.tf` files.

    Root files only: a registry module's `modules/<sub>/variables.tf` declares
    the submodule's interface, not the one a `module` block in the agent's
    workspace fills in. Submodules are listed by their registry `//` address
    instead, which is what a caller would need to write to reach one.
    """
    inputs: dict[str, dict] = {}
    outputs: dict[str, dict] = {}
    requirements: dict[str, dict] = {}
    unreadable: list[str] = []
    required_version: str | None = None
    for relpath in sorted(p for p in relpaths if p.endswith(".tf") and "/" not in p):
        try:
            blocks = hcl_blocks((module_dir / relpath).read_text())
        except (HclError, OSError, UnicodeDecodeError):
            unreadable.append(relpath)
            continue
        for kind, labels, body in blocks:
            attributes = body["attributes"]
            if kind == "variable" and labels:
                inputs[labels[0]] = _input_row(labels[0], attributes)
            elif kind == "output" and labels:
                outputs[labels[0]] = _output_row(labels[0], attributes)
            elif kind == "terraform":
                required_version = required_version or _literal(attributes.get("required_version", ""))
                requirements.update(_provider_requirements(body))
    interface = {
        "inputs": [inputs[name] for name in sorted(inputs)],
        "outputs": [outputs[name] for name in sorted(outputs)],
        "provider_requirements": [requirements[name] for name in sorted(requirements)],
        "submodules": sorted(
            {p.rsplit("/", 1)[0] for p in relpaths if p.startswith("modules/") and p.endswith(".tf")}
        ),
    }
    if required_version:
        interface["required_terraform_version"] = required_version
    if unreadable:
        interface["unreadable_files"] = sorted(unreadable)
    return interface


def _input_row(name: str, attributes: dict[str, str]) -> dict:
    row: dict = {"name": name, "required": "default" not in attributes}
    missing: list[str] = []
    description = attributes.get("description")
    if description is None or _literal(description) is None:
        missing.append("description")
    else:
        row["description"] = _literal(description)
    _declared(attributes, "type", row, missing)
    if not row["required"]:
        _declared(attributes, "default", row, missing)
    for optional in ("nullable", "sensitive"):
        if optional in attributes:
            row[optional] = attributes[optional]
    if missing:
        row["not_shown"] = sorted(missing)
    return row


def _output_row(name: str, attributes: dict[str, str]) -> dict:
    row: dict = {"name": name}
    description = attributes.get("description")
    if description is not None and _literal(description) is not None:
        row["description"] = _literal(description)
    else:
        row["not_shown"] = ["description"]
    if "sensitive" in attributes:
        row["sensitive"] = attributes["sensitive"]
    return row


def _provider_requirements(terraform_body: dict) -> dict[str, dict]:
    """`required_providers` entries as `{name: {source, version}}`, each field
    the attribute's own source text or absent."""
    found: dict[str, dict] = {}
    for kind, _labels, body in terraform_body["blocks"]:
        if kind != "required_providers":
            continue
        for name, raw in body["attributes"].items():
            row: dict = {"name": name}
            try:
                inner, end = _read_body(raw, raw.index("{") + 1) if raw.startswith("{") else (None, 0)
            except (HclError, ValueError):
                inner = None
            if inner is None:
                row["not_shown"] = ["source", "version"]
                row["declaration"] = raw
            else:
                for key in ("source", "version"):
                    literal = _literal(inner["attributes"].get(key, ""))
                    if literal is not None:
                        row[key] = literal
                row["not_shown"] = sorted({"source", "version"} - set(row))
                if not row["not_shown"]:
                    del row["not_shown"]
            found[name] = row
    return found


class ProviderMirror:
    """The image's `filesystem_mirror` tree, read the way terraform reads it.

    `<root>/<host>/<namespace>/<type>/index.json` lists the mirrored versions and
    `<version>.json` the platforms of each (`archives`) -- see
    gates/oracle_falsifiability.py, which reads the same two files out of the
    image. Packages and their hashes are all the mirror holds: no registry
    documentation, which is why two of the nine tools decline in favour of AWS
    Docs MCP instead of inventing prose.
    """

    def __init__(self, root: Path):
        self.root = root
        self.providers: dict[tuple[str, str], dict] = {}
        for index in sorted(root.glob("*/*/*/index.json")) if root.is_dir() else []:
            try:
                versions = json.loads(index.read_text()).get("versions", {})
            except (json.JSONDecodeError, OSError):
                continue
            type_dir = index.parent
            key = (type_dir.parent.name, type_dir.name)
            self.providers[key] = {
                "host": type_dir.parent.parent.name,
                "dir": type_dir,
                "versions": sorted(versions, key=_version_key),
            }

    @property
    def present(self) -> bool:
        return bool(self.providers)

    def addresses(self) -> list[str]:
        return sorted(f"{ns}/{name}" for ns, name in self.providers)

    def platforms(self, namespace: str, name: str, version: str) -> list[str]:
        entry = self.providers[(namespace, name)]
        try:
            archives = json.loads((entry["dir"] / f"{version}.json").read_text()).get("archives", {})
        except (json.JSONDecodeError, OSError):
            return []
        return sorted(archives)


# The two sentences every declining answer ends on. Both are a SUCCESSFUL
# result: an error reads to an agent as an outage worth retrying, while these
# state the bound the agent is working inside and where to go instead.
AWS_DOCS_HANDOFF = (
    "provider documentation on this arm comes from the AWS Docs MCP server, which serves the "
    "terraform-provider-aws resource, data-source and attribute pages; this environment's "
    "provider mirror holds provider packages only, with no registry documentation in it"
)
NO_POLICIES = "no Sentinel policy library is served in this environment, and there is no registry to search"

_INDEX_NOTES = (
    "This index answers from the module tree vendored into this environment and from the "
    "provider mirror; it holds no connection to registry.terraform.io.",
    "README.md, docs/ and examples/ are pruned from the vendored tree (see manifest.json "
    f'"prune"), so no module documentation prose can be shown; inputs and outputs are read '
    "from the module's own variables.tf and outputs.tf.",
    '"type" and "default" are the verbatim HCL source text of the declaration. A "not_shown" '
    "list names fields this environment cannot show, either undeclared by the module or not "
    "readable by this reader -- never guessed.",
    "Publish dates, download counts and verification badges are registry metadata this "
    "environment does not hold.",
)
SEARCH_PAGE_SIZE = 10


class ArgumentError(Exception):
    """A caller mistake, not an environment bound: reported as an MCP error
    result so the agent retries with the argument rather than reading the miss
    text as "this module does not exist"."""


class Index:
    """The nine registry tools, answered from the manifest and the mirror.

    One object shared by every request: the responder and the index tool are one
    process over one manifest, so they cannot disagree about what exists. Every
    answer is deterministic -- sorted throughout, no time, no counters -- because
    a tuned equipping row whose answers vary between trials is not a fixed
    treatment.
    """

    def __init__(self, manifest: Manifest, mirror: ProviderMirror):
        self.manifest = manifest
        self.mirror = mirror
        self._interfaces: dict[tuple[str, str], dict] = {}

    def interface(self, name: str, version: str, submodule: str = "") -> dict:
        """Memoised; a second parse of the same files yields the same dict, so a
        racing reader on another request thread costs work, never an answer."""
        key = (name, version, submodule)
        if key not in self._interfaces:
            root = self.manifest.dir_of(name, version)
            files = sorted(self.manifest.modules[(name, version)]["files"])
            if submodule:
                prefix = submodule + "/"
                root = root / submodule
                files = [f.removeprefix(prefix) for f in files if f.startswith(prefix)]
            self._interfaces[key] = module_interface(root, files)
        return self._interfaces[key]

    def call(self, tool: str, arguments: dict) -> str:
        return getattr(self, f"_{tool}")(arguments)

    # -- modules ----------------------------------------------------------

    def _search_modules(self, arguments: dict) -> str:
        query = _string(arguments, "module_query", allow_empty=True).lower()
        # Every whitespace-separated word must match, each anywhere in the module
        # name, its description or one of its input names. A caller asks for
        # "s3 bucket", not for a substring: matching the query as one literal
        # string answered nothing for the most natural phrasing of the most
        # common request, which is a handicap on the tuned level rather than a
        # property of the index. A single-word query is unaffected.
        tokens = query.split()
        offset = _offset(arguments, "current_offset")
        hits = []
        for name in self.manifest.names:
            versions = self.manifest.versions(name)
            entry = self.manifest.modules[(name, versions[-1])]
            description = entry.get("description") or ""
            inputs = [i["name"] for i in self.interface(name, versions[-1])["inputs"]]
            matched = sorted(
                i for i in inputs if any(token in i.lower() for token in tokens)
            )
            haystacks = [name.lower(), description.lower(), *(i.lower() for i in inputs)]
            if not all(any(token in h for h in haystacks) for token in tokens):
                continue
            hit = {
                "id": f"{NAMESPACE}/{name}/{SYSTEM}/{versions[-1]}",
                "source": f"{NAMESPACE}/{name}/{SYSTEM}",
                "versions": list(reversed(versions)),
                "input_count": len(inputs),
            }
            if description:
                hit["description"] = description
            if matched:
                hit["inputs_matching_query"] = matched
            hits.append(hit)
        page = hits[offset : offset + SEARCH_PAGE_SIZE]
        payload = {
            "query": query,
            "current_offset": offset,
            "total": len(hits),
            "modules": page,
            "notes": [
                "Every word of the query must match, each anywhere in a module name or "
                "input name. This index carries no module description, so a query "
                "matching only prose matches nothing here.",
                *_INDEX_NOTES,
            ],
        }
        if offset + SEARCH_PAGE_SIZE < len(hits):
            payload["next_offset"] = offset + SEARCH_PAGE_SIZE
        return _document(payload)

    def _get_module_details(self, arguments: dict) -> str:
        module_id = _string(arguments, "module_id")
        # `//<path>` is this index's one addition to upstream's module_id: the
        # `iam` module's ROOT declares nothing at all, so without it the honest
        # answer for the module an agent would actually call is empty.
        address, _, submodule = module_id.partition("//")
        submodule = submodule.strip("/")
        parts = address.strip("/").split("/")
        if len(parts) not in (3, 4):
            raise ArgumentError(
                f"module_id must be namespace/name/provider/version (or namespace/name/provider "
                f"for the newest version), got {module_id!r}"
            )
        namespace, name, system = parts[0], parts[1], parts[2]
        if namespace != NAMESPACE or system != SYSTEM:
            return _outside_allowlist(self.manifest, namespace, name, system)
        newest = self.manifest.newest(name)
        if newest is None:
            # Before the version check, or an unvendored NAME with a version
            # attached answers "available versions:" with nothing after it.
            return unknown_module(self.manifest, name)
        version = parts[3] if len(parts) == 4 else newest
        if (name, version) not in self.manifest.modules:
            return unknown_version(self.manifest, name, version)
        entry = self.manifest.modules[(name, version)]
        available = self.interface(name, version)["submodules"]
        if submodule and submodule not in available:
            return (
                UNAVAILABLE.format(what=f"{NAMESPACE}/{name}/{SYSTEM}//{submodule}")
                + "; available submodules: " + (", ".join(available) or "none")
            )
        interface = dict(self.interface(name, version, submodule))
        submodules = [
            {"path": path, "source": f"{NAMESPACE}/{name}/{SYSTEM}//{path}"}
            for path in interface.pop("submodules", [])
        ]
        payload = {
            "id": f"{NAMESPACE}/{name}/{SYSTEM}/{version}" + (f"//{submodule}" if submodule else ""),
            "source": f"{NAMESPACE}/{name}/{SYSTEM}",
            "version": version,
            "versions_available": self.manifest.versions(name),
            "upstream": {
                "repo": entry.get("upstream_repo"),
                "tag": entry.get("upstream_tag"),
                "commit": entry.get("upstream_commit"),
            },
            "submodules": submodules,
            **interface,
            "notes": list(_INDEX_NOTES),
        }
        if not interface["inputs"] and not interface["outputs"] and submodules:
            payload["notes"].insert(0, (
                "This module's root declares no inputs and no outputs: it is called through one "
                "of its submodules, whose `source` addresses are listed under submodules. Pass "
                "one of them as module_id to see that submodule's interface."
            ))
        if len(parts) == 3:
            payload["notes"].insert(
                0, f"module_id carried no version; answered for the newest available, {version}."
            )
        return _document(payload)

    def _get_latest_module_version(self, arguments: dict) -> str:
        publisher = _string(arguments, "module_publisher")
        name = _string(arguments, "module_name")
        system = _string(arguments, "module_provider")
        if publisher != NAMESPACE or system != SYSTEM:
            return _outside_allowlist(self.manifest, publisher, name, system)
        newest = self.manifest.newest(name)
        if newest is None:
            return unknown_module(self.manifest, name)
        return _document({
            "source": f"{NAMESPACE}/{name}/{SYSTEM}",
            "latest_version": newest,
            "versions_available": self.manifest.versions(name),
            "notes": [
                "Latest AVAILABLE HERE. Upstream may have published newer versions; only the "
                "versions listed exist in this environment.",
                *_INDEX_NOTES,
            ],
        })

    # -- providers --------------------------------------------------------

    def _search_providers(self, arguments: dict) -> str:
        for key in ("provider_name", "provider_namespace", "service_slug", "provider_document_type"):
            _string(arguments, key)
        return DECLINED.format(tool="search_providers", reason=AWS_DOCS_HANDOFF)

    def _get_provider_details(self, arguments: dict) -> str:
        _string(arguments, "provider_doc_id")
        return DECLINED.format(tool="get_provider_details", reason=AWS_DOCS_HANDOFF)

    def _get_latest_provider_version(self, arguments: dict) -> str:
        namespace = _string(arguments, "namespace")
        name = _string(arguments, "name")
        entry = self.mirror.providers.get((namespace, name))
        if entry is None:
            return self._unknown_provider(namespace, name)
        return _document({
            "source": f"{namespace}/{name}",
            "latest_version": entry["versions"][-1],
            "mirrored_versions": entry["versions"],
            "notes": [
                "Latest MIRRORED HERE, read from the mirror's own index.json. The version "
                "pinned in this workspace's provider.tf is the one to write.",
                *_INDEX_NOTES,
            ],
        })

    def _get_provider_capabilities(self, arguments: dict) -> str:
        namespace = _string(arguments, "namespace")
        name = _string(arguments, "name")
        entry = self.mirror.providers.get((namespace, name))
        if entry is None:
            return self._unknown_provider(namespace, name)
        version = arguments.get("version") or entry["versions"][-1]
        if version not in entry["versions"]:
            return (
                UNAVAILABLE.format(what=f"{namespace}/{name} {version}")
                + f"; mirrored versions: {', '.join(entry['versions'])}"
            )
        return _document({
            "source": f"{namespace}/{name}",
            "version": version,
            "mirrored_versions": entry["versions"],
            "platforms": self.mirror.platforms(namespace, name, version),
            "notes": [
                "Resource, data-source and function NAMES are not in a filesystem mirror -- it "
                f"holds provider packages and their hashes. For those, {AWS_DOCS_HANDOFF}.",
                "The mirror is built for the image's own platform, so a platform absent here is "
                "absent from this environment, not from the provider.",
                *_INDEX_NOTES,
            ],
        })

    def _unknown_provider(self, namespace: str, name: str) -> str:
        if not self.mirror.present:
            return (
                UNAVAILABLE.format(what=f"{namespace}/{name}")
                + "; no provider mirror is present in this process, so no provider can be "
                "described here"
            )
        return (
            UNAVAILABLE.format(what=f"{namespace}/{name}")
            + "; available providers: " + ", ".join(self.mirror.addresses())
        )

    # -- policies ---------------------------------------------------------

    def _search_policies(self, arguments: dict) -> str:
        _string(arguments, "policy_query")
        return DECLINED.format(tool="search_policies", reason=NO_POLICIES)

    def _get_policy_details(self, arguments: dict) -> str:
        _string(arguments, "terraform_policy_id")
        return DECLINED.format(tool="get_policy_details", reason=NO_POLICIES)


def _document(payload: dict) -> str:
    """Sorted keys and fixed indent: two runs of one call are byte-identical,
    which gates/tests/test_registry_index_tool.py asserts."""
    return json.dumps(payload, indent=2, sort_keys=True)


def _string(arguments: dict, key: str, allow_empty: bool = False) -> str:
    """A required argument of the §1 schemas. Missing is the caller's mistake;
    `allow_empty` is for `module_query`, where "" is the honest way to ask what
    this environment holds."""
    value = arguments.get(key)
    if not isinstance(value, str) or (not value.strip() and not allow_empty):
        raise ArgumentError(f"{key} is required and must be a non-empty string")
    return value.strip()


def _offset(arguments: dict, key: str) -> int:
    value = arguments.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value != int(value):
        raise ArgumentError(f"{key} must be a whole number >= 0")
    return int(value)


def unknown_module(manifest: Manifest, name: str) -> str:
    return (
        UNAVAILABLE.format(what=f"{NAMESPACE}/{name}/{SYSTEM}")
        + "; available modules: " + ", ".join(manifest.names)
    )


def unknown_version(manifest: Manifest, name: str, version: str) -> str:
    return (
        UNAVAILABLE.format(what=f"{NAMESPACE}/{name}/{SYSTEM} {version}")
        + f"; available versions: {', '.join(manifest.versions(name))}"
    )


def _outside_allowlist(manifest: Manifest, namespace: str, name: str, system: str) -> str:
    return (
        UNAVAILABLE.format(what=f"{namespace}/{name}/{system}")
        + f"; this registry serves only {NAMESPACE}/<name>/{SYSTEM}, with <name> one of: "
        + ", ".join(manifest.names)
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    manifest: Manifest
    index: Index
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
            return self._text_404(_outside_allowlist(self.manifest, ns, name, system))
        if parts[3:] == ["versions"]:
            return self._versions(name)
        if len(parts) == 5 and parts[4] == "download":
            return self._download(name, parts[3])
        self._text_404(f"no such endpoint: {self.path}")

    def _versions(self, name: str) -> None:
        versions = self.manifest.versions(name)
        if not versions:
            return self._text_404(unknown_module(self.manifest, name))
        payload = {"modules": [{"versions": [{"version": v} for v in versions]}]}
        self._json(200, payload)

    def _download(self, name: str, version: str) -> None:
        if (name, version) not in self.manifest.modules:
            newest = self.manifest.newest(name)
            if newest is None:
                return self._text_404(unknown_module(self.manifest, name))
            return self._text_404(
                UNAVAILABLE.format(what=f"{NAMESPACE}/{name}/{SYSTEM} {version}")
                + f"; the newest available version is {newest}"
            )
        # Absolute rather than relative: a bare path in X-Terraform-Get is
        # resolved as a URL against the download endpoint, never as a
        # filesystem path (tf-module-registry-loopback.md §2).
        host = self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        url = f"http://{host}/tarballs/{name}-{version}.tar.gz"
        self._send(204, None, b"", {"X-Terraform-Get": url})

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
            params = message.get("params") or {}
            name = params.get("name")
            if name not in TOOL_NAMES:
                return self._json(200, _rpc_error(message.get("id"), -32602, f"unknown tool: {name}"), headers)
            arguments = params.get("arguments")
            try:
                text = self.index.call(name, arguments if isinstance(arguments, dict) else {})
                is_error = False
            except ArgumentError as exc:
                # The one error result: a malformed argument is the caller's to
                # fix, and reporting it as a miss would read as "this does not
                # exist". A bound of the ENVIRONMENT is a successful result
                # instead -- an error there reads to an agent as an outage worth
                # retrying, while the text states the bound it works inside.
                text, is_error = f"{name}: {exc}", True
            return self._json(200, _rpc_ok(message.get("id"), {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            }), headers)
        self._json(200, _rpc_error(message.get("id"), -32601, f"method not found: {method}"), headers)

    def log_message(self, *args) -> None:
        """Silenced: the `ACCESS` lines `_send` prints are the record, and they
        carry the status every caller of this server asserts on."""


def _rpc_ok(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(root: Path, port: int, bind: str = "127.0.0.1", mirror_root: Path | None = None) -> None:
    manifest = Manifest(root)
    handler = type("BoundHandler", (Handler,), {
        "manifest": manifest,
        "index": Index(manifest, ProviderMirror(Path(mirror_root or MIRROR_ROOT))),
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
    # Absent, the provider tools answer that no mirror is present rather than
    # inventing a provider: a host gate has no mirror, only the image does.
    ap.add_argument("--mirror-root", type=Path, default=MIRROR_ROOT,
                    help="filesystem provider mirror the provider tools read")
    args = ap.parse_args(argv)
    if not (args.root / "manifest.json").is_file():
        print(f"no manifest.json under {args.root}", file=sys.stderr)
        return 2
    serve(args.root, args.port, args.bind, args.mirror_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
