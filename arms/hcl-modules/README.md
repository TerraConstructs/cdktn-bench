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

## State: schema and plumbing only

`environment/` is empty and there is **no Dockerfile**, so there is no image, no
toolchain and no task: `generator/gen.py::ARMS_PENDING_IMAGE` refuses to emit this
arm, `make build-arms`/`make preflight` skip it, and no spec enables it
(`arms.hcl_modules.enabled` defaults to false with a reason naming the gap,
`specs/SCHEMA.md` §1). What exists today is the enum plumbing — `Arm`,
`ARM_DIRNAME`, `ARM_WORKSPACE_SUBDIR`, `shards.ARM_ORDER`,
`audit.ARM_TOKEN_PATTERNS` — plus the `predicted_tier_caught.hcl_modules_override`
tier column.

Authoring shape once the image lands: plain `.tf` files in the same
`environment/workspace` the `hcl-raw` Dockerfile COPYs to `/app/project`, validated
and planned with the same `terraform` binary, which is why the audit gate's evidence
patterns for this arm are hcl-raw's.

## What the remaining phases add

| phase | deliverable |
| --- | --- |
| 3 | the plan normaliser (module resources hoisted from `resource_changes` with `after_unknown` carried, cross-boundary configuration references resolved) behind a zero-drift parity gate over every existing Terraform fixture, then red-green fixtures for module defaults |
| 4 | module delivery: the vendored module set, the registry sidecar, the search endpoint, the deny-list sweep over the manifest, preflight proving `terraform init` offline |
| 5 | this arm's environment tree and the pilot: three composition-trap scenarios with references and per-catch fixtures, `falsifiability` and `grading-proof` green, one live promotion trial |
| 6 | corpus roll-out |

Design: `../../docs/design/tf-modules-arm.md` (the arm),
`tf-module-registry-loopback.md` (the offline registry, executed against terraform
1.15.8), `registry-index-tool.md` (the M2 tuned equipping), `sast-module-handling.md`
and `plan-normaliser-survey.md` (the evidence behind the normaliser).

## Delivery shape (owner-reviewable, built in phase 4)

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
- **The tree is unreadable to the agent user** in the agent container, and
  `.terraform/modules/modules.json` sources must be registry sources: a local
  `/opt/...` source is a deny, so version selection stays a measured skill.
- **Version selection is real**: `kms` is served at 4.2.2 and 4.0.0 (the exact pin
  `eks` and `route53` carry), and the `eks` provider coupling is settled against the
  `hcl-raw` provider pin (`../../DECISIONS.md` Amendment 48).
- **A `/mcp` endpoint ships with the sidecar** from phase 4 whose `tools/list` is the
  nine registry tool names and whose every call answers "not available in this
  environment" until M2 lands the bench-owned index tool, so M2 lands in place with
  no new hosting.
- **`allow_internet` stays at Harbor's default**: the forced `host` override in the
  CLI config never consults DNS, so masking does not depend on it.

## Equipping levels (M2 axis, `../../docs/prereg-iac-abstraction-benchmark.md` §2.2)

- **Baseline**: the central vendored `terraform-aws-modules` set at allowlisted
  versions served by the loopback registry sidecar, plus this arm's one-line
  toolchain sentence in the instruction — design C of `registry-index-tool.md`.
- **Tuned**: the bench-owned index tool in the same sidecar, plus AWS Docs MCP, plus
  the vendored authoring skill — design B. The HashiCorp Terraform MCP server is
  **not** the tuned equipping: v1.3.0 hard-codes the public registry URL
  (`pkg/client/registry.go:24`) with no override, so it cannot answer from the
  allowlist and cannot run offline.
