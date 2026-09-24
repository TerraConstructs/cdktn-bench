# arms/hcl-modules

Fourth arm: **Terraform composed from `terraform-aws-modules` registry modules** —
the Terraform-native best-practice rung between hand-written HCL (`arms/hcl-raw`,
which is explicitly module-free) and a typed construct library (`arms/awscdk`,
`arms/terraconstructs`). It is an arm, not a scenario treatment: module use changes
the authoring substrate, so it is judged by identical metrics per arm
(`../../DECISIONS.md` Amendment 46, which closes ROADMAP open decision 4).

Why it exists: raw HCL alone is open to the objection that it is a strawman, since
practitioner Terraform is community modules. The arm is a falsification test of this
benchmark's headline, and its honest prior is a near-zero discovery tax — those
modules are among the most-represented IaC artifacts in any training corpus
(`../../ROADMAP.md` M3). The prediction under test: modules win on composition traps
and lose on property-semantics traps.

## State: image and sidecar, no task yet

`environment/` holds the arm image (`environment/Dockerfile`), the vendored module
tree, the registry responder and the compose sidecar, and `make build-arms` /
`make preflight` build and run it like any other arm. What is still missing is the
generator's side: `generator/gen.py` has no `write_environment()` branch and no
`ARM_MEMORY_MB` entry for the arm, so `ARMS_PENDING_IMAGE` still refuses to emit a
task, and no spec enables it (`arms.hcl_modules.enabled` defaults to false with a
reason naming the gap, `specs/SCHEMA.md` §1). `make gen-all` is therefore still
byte-identical, and the arm appears in no task path. Phase 5's pilot is what closes
that.

## The image

Derived from `arms/hcl-raw/environment/Dockerfile`: same digest-pinned base, same
pinned terraform 1.15.8 / opa / jq / hcl2json / AWS-CLI fetches with the same
probe-then-fallback and sha256 pins (`../../docs/asset-mirror.md`), same
`/app/project` workspace with the agent-owned `main.tf` split from the non-agent
`provider.tf`. The two Terraform arms must differ only in whether the agent composes
registry modules, or a cross-arm score difference could be a toolchain difference.

| path in the image | what it is |
| --- | --- |
| `/opt/terraform-plugin-mirror` | pre-warmed provider mirror, **eight** sources (`environment/mirror-src/main.tf`) |
| `/opt/terraform-modules` | the vendored `terraform-aws-modules` tree + `manifest.json`, COPYed from `environment/modules/` |
| `/opt/vendor_modules.py` | byte copy of `scripts/vendor_modules.py`; the build runs `--verify` over the tree |
| `/opt/tf-registry/responder.py` | the loopback registry; the sidecar's command |
| `/etc/terraform.d/cli.tfrc` | `filesystem_mirror` + the forced `registry.terraform.io` host block |
| `/opt/preflight/` | `preflight.sh` + four fixtures |

**Eight providers, not one.** `terraform init` resolves a module's whole tree, so a
provider declared only by a submodule the workspace never calls still has to be in
the mirror — and with no `direct {}` fallback its absence is a hard init failure.
`hashicorp/random` is reachable only that way (the `rds` decoy's `db_instance`
submodule, called unconditionally from its root) and is absent from
`docs/design/hcl-modules-spec-matrix.md` §4b's table, so
`generator/tests/test_hcl_modules_image.py` recomputes the union from the vendored
bytes rather than restating the table, and checks every pin against every `>=` floor
in the tree.

The tree names a ninth, `kreuzwerker/docker`, and the mirror deliberately omits it:
its only declarer `lambda//modules/docker-build` builds container images and needs a
Docker daemon the agent container has not got, and mirroring it measured **370s of a
415s** `terraform providers mirror` step (the other eight together take ~45s) against
Harbor's 600s `build_timeout_sec` for a cold task build. A workspace naming that
submodule fails `init` on the missing provider, which is the loud failure the absent
`direct {}` block exists to produce. The exclusion is one named entry in the test, so
a second one has to be argued rather than quietly added.

**No module byte is fetched at build time.** `environment/modules/` is committed
(`../../docs/hcl-modules-vendoring.md`), the Dockerfile COPYs it, and the build then
re-hashes the whole tree against `manifest.json` — a manifest that is computed and
never checked is this repo's signature failure mode.

## The sidecar

`environment/docker-compose.yaml` adds one service, `tf-registry`, that builds the
SAME context with the SAME Dockerfile as Harbor's agent service `main` and differs
only in its command, so the responder, the module bytes and the manifest are one
artifact and the sidecar cannot drift from the tree the agent reads
(`../../DECISIONS.md` Amendment 46 (a)). Verified: the two images have identical
`RootFS.Layers` and identical `Config`. They do **not** share an image ID — BuildKit
stamps each build with its own attestation — and collapsing them onto one would take
a fixed `image:` tag, which two concurrent trials of different tasks would race on.
Neither service sets `image:`, so Harbor's own image naming is untouched. `main` waits on the sidecar's healthcheck, because a `terraform init` one
second early fails with a connection error that reads like an offline-arm bug.

`environment/terraformrc`'s `host "registry.terraform.io"` block points `modules.v1`
at `http://tf-registry:8081/v1/modules/`, so Terraform reads the service address out
of the config and issues no `/.well-known/terraform.json` discovery request and no
DNS lookup at all. That is why `allow_internet` can stay at Harbor's default
(Amendment 46 (g)): masking the public registry does not depend on the network
policy. The block also restates `providers.v1`, because a `host` block replaces the
whole service map rather than overriding one entry.

Anything that is not a compose project substitutes loopback for the service name
into that same file rather than hand-writing a second config: `environment/preflight.sh`
does it with `sed`, and the host gates do it in `gates/tf_registry.py`.

## Preflight

`./preflight.sh` builds the image and runs `environment/preflight.sh` under
`docker run --network none`. With the responder started inside that same container on
loopback, it gates on: the tree still hashing to its manifest; `init` + `validate` of
a workspace naming `s3-bucket` 5.16.1; `init` + `validate` of one naming `route53`
6.5.1, whose own `main.tf` calls `kms` 4.0.0 by registry address (the transitive hop
the two-version allowlist exists for); `init` + `validate` of one naming `ecs` 7.6.1,
whose own submodules are relative paths; and `init` FAILING for `s3-bucket` 9.9.9. That
last one is asserted three ways — non-zero exit, no tarball served for 9.9.9, and the
responder's own 404 naming the newest version it holds — because a container with no
route to the sidecar also fails `init`.

Those four are the standing gate. The **whole** allowlist was walked once as an audit:
a loop `init`ing each of the 21 vendored `module@version` pairs in the image under
`--network none` came back 21/21 green with no discovery request, which is what makes
the eight-provider union a measured claim about every module rather than about the
three the preflight names.

`plan` is NOT attempted, unlike `arms/hcl-raw`'s preflight. Every candidate module
reads `data "aws_caller_identity"` to build an ARN or a policy
(`../../docs/design/hcl-modules-spec-matrix.md` §5), and no provider `skip_*` flag
suppresses an explicit data source; under `--network none` that read retries for
minutes rather than failing fast. `gates/aws_stub.py` answers it in the real gates,
and a single `docker run` has no stub.

The service NAME is not exercised there; the two-container compose shape is proven
separately by running Harbor's own base compose plus `environment/docker-compose.yaml`.

## Amendment 46 (c): half of it is void as built

No arm Dockerfile declares a `USER`, and `generator/gen.py` actively REFUSES one for
a seeded spec, because Harbor's `ScriptRunner` prepares `/logs/pre_invoke` as root
and then runs the seed script as the image's default user. The agent therefore runs
as uid 0 and file modes hide nothing from it: "the tree is unreadable to the agent
user" cannot be made true without a non-root agent user, which is a separate
decision. What stands in for it is content discipline — the vendored bytes are
upstream's own and `manifest.json` carries no bench judgement, in particular no
`decoy` flag; which four modules are bait lives only in
`../../scripts/vendor_modules.pins.json`, which reaches no build context.

The half that carries (c) is the second, and its wording in Amendment 46 is too broad
to implement as written: a registry module calls its own submodules by relative path,
so `ecs`, `eks` and `rds` each install `modules.json` entries whose `Source` is
`./modules/...`. The rule the phase-5 verifier implements is scoped to the calls the
ROOT module makes — an entry whose `Key` carries no dot — because those are the only
ones the agent wrote. Reading `/opt/terraform-modules` then tells an agent what exists
while copying it in is still not a solution. `environment/preflight.sh` asserts the
scoped rule against a fixture that installs three relative-source entries, so nothing
the image itself installs can trip the deny and the rule cannot pass vacuously.

## What the remaining phases add

| phase | deliverable |
| --- | --- |
| 3 | the plan normaliser (module resources hoisted from `resource_changes` with `after_unknown` carried, cross-boundary configuration references resolved) behind a zero-drift parity gate over every existing Terraform fixture, then red-green fixtures for module defaults |
| 4 | **done**: module delivery — the vendored module set, the registry sidecar, the search endpoint and the `/mcp` skeleton, the deny-list sweep over the manifest, preflight proving `terraform init` offline for all 21 vendored modules |
| 5 | this arm's environment tree and the pilot: three composition-trap scenarios with references and per-catch fixtures, `falsifiability` and `grading-proof` green, one live promotion trial |
| 6 | corpus roll-out |

Design: `../../docs/design/tf-modules-arm.md` (the arm),
`tf-module-registry-loopback.md` (the offline registry, executed against terraform
1.15.8), `registry-index-tool.md` (the M2 tuned equipping), `sast-module-handling.md`
and `plan-normaliser-survey.md` (the evidence behind the normaliser).

## Delivery shape (the Amendment 46 decisions this arm is built to)

- **The registry sidecar is this arm's own image run with a different `command`**
  (the responder), so one image digest in the equipping hash covers the responder,
  the module bytes and the manifest. Harbor merges a task's
  `environment/docker-compose.yaml` extra services and runs one compose project per
  trial, and the verifier executes in the same environment; the host gates start the
  same Python file as a subprocess.
- **The module tree is vendored in-repo** under `environment/modules/` (about 4 MB
  pruned, Apache-2.0, LICENSE files retained), with a manifest recording the upstream
  commit sha per module and a per-file sha256, refreshed by a script the owner runs.
  The image build fetches no module bytes from GitHub, so the host gates and the
  image share bytes by construction.
- **Every module call the root workspace makes must be a registry source**: a local
  `/opt/...` source is a deny, so module and version selection stay measured skills.
  Entries a registry module makes inside its own tree are out of scope, or the rule
  would refuse `ecs`, `eks` and `rds`. The companion decision — the tree unreadable
  to the agent user — is VOID as built, see "Amendment 46 (c)" above.
- **Version selection is real**: `kms` is served at 4.2.2 and 4.0.0 (the exact pin
  `eks` and `route53` carry), and the `eks` provider coupling is settled against the
  `hcl-raw` provider pin (`../../DECISIONS.md` Amendment 48).
- **A `/mcp` endpoint ships with the sidecar** from phase 4, and M2's index tool
  landed in it with no new hosting and no compose change: `/mcp` and the module
  registry protocol are the same process on the same port 8081.
- **`allow_internet` stays at Harbor's default**: the forced `host` override in the
  CLI config never consults DNS, so masking does not depend on it.

## The index tool (M2's tuned row)

`environment/tf-registry/responder.py` answers the nine tool names of
`terraform-mcp-server` v1.3.0's `registry` toolset — upstream's names and input
schemas, so a skill or a model that knows them calls the same tools with the same
arguments — from the vendored manifest and the provider mirror
(`--mirror-root`, default `/opt/terraform-plugin-mirror`). The HashiCorp server
itself cannot be the tuned row: v1.3.0 hard-codes the public registry URL
(`pkg/client/registry.go:24`) with no override. The per-tool table, the two
honesty properties and the test map are in `../../docs/gates.md#tf-registry`; what
is specific to this arm:

- **Module inputs and outputs come from the module's own `.tf` files**, read by a
  small stdlib HCL attribute reader in the responder. It reports source text and
  never evaluates: `type` and `default` are verbatim, and the one field it cannot
  read across 1257 inputs and 415 outputs (`rds`' heredoc description) is named in
  a `not_shown` list instead of guessed.
- **`//<path>` addresses a submodule.** `iam`'s root declares no inputs and no
  outputs at all — it is called through `//modules/iam-policy` and friends — so a
  tool that could only answer about roots would answer nothing for the module an
  agent writes.
- **No prose.** README, `docs/` and `examples/` are pruned from the vendored tree,
  so no answer reconstructs module documentation; provider *docs* come from AWS
  Docs MCP, prereg §2.2's fairness row for both Terraform arms.
- **Decoys stay unmarked.** The manifest carries no `decoy` flag (see "Amendment
  46 (c)" above) and neither does any answer built from it; a test asserts the
  string appears in no answer at all.
- **The untuned row is the same allowlist.** The search endpoint (design C) and
  the index tool (design B) are one process over one manifest, so the equipping
  levels differ in discovery tooling only.

## Equipping levels (M2 axis, `../../docs/prereg-iac-abstraction-benchmark.md` §2.2)

- **Baseline**: the central vendored `terraform-aws-modules` set at allowlisted
  versions served by the loopback registry sidecar, plus this arm's one-line
  toolchain sentence in the instruction — design C of `registry-index-tool.md`.
- **Tuned**: the bench-owned index tool in the same sidecar, plus AWS Docs MCP, plus
  the vendored authoring skill — design B. The HashiCorp Terraform MCP server is
  **not** the tuned equipping: v1.3.0 hard-codes the public registry URL
  (`pkg/client/registry.go:24`) with no override, so it cannot answer from the
  allowlist and cannot run offline.
- **`tuned-stale`**: the same MCP list and the same skill DIRECTORY name, with the
  skill at v1.0.0 — H2 isolates one variable, the guidance's own facts, and the
  level is therefore not observable from inside the container.

The material itself is corpus-wide under `../../equipping/`, keyed
`levels/hcl-modules.<level>.yaml`; a spec opts in with `equipping.levels`
(`../../specs/SCHEMA.md` §1.1). A tuned task of this arm differs from its bare
sibling in exactly two paths — `task.toml` (`skills_dir` +
`[[environment.mcp_servers]]`) and `environment/` (`equipping/` plus one appended
`COPY equipping/ /opt/equipping/`); `instruction.md`, `tests/` and `solution/` are
byte-identical, so both levels are graded by the same oracle.
`make equipping-check` / `make equipping-preflight` check that the declaration
matches the artifact (`../../docs/gates.md#tuned-equipping`). **Not yet runnable**:
AWS Docs MCP is not installed in this image, so the image half is red for both
tuned levels; the index tool itself needs no install (it is the sidecar).
