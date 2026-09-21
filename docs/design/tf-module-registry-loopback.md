# Offline loopback module registry for the TF-modules arm

Status: research memo, 2026-09-21. Answers the delivery question left open in
`docs/design/tf-modules-arm.md` §2 ("A loopback module registry… to verify
first: Terraform's rules on plain-HTTP discovery for a `host` override").
Everything marked *verified* was executed against `terraform v1.15.8`
(darwin_arm64) under `…/scratchpad/modreg`, with all outbound HTTP forced
through a dead proxy (`HTTP_PROXY=HTTPS_PROXY=http://127.0.0.1:9`, `NO_PROXY`
naming only the responder) — the `--network none` stand-in on macOS.

## 1. Headline: the transparent override works, over plain HTTP

Verified. A CLI-config `host` block that overrides `modules.v1` for
`registry.terraform.io` makes `terraform init` resolve
`source = "terraform-aws-modules/s3-bucket/aws"` + `version = "~> 5.16"`
from a loopback HTTP responder, fully offline, with no TLS, no certificate,
no `.well-known` request at all, and no change to what the agent writes.
The mechanism is `ForceHostServices` in `terraform-svchost/disco`, whose own
doc comment says it "prevents the receiver from attempting network-based
discovery for the given host"; the `Scheme: "https"` hardcoded in `disco.go`
applies only to the discovery fetch it skips. Exact working config:

```hcl
# /etc/terraform.d/cli.tfrc  (TF_CLI_CONFIG_FILE points here)
provider_installation {
  filesystem_mirror { path = "/opt/terraform-plugin-mirror" }   # unchanged
}
host "registry.terraform.io" {
  services = {
    "modules.v1" = "http://tf-registry:8081/v1/modules/"   # sidecar shape
    # "modules.v1" = "http://127.0.0.1:8081/v1/modules/"   # in-image shape
  }
}
disable_checkpoint = true
```

* `provider_installation` and `host` coexist in one file with no
  interaction: one offline run installed `hashicorp/aws v6.58.0` from the
  filesystem mirror and the modules from the responder, `init` + `validate`
  green, for a config using `s3-bucket` and `iam//modules/iam-role`.
* **Discovery is skipped entirely** with a `host` block present — the
  responder never saw `/.well-known/terraform.json` (its request log).
* **Non-loopback is fine**, so the compose-sidecar shape needs no
  self-signed CA: verified against a LAN IP (`http://192.168.50.246:8081/…`)
  and a DNS hostname (`http://192-168-50-246.nip.io:8081/…`) as well as
  `127.0.0.1`. There is no HTTPS requirement and no loopback special case on
  the overridden service URL. A literal compose service name was not
  exercised (no compose run here) but is the same code path: a plain-HTTP
  absolute URL whose host the Go HTTP client resolves.
* A `host "reg.localhost" {…}` override works the same way, with the agent
  writing `source = "reg.localhost/terraform-aws-modules/…"` (verified) —
  rejected here because it puts a non-production hostname in every source.
* **Without** an override, discovery is always HTTPS: `source =
  "reg.localhost:8081/…"` produced `GET
  https://reg.localhost:8081/.well-known/terraform.json … EOF`, and
  `localhost/…` is rejected outright ("invalid module registry hostname: must
  contain at least one dot"). The `host` services override is the *only* way
  to serve modules over plain HTTP.

## 2. What the responder must implement

Three endpoints; reference implementation (~90 lines of stdlib Python):
`…/scratchpad/modreg/serve.py` (`serve_any.py` binds `0.0.0.0`).

| request | response |
|---|---|
| `GET /.well-known/terraform.json` | `{"modules.v1":"/v1/modules/"}` — unused while the `host` block exists |
| `GET /v1/modules/:ns/:name/:sys/versions` | `200 {"modules":[{"versions":[{"version":"5.16.1"}]}]}` — `source`, `root`, `submodules`, `providers`, `deprecation` may all be omitted (verified) |
| `GET /v1/modules/:ns/:name/:sys/:ver/download` | `204` with `X-Terraform-Get:` and no body (what the real registry does: verified `204` + `x-terraform-get: git::https://github.com/…?ref=<sha>`) |

`X-Terraform-Get` semantics — the protocol doc states a value "beginning
with `/`, `./` or `../` … is resolved relative to the full URL of the download
endpoint"; all rows below verified:

| header value | result |
|---|---|
| `/opt/terraform-modules/s3-bucket-5.16.1` (bare path) | **resolved as a URL relative to the download endpoint** → `GET http://host:8081/opt/…` → 404. Bare paths do *not* mean "filesystem". |
| `file:///opt/terraform-modules/s3-bucket-5.16.1` | works; go-getter **symlinks** `.terraform/modules/<key>` at the vendored dir (no copy). Requires the tree to be visible *in the agent container* — wrong for a sidecar unless the vendor volume is mounted in both. |
| `/mod/s3-bucket-5.16.1.tar.gz` (relative archive) | **best for the sidecar**: resolved against the download URL → `HEAD`+`GET http://tf-registry:8081/mod/…tar.gz`, extracted as a real directory copy. The responder needs no knowledge of its own hostname. |
| absolute `http://host:8081/mod/….tar.gz` | works too; go-getter picks the unpacker from the `.tar.gz`/`.zip` suffix (add `?archive=tar.gz` if the path has no suffix). |
| `git::https://…?ref=<sha>` | what upstream returns; needs git + network — not for this arm. |

Submodule addresses need no extra work: `source =
"terraform-aws-modules/iam/aws//modules/iam-role"` hits the same *root*
`versions`/`download` endpoints and Terraform appends the subdirectory itself
(verified; `Dir` becomes `.terraform/modules/role/modules/iam-role`).

## 3. Integrity: there is none, and that is what makes this safe

Verified: after a module-based `init`, `.terraform.lock.hcl` holds only
`provider "registry.terraform.io/hashicorp/aws"` — zero module entries, zero
module hashes; `.terraform/modules/modules.json` records only
`{Key, Source, Version, Dir}` (`Source` keeps the registry hostname, e.g.
`registry.terraform.io/terraform-aws-modules/s3-bucket/aws`). The protocol has
no checksum field at all, so masking `modules.v1` can never conflict with a
lock file the way a provider mirror could. Integrity is ours to enforce at
image-build time (§5).

For grading, `modules.json` is the per-trial record of which module and
version the agent selected — the natural artefact for a "did it use modules,
and which" oracle.

## 4. Failure modes and the no-mirror fact

* Modules have **no** mirror mechanism. `filesystem_mirror` /
  `network_mirror` live inside `provider_installation` and are provider-only;
  there is no `terraform modules mirror` command. Vendoring + a responder (or
  local paths) is the whole option space.
* Responder down → **fail fast, ~1 s**, no hang: `Error accessing remote
  module registry … the request failed after 2 attempts … dial tcp
  127.0.0.1:8081: connect: connection refused` (verified).
* No override + no network → `failed to request discovery document … giving
  up after 4 attempt(s)`, also sub-second (verified).
  `internal/registry/client.go` has `defaultRetry = 1`,
  `defaultRequestTimeout = 10s`, and shares one `retryablehttp` transport with
  `disco`, so both env vars should apply — but in 1.15.8
  `TF_REGISTRY_DISCOVERY_RETRY=0`/`=2` still reported "4 attempts" and
  `TF_REGISTRY_CLIENT_TIMEOUT=1` changed only the error text. Treat the
  attempt count as not tunable; what keeps preflight fast is
  connection-refused, i.e. the responder in the same network namespace.

## 5. Vendoring at build time

Layout served: `/opt/terraform-modules/<module>-<version>/…`, one directory
per root module — exactly a GitHub tag tarball minus its top directory:
`curl -fsSL https://codeload.github.com/terraform-aws-modules/terraform-aws-<m>/tar.gz/refs/tags/v<ver>`
(all 16 repos tag releases `v<semver>`, verified).
**Do not pin the tarball's sha256**: the `refs/tags/v5.16.1` and
`<commit-sha>` codeload archives of s3-bucket 5.16.1 have identical extracted
trees but different gzip bytes
(`bbf69b67…` vs `acc75f5e…`, verified) — GitHub archive bytes are not a
stable pin. Pin instead the commit sha (the upstream registry's own
`download` response hands you one: `x-terraform-get: git::…?ref=5dc2f1f8…`)
plus a manifest of per-file sha256 over the extracted tree, and make that
manifest part of the equipping hash. Licence: every module in the set is
Apache-2.0 (`LICENSE` present in each tree) — redistribution inside the image
needs only the retained `LICENSE` files.

Sizes, extracted (verified): 17 MB as shipped, 3.8 MB after pruning
`examples/ tests/ wrappers/ docs/ .github/ *.md *.png`, and the pruned tree
still inits and validates. Largest survivors: security-group 1.1 MB (52
protocol submodules), eks 524 K, ecs 384 K, lambda 260 K, iam 240 K, vpc
236 K. Hash either the upstream tree or the pruned one — pick one, record it.

Pinned set as of today, with the root `required_providers` constraint on
`hashicorp/aws` (verified from each `versions.tf`):

| module@version (aws constraint) | vs mirror 6.58.0 |
|---|---|
| vpc@6.7.3, alb@10.5.1, ecr@3.2.0, lambda@8.8.2, acm@6.3.1, route53@6.5.1, dynamodb-table@5.5.2, sqs@5.2.2, sns@7.1.1, kms@4.2.2 + 4.0.0 — all `>= 6.28` (kms 4.0.0: `>= 6.0`) | ok |
| security-group@6.0.0 `>= 6.29`; ecs@7.6.1 `>= 6.41`; s3-bucket@5.16.1 `>= 6.42`; rds@7.2.2 `>= 6.28` but terraform `>= 1.11.1` | ok |
| iam@6.8.2 — root has no `versions.tf` (submodules only) | ok |
| **eks@21.25.1 — `>= 6.59`** | **fails** |

`eks` 21.25.1 is the only member that will not install against the pinned
mirror: `no available releases match the given constraints >= 6.0.0,
>= 6.59.0` (verified). Either bump the mirror (an amendment, per
`tf-modules-arm.md`) or pin an older `eks` (last 21.x with `>= 6.28`).

**Provider mirror is the real coupling, not just for eks.** Root modules
declare non-aws providers that `init` must resolve even when unused: `eks` →
`tls >= 4.0`, `time >= 0.9` (plus `cloudinit >= 2.0`, `null >= 3.0` from its
sub-tree); `lambda` → `external`, `local`, `null`. Verified: a bare
`module "eks"` fails init on all four against the aws-only mirror. Enabling
lambda or eks requires mirroring those too; the other 14 are aws-only at
root.

## 6. Transitive registry dependencies

Verified by grepping every non-`examples/tests/wrappers` `.tf` for a
non-relative `source`:

* `eks` 21.25.1 → `terraform-aws-modules/kms/aws` **exactly `4.0.0`**
  (`main.tf:369`).
* `route53` 6.5.1 → `terraform-aws-modules/kms/aws` **exactly `4.0.0`**
  (`main.tf:115`, the DNSSEC key).
* Nothing else. Every other nested call is relative (`./modules/…`:
  rds 5, eks 3, ecs 2 at root level), satisfied by the vendored tree.
* `lambda/modules/docker-build` declares `kreuzwerker/docker` (a *provider*,
  not a module) — only if that submodule is called.

So the responder must serve `kms` twice: `4.2.2` (what an agent would pick)
and `4.0.0` (the pin inside eks and route53). Verified end-to-end: `module
"r53"` at 6.5.1 offline pulled `r53.route53_dnssec_kms` = kms 4.0.0.

## 7. How the agent discovers what exists

There is no `terraform` CLI command that searches a registry, and the
protocol has no search endpoint (`/v1/modules/search` is a non-protocol
registry API, not something Terraform itself calls). Three candidates, and a
recommendation:

1. **Training data plus init errors.** The agent knows the
   `terraform-aws-modules/*` names but not our pinned versions. A wrong guess
   degrades gracefully and self-corrects (both verified): `version = "~> 4.0"`
   → *"There is no available version … The newest available version is
   5.16.1"*; an unvendored name → *"Module \"nope\" … cannot be found in the
   module registry at registry.terraform.io"*. One wasted turn per module, so
   this works with zero instruction text but costs turns and distorts the
   measure.
2. **An index the responder serves.** `serve.py` also answers
   `GET /v1/modules/search` with `{"modules":[{id, source, versions}]}` built
   from the vendored tree (verified by `curl`). Cheap, always in sync with
   the bytes, and `curl`-able by the agent — but it needs one instruction
   line telling it the URL, and it teaches the agent that this registry is
   unusual.
3. **Terraform MCP server — cannot be redirected.** In
   `hashicorp/terraform-mcp-server` v1.3.0 (2026-08-26) the public tools
   `search_modules`, `get_module_details`, `get_latest_module_version` build
   every URL from a hardcoded constant `DefaultPublicRegistryURL =
   "https://registry.terraform.io"` (`pkg/client/registry.go`), with no env
   var or flag to change it (`TFE_ADDRESS`/`TFE_TOKEN`/`TFE_SKIP_TLS_VERIFY`
   redirect only the go-tfe *private* tools `search_private_modules` /
   `get_private_module_details`). They also call the broader Registry HTTP API
   (`/v1/modules/search`, `/v1/modules/{ns}/{n}/{p}[/{v}]`), never the
   protocol's `/versions` or `/download`. So the MCP equipping level either
   keeps outbound access (breaking the offline guarantee and surfacing
   *upstream* versions we do not serve), is dropped, or is replaced by our own
   index tool over the vendored set. The last is the only airtight option, and
   it means the pre-registration's "Terraform MCP" equipping row is no longer
   literally that server — the amendment must say so.

Recommendation: a generator-owned bootstrap file in the workspace (beside
`provider.tf`, not agent-owned, so prompt parity holds) listing `source`,
available versions and a one-line purpose, *plus* the `/v1/modules/search`
endpoint as the self-service path — both generated from one manifest so they
cannot drift. Decoys go in the same manifest, unmarked: plausible-but-wrong
choices for the scenario (`eks` when nothing is Kubernetes, `security-group`
when the chosen module already manages rules, `rds` beside
`dynamodb-table`, `alb` beside `route53`), which is the selection cost M3
asked for. The deny-list sweep must cover the bootstrap file: a module named
after the trap leaks the answer.

## 8. Open items

* `plan` on this arm needs the STS stub the gates already run: module bodies
  contain `data "aws_caller_identity"` (verified: the `iam-role` submodule
  fails plan offline on STS while `init`/`validate` are green).
* Decide `file://` symlink vs served tarball: the symlink (in-image
  responder) is free but points `.terraform/modules/<key>` into a read-only
  tree — check teardown/idempotence tolerate that; the tarball (sidecar) gives
  a normal copy for a few hundred ms per module.

## 9. Sources

* Module registry protocol (endpoints, `X-Terraform-Get`, 204 semantics):
  https://developer.hashicorp.com/terraform/internals/module-registry-protocol
* Registry HTTP API (module list/search/versions/download):
  https://developer.hashicorp.com/terraform/registry/api-docs
* CLI config `host` blocks / service discovery and `provider_installation`:
  https://developer.hashicorp.com/terraform/cli/config/config-file
* `TF_REGISTRY_DISCOVERY_RETRY`, `TF_REGISTRY_CLIENT_TIMEOUT`:
  https://developer.hashicorp.com/terraform/cli/config/environment-variables
* Remote service discovery, HTTPS-on-any-port requirement:
  https://developer.hashicorp.com/terraform/internals/remote-service-discovery
* `terraform-mcp-server` v1.3.0 `pkg/client/registry.go`,
  `pkg/client/tfe_client.go`, `pkg/tools/registry/*.go`:
  https://github.com/hashicorp/terraform-mcp-server
* `ForceHostServices`: `hashicorp/terraform-svchost` `disco/disco.go`;
  consumed by terraform `internal/command/cliconfig` + `commands.go`
* go-getter (archive detection by suffix, `file://` symlink behaviour,
  `?archive=`): https://github.com/hashicorp/go-getter
* Upstream evidence that `download` returns 204 + `git::` URL:
  `curl -D - https://registry.terraform.io/v1/modules/terraform-aws-modules/s3-bucket/aws/5.16.1/download`
* Experiment artefacts (scratch, not in-repo) under `…/scratchpad/modreg/`:
  `serve.py`, `serve_any.py`, `cli-*.tfrc`, `work/t1`–`t6`, `vendor/`,
  `vendor-slim/`, `dl/` (tag tarballs + sha256s).
