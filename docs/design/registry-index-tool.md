# A bench-owned registry index tool: replacing the Terraform MCP server

Status: research memo, 2026-09-21. Answers the question left open by
`docs/design/tf-module-registry-loopback.md` §7.3 and
`docs/design/tf-modules-arm.md` §2 ("the Terraform MCP server cannot be the
tuned equipping for this arm as is"). Scope: the **M2 tuned equipping row**
for `hcl_modules` (and `hcl_raw`), sequenced *after* the arm lands. Facts in
§1 are read off `hashicorp/terraform-mcp-server` at tag `v1.3.0`
(`943a44eb28dc58432b34efdf08f7fc846adc446d`, 2026-08-25), cloned to
`…/scratchpad/mcp/terraform-mcp-server`; §2 off this repo at HEAD.

## 1. Terraform MCP server: verified facts

**Public, MPL-2.0, forkable.** `github.com/hashicorp/terraform-mcp-server`;
`LICENSE` = Mozilla Public License 2.0 (`Copyright (c) 2025 HashiCorp, Inc.`),
`SPDX-License-Identifier: MPL-2.0` on all 121 Go files under `pkg/`. Version
`1.3.0` (`version/VERSION`), shipped as
`docker.io/hashicorp/terraform-mcp-server:1.3.0`, `transport: stdio`
(`server.json`). MPL-2.0 is file-level copyleft: a patched
`pkg/client/registry.go` stays MPL and must be disclosed — doable, but it puts
Go in the build. **Transports:** `stdio` and `streamable-http` subcommands
(`cmd/terraform-mcp-server/init.go:52`, `:76`; deprecated `http` alias `:127`),
default bind `127.0.0.1:8080` (`:149-150`), also `TRANSPORT_MODE=`.
**Toolsets:** `registry` is the default and the only one needing no TFE session
(`pkg/toolsets/toolsets.go:57-60`, `registry.go:19-32`); its nine tools are
below, everything else is gated on `RequiresTFE`.

| tool (file:line of `mcp.NewTool`) | required inputs | HTTP call (path after base) |
|---|---|---|
| `search_modules` (`pkg/tools/registry/search_modules.go:24`) | `module_query`; opt `current_offset` (num, min 0) | `v1/modules/search?q='…'&offset=N` (`:92`) |
| `get_module_details` (`get_module_details.go:24`) | `module_id` = `ns/name/provider/version` | `v1/modules/{module_id}?offset=N` (`:85`) |
| `get_latest_module_version` (`get_latest_module_version.go:22`) | `module_publisher`, `module_name`, `module_provider` | `v1/modules/{pub}/{name}/{prov}` (`:70`) |
| `search_providers` (`search_providers.go:25`) | `provider_name`, `provider_namespace`, `service_slug`, `provider_document_type` (enum: resources, data-sources, functions, guides, overview, actions, list-resources); opt `provider_version` | `v1/providers/{ns}/{name}/{ver}` (`:111`) **and** `v2/provider-docs?filter[provider-version]=…&filter[category]=…&filter[language]=hcl&page[number]=N` (`:221`, paginated via `pkg/client/registry.go:105`), `v2/provider-docs/{id}` (`:249`) |
| `get_provider_details` (`get_provider_details.go:21`) | `provider_doc_id` | `v2/provider-docs/{id}` (`:55`) |
| `get_latest_provider_version` (`get_latest_provider_version.go:19`) | `namespace`, `name` | `v1/providers/{ns}/{name}` (`pkg/client/common.go:18`) |
| `get_provider_capabilities` (`get_provider_capabilities.go:26`) | `namespace`, `name`; opt `version` | `v1/providers/{ns}/{name}/{ver}` (`:90`), `v2/providers/{ns}/{name}?include=provider-versions` (`common.go:36`) |
| `search_policies` / `get_policy_details` | `policy_query` / `terraform_policy_id` | `v2/policies?page[size]=100&include=latest-version` (`search_policies.go:72`), `v2/{id}?include=policies,policy-modules,policy-library` (`get_policy_details.go:55`) |

Every one of those goes through one function, and the base URL is a
compile-time constant:

```go
// pkg/client/registry.go:24
const DefaultPublicRegistryURL = "https://registry.terraform.io"
// pkg/client/registry.go:71  (inside SendRegistryCall)
url, err := url.Parse(fmt.Sprintf("%s/%s/%s", DefaultPublicRegistryURL, ver, uri))
```

**No env var or flag redirects it.** `TFE_ADDRESS`/`TFE_TOKEN` feed the go-tfe
client used only by the `RequiresTFE` tools. The one env var that touches the
registry client is `TFE_SKIP_TLS_VERIFY` (`pkg/client/tfe_client.go:23`), read
by `parseTerraformSkipTLSVerify` (`pkg/client/common.go:91-103`) →
`GetHttpClientForSession` (`pkg/client/registry_client.go:52-56`) →
`CreateHTTPClient(insecureSkipVerify, …)`, which sets
`TLSClientConfig{InsecureSkipVerify: …}` (`registry.go:32`) **and**
`transport.Proxy = http.ProxyFromEnvironment` (`registry.go:34`). That pair is
the only no-fork redirect surface (design D below) — untested here, source-supported.
Also note `pkg/resources/resources.go:21` fetches module-authoring guides from
`raw.githubusercontent.com`, a second egress the offline guarantee must cover.

## 2. The equipping machinery that exists here, and what is missing

**What is hashed** (`gates/equipping.py`): `instruction.md` (or every
`steps/*/instruction.md`), then `_discover_equipping_files` — every file under
a `skills/` directory anywhere in the task dir, plus any file literally named
`mcp.json`, `.mcp.json`, `plugins.json`, `plugin.json`, `marketplace.json`
(`_MCP_CONFIG_NAMES`/`_PLUGIN_CONFIG_NAMES`, lines 45-48) — plus the resolved
image digest, plus `extra_cfg` (with `task.toml [metadata]
workspace_seed_sha256` folded in). `HASH_SCHEME_VERSION = 1`.

**How Harbor actually declares equipping** (harbor 0.9.0 in `.venv`):
- `task.toml [environment] mcp_servers` — a list of
  `MCPServerConfig{name, transport: "stdio"|"sse"|"streamable-http", url,
  command, args}` (`harbor/models/task/config.py:194`, `:334-357`; `"http"`
  is normalised to `"streamable-http"`), and `[environment] skills_dir`
  (`:200-204`), a path *inside the container*.
- Trial/CLI level: `--mcp-config <file>` (Claude-style `{"mcpServers":{…}}`
  or Harbor's `{"mcp_servers":[…]}`, `harbor/cli/utils.py:97-140`) and
  `--skill/--skills` dirs (each needs `SKILL.md`), merged by name with the
  task-level list in `Trial._init_agent` (`harbor/trial/trial.py:463-487`).
- **Claude Code gets no MCP CLI flag.** `harbor/agents/installed/claude_code.py`
  writes `{"mcpServers": …}` into `$CLAUDE_CONFIG_DIR/.claude.json`
  (`_build_register_mcp_servers_command`, `:978-1004`) and `cp -r
  {skills_dir}/* $CLAUDE_CONFIG_DIR/skills/` (`:949-961`) before invoking
  `claude --print --permission-mode=bypassPermissions …` (`:1144-1155`), with
  `$CLAUDE_CONFIG_DIR=/logs/agent/sessions`. User-scoped, so no trust dialog;
  there is no `--strict-mcp-config` anywhere in harbor.

**Holdout rule:** `generator/gen.py:5616 enforce_no_holdout_equipping` reuses
`gates.equipping._discover_equipping_files` over generated arm dirs and
hard-fails `make gen` when a `specs/split.yaml` **holdout** spec carries any
equipping file. Its runtime twin is `scripts/run-bench.sh:290-365`, which
refuses `--skill`/`--mcp-config` against a holdout task and records the flag
strings in `jobs/*/budget.json` `cli_equipping` (`:398-419`).

**Gap list for a modules-arm tuned row:**
1. **Nothing exists.** No task dir in the repo carries a `skills/`, `mcp.json`
   or `plugins.json`; the prereg §2.2 tuned column (Terraform MCP + Babenko
   skills + AWS Docs MCP) and ROADMAP M2 are entirely unbuilt.
2. **The hash misses Harbor's real channel.** `task.toml [environment]
   mcp_servers`/`skills_dir` are read by Harbor and *not* by
   `compute_equipping_hash` (which opens `task.toml` only for
   `workspace_seed_sha256`) — an inline `mcp_servers` block changes the trial
   and not the hash. `enforce_no_holdout_equipping` is blind to it too.
3. **`cli_equipping` records paths, not content.** `budget.json` holds
   `--mcp-config=./mcp.json`; two different files at that path hash alike, and
   nothing folds it into a row automatically (Slice F still pending).
4. No sidecar/compose support in the generator yet (`environment/docker-compose.yaml`
   exists only as `services:\n  main: {}`, `specs/SCHEMA.md:2427`), no manifest,
   no Babenko skill vendored, no AWS Docs MCP pin.

## 3. Four designs

Common to all: the sidecar from `tf-module-registry-loopback.md` already
speaks the *module registry protocol* (`/v1/modules/:ns/:n/:sys/versions`,
`…/:ver/download`) which is **not** what the MCP tools call. Any design that
serves the MCP tool set must additionally implement the **Registry HTTP API**
shapes from §1's table.

**A — real server, patched base URL (fork).** Replace the constant at
`registry.go:24` with an env read, build a bench image, point it at the
sidecar; the sidecar grows `/v1/modules/search`, `/v1/modules/{id}`,
`/v1/providers/…` and the `v2/provider-docs` JSON:API shape.
*Fidelity:* perfect (byte-identical names, schemas, output prose). *SSOT:*
good — answers come from the sidecar over the manifest. *Rejection:* poor —
every miss funnels through `SendRegistryCall`'s
`fmt.Errorf("error: %s", "404 Not Found")` and surfaces as *"no modules found …
try a different search term"*, i.e. a bad query, not a bounded environment;
fixing that means patching the handlers too. *Offline:* good once patched
(`pkg/resources`' GitHub fetches also need neutralising). *Runs:* stdio in the
agent image or `streamable-http` beside the sidecar. *Language:* Go + MPL
disclosure duty. *Effort:* high (Go in CI, v2 JSON:API emulation, rebase per
upstream release).

**B — bench-owned MCP server, same tool names/schemas (recommended).**
~400 lines of Python stdlib: JSON-RPC 2.0 over `streamable-http` inside the
existing sidecar process, advertising exactly the nine `registry`-toolset
tools with the §1 input schemas copied verbatim, answering from the manifest
and from the provider mirror's own `index.json` files.
*Fidelity:* high where it matters — a Babenko-style skill or a model that
knows the HashiCorp tool names calls the same names with the same arguments.
It is not byte-identical prose, and two tools cannot be answered honestly:
`search_providers`/`get_provider_details` return *registry docs markdown*,
which the filesystem mirror does not contain (it holds provider zips + per-version
JSON only). Options: derive terse attribute text from a build-time
`terraform providers schema -json` dump, or reject those two and let **AWS
Docs MCP** — already the prereg's fairness row for both TF arms — carry
provider docs. Prefer the latter; it keeps the tool honest and the scope small.
*SSOT:* best — the responder and the tool are one process over one manifest,
so they cannot disagree. *Rejection:* best — a miss returns a **successful**
tool result whose text says *"`terraform-aws-modules/eks/aws` is not available
in this environment; available modules: …"*, never an error that reads like an
outage or a bad query. *Offline:* absolute — no HTTP client exists in the
process. *Language:* Python stdlib (owner-approved). *Effort:* medium
(~2 days on top of the sidecar; MCP `initialize`/`tools/list`/`tools/call`
plus session header handling is small and testable with a stdlib client).
*Hash:* Harbor declares it as one `[environment] mcp_servers` entry with
`transport = "streamable-http"`, `url = "http://tf-registry:8082/mcp"` — see §5
for the hash amendment that must accompany it.

**C — no MCP (the untuned baseline, not the tuned row).** Sidecar's
`/v1/modules/search` endpoint plus the arm's one-line toolchain sentence.
*Fidelity:* low as a *tuned* row — a 2026 practitioner has an MCP server, and
claiming the tuned cell without one weakens prereg §2.2's symmetry principle.
Otherwise free, already designed, zero new surface: this is what the **untuned**
arm gets, and B's fallback if it slips.

**D — MITM proxy in front of the unmodified server.** Run upstream
`hashicorp/terraform-mcp-server:1.3.0` with
`HTTPS_PROXY=http://127.0.0.1:8888` + `TFE_SKIP_TLS_VERIFY=true` (§1) and a
TLS-terminating Python proxy that answers `CONNECT registry.terraform.io:443`
itself, serving allowlisted paths from the manifest and `404`-ing the rest.
*Fidelity:* perfect, no fork, no Go, no MPL duty. *Rejection:* worse than A —
a blocked path is indistinguishable from an upstream 404, retried 3× first.
*Offline:* rests on an env var whose documented meaning is TFE TLS verification
plus `ProxyFromEnvironment` semantics; one upstream refactor silently restores
egress, the one failure the offline guarantee cannot tolerate. *Effort:* medium,
verification burden the highest of the four. Keep as B's fidelity cross-check.

## 4. One manifest

`arms/hcl-modules/registry-manifest.yaml`, the single input to the image
build, the sidecar responder, the index tool, and the deny-list sweep:

```yaml
schema_version: 1
terraform: { min_version: "1.11.1" }
providers:                          # → mirror-src/main.tf is GENERATED from this
  - source: hashicorp/aws
    version: "6.58.0"
    platforms: [linux_arm64, linux_amd64]
    sha256: { linux_arm64: "…", linux_amd64: "…" }   # from the mirror's own JSON
  - { source: hashicorp/tls,  version: "4.1.0", … }  # pulled in by eks
modules:
  - id: terraform-aws-modules/s3-bucket/aws
    versions: ["5.16.1"]
    commit_sha: { "5.16.1": "5dc2f1f8…" }   # from upstream x-terraform-get ?ref=
    tree_sha256: { "5.16.1": "…" }          # per-file manifest digest, pruned tree
    aws_constraint: ">= 6.42"
    summary: "Private S3 bucket with policy, encryption and lifecycle inputs"
    decoy: false                            # unmarked in every agent-visible output
    requires_modules: []
  - id: terraform-aws-modules/kms/aws
    versions: ["4.2.2", "4.0.0"]            # 4.0.0 is eks'/route53's exact pin
    …
```

Consumers: (a) the Dockerfile vendoring step downloads each
`commit_sha` tarball, prunes, verifies `tree_sha256`; (b) a generator step
renders `mirror-src/main.tf` `required_providers` from `providers:` so the
mirror and the manifest cannot drift; (c) the sidecar answers `versions`/
`download`/`/v1/modules/search` from `modules:`; (d) the index tool answers
from the same in-memory load, and rejects anything absent with the available
set named; (e) the deny-list sweep runs `Spec`'s vocabulary check over every
`id`/`summary` (a decoy named after a trap leaks the answer —
`tf-module-registry-loopback.md` §7). Pinning: `sha256` of the canonical
manifest bytes goes into `extra_cfg` as `registry_manifest_sha256`, and the
arm image digest already covers the vendored bytes it produced.

## 5. Recommendation and phases

Ship **B**, after the arm. Untuned arm = **C** (sidecar search endpoint only,
no MCP, no skills). Order:

0. *(prerequisite)* modules arm lands: `tf-modules-arm.md` milestones 1-6.
1. **Hash amendment first** (independent of the arm, ~half a day): fold
   `task.toml [environment] mcp_servers` + `skills_dir` into
   `compute_equipping_hash` (bump `HASH_SCHEME_VERSION` to 2), teach
   `enforce_no_holdout_equipping` the same channel, and make
   `scripts/run-bench.sh` record `--mcp-config`/`--skill` *content* digests in
   `cli_equipping`. Without this a tuned row can be mislabelled, and gaps 2-3
   of §2 are live today regardless of this tool.
2. **Index tool in the sidecar**: MCP `streamable-http` endpoint beside the
   registry endpoints, nine tool names, manifest-backed answers, the
   "not available in this environment" rejection text, `search_providers`/
   `get_provider_details` declining in favour of AWS Docs MCP. Tests: schema
   parity against the §1 table, a rejection golden, and a no-socket assertion
   (the process opens no outbound connection).
3. **Tuned row equipping**: `[environment] mcp_servers` entry for the index
   tool + AWS Docs MCP, `skills_dir` with the vendored Babenko skill, all
   developed on the **train** split only.
4. **Amendment** (next free number is 44): the prereg §2.2 tuned cell for both
   TF arms is *the bench index tool*, not `hashicorp/terraform-mcp-server`,
   with §1's file:line evidence as the reason; record that provider *docs*
   come from AWS Docs MCP on those arms and that module/provider *lookup* is
   bounded by the allowlist. `tf-modules-arm.md` §2 already predicted this
   amendment; M2's H2 (staleness cost) becomes cheap to run, since a stale
   manifest is one field flip.
5. Optional: stand **D** up once in scratch against the real server to
   diff its prose output against the index tool's, as a fidelity check.

## 6. Sources

* `hashicorp/terraform-mcp-server` v1.3.0 (`943a44eb`): `LICENSE`,
  `version/VERSION`, `server.json`, `pkg/client/registry.go`,
  `pkg/client/common.go`, `pkg/client/registry_client.go`,
  `pkg/client/tfe_client.go`, `pkg/toolsets/{toolsets,registry}.go`,
  `pkg/tools/registry/*.go`, `pkg/resources/resources.go`,
  `cmd/terraform-mcp-server/init.go` — clone at
  `…/scratchpad/mcp/terraform-mcp-server`.
* Registry HTTP API (module search/versions, provider v1/v2 shapes):
  https://developer.hashicorp.com/terraform/registry/api-docs
* Module registry protocol: https://developer.hashicorp.com/terraform/internals/module-registry-protocol
* MCP transports (`stdio`, streamable HTTP): https://modelcontextprotocol.io/specification
* harbor 0.9.0 in `.venv`: `harbor/models/task/config.py:194,200-204,334-357`,
  `harbor/models/trial/config.py:52-63`, `harbor/trial/trial.py:463-487,560-599`,
  `harbor/cli/{trials.py:189-207,464-467, utils.py:97-140}`,
  `harbor/agents/installed/claude_code.py:949-1004,1113-1155`.
* This repo: `gates/equipping.py`, `generator/gen.py:5616`,
  `scripts/run-bench.sh:290-419`, `arms/hcl-raw/environment/{terraformrc,mirror-src/main.tf,Dockerfile:171-183}`,
  `specs/SCHEMA.md:52,2427`, `docs/prereg-iac-abstraction-benchmark.md` §2.2,
  `ROADMAP.md:242` (M2), `docs/design/{tf-modules-arm,tf-module-registry-loopback}.md`.
