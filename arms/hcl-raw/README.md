# arms/hcl-raw

Primary arm: **hand-written Terraform HCL**, no modules (no `terraform-aws-modules`,
no local module indirection — resources authored directly, per Amendment 2).

## Contents

```
environment/
├── Dockerfile        # cdktn-bench/hcl-raw agent image
├── terraformrc        # TF_CLI_CONFIG_FILE: filesystem_mirror only, no direct{} network fallback
├── mirror-src/main.tf # build-time-only: `terraform providers mirror` input
├── fixtures/main.tf   # runtime preflight fixture: one aws_s3_bucket, dummy creds + skip_* flags
└── preflight.sh        # terraform version -> offline init -> offline validate -> best-effort plan
```

Per-scenario generated task dirs (via `generator/`) reuse this same `Dockerfile` and add
their own instruction text + starter HCL. Note the instruction is not always one root
file: a **multi-step** task has no root `instruction.md` at all — one per step, under
`steps/<name>/` (`specs/SCHEMA.md` §8.3, `DECISIONS.md` Amendments 26/27). A
**brownfield** task's starter HCL is not a skeleton but a hand-authored, plan-green
`workspace_seed` (§2.7 / Amendment 28).

## Pinned versions

| Component | Version | Source |
| --- | --- | --- |
| `terraform` CLI | **1.15.8** | direct download from `releases.hashicorp.com`, sha256-verified against hardcoded checksums (linux\_amd64 and linux\_arm64) from the published `terraform_1.15.8_SHA256SUMS`, not fetched-and-trusted at build time |
| `hashicorp/aws` provider | **6.58.0** | mirrored into the image via `terraform providers mirror`, which itself verifies HashiCorp's registry signature at build time (`Package authenticated: signed by HashiCorp` in the build log) — not the same version `arms/terraconstructs` mirrors (6.52.0); see `../../DECISIONS.md` "TF provider version per arm" |
| base image | `debian:bookworm-slim` | **digest-pinned** (`@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241`), not just tag-pinned — see `../../DECISIONS.md` "Pinning standard". Also carries the common agent-container baseline: `bash`, `git`, `curl`, `jq`, `unzip`, `ca-certificates`, AWS CLI v2 (see `../../DECISIONS.md` "Agent-container baseline contract") |

Both pins are current-stable as of 2026-08-06 (`checkpoint-api.hashicorp.com` /
`registry.terraform.io/v1/providers/hashicorp/aws/versions`). Bump both together and
re-run `preflight.sh` before merging a version bump.

**WORKDIR is `/app/project`** (was `/workspace` — changed to match `arms/awscdk` and
`arms/terraconstructs`, per the agent-container baseline contract above).

## The offline guarantee

`environment/terraformrc` (baked in at `/etc/terraform.d/cli.tfrc`, wired via
`TF_CLI_CONFIG_FILE`) declares **only** `filesystem_mirror`, no `direct {}` block:

```hcl
provider_installation {
  filesystem_mirror {
    path = "/opt/terraform-plugin-mirror"
  }
}
```

That's a hard fail-closed, not just a preference — any provider absent from the mirror
errors out immediately instead of silently reaching the network. The mirror is
populated once, at image-build time (`terraform providers mirror` needs network; that
step runs during `docker build`, never at container-run time).

`terraform init` and `terraform validate` need **nothing else**: `validate` only
consults the provider *schema*, which lives in the mirrored plugin binary, so no AWS
account, no credentials, no reachable network at all. Verified with
`docker run --rm --network none ... preflight.sh`.

## What `terraform validate` actually catches (evidence, not assumption)

The original plan doc (`docs/iac-abstraction-aws-bench-plan.md` line 115) claimed the
`s3-lambda-log-retention` seed scenario's headline catch — `retention_in_days = 10`, not
a valid `RetentionDays` enum value — "passes `validate`, dies at plan/apply-tier
validation" for the HCL arm. **That is false for the pinned provider (`hashicorp/aws
6.58.0`) and was never re-checked against it before being written down.** The AWS
provider's schema `ValidateFunc` for this attribute fires at `validate` time for any
statically-known (non-computed, non-unknown) value — the same tier `tsc` would catch the
CDK arm's equivalent typed-enum violation at. Reproduced directly, offline, inside
`cdktn-bench/hcl-raw:dev`:

```
$ terraform validate
Error: expected retention_in_days to be one of [0 1 3 5 7 14 30 60 90 120 150 180 365
400 545 731 1096 1827 2192 2557 2922 3288 3653], got 10

  with aws_cloudwatch_log_group.example,
  on main.tf line 22, in resource "aws_cloudwatch_log_group" "example":
  22:   retention_in_days = 10

Error: expected versioning_configuration.0.status to be one of ["Enabled" "Suspended"
"Disabled"], got NotARealStatus

  with aws_s3_bucket_versioning.example,
  on main.tf line 32, in resource "aws_s3_bucket_versioning" "example":
  32:     status = "NotARealStatus"

$ echo $?
1
```

(`plan` fails too, for the same reason — `validate` runs first and is the binding gate.)

**Consequence for scenario design (flagged for Slice D, before scenario specs freeze):**
any attribute with a static, enum-shaped `ValidateFunc` in the AWS provider's schema —
`retention_in_days` and `versioning_configuration.status` confirmed here, likely many
more (`ecs` launch types, `s3` ACLs, etc.) — is caught by HCL's cheapest tier
(`validate`), the same tier `tsc` catches CDK's equivalent typed-enum violation at. A
catch that relies on the type-vs-untyped asymmetry needs a value that is either (a) not
statically enum-constrained in the provider schema at all (structural/nested-attribute
placement errors, like the `ecs-swappiness` scenario's silently-ignored-unless-`maxSwap`
catch — no `ValidateFunc` can catch "this field is accepted syntactically but ignored
semantically"), or (b) a genuinely runtime-only constraint (cross-resource consistency,
account/region-dependent behavior) invisible to both `validate` and `tsc`. See
`docs/iac-abstraction-aws-bench-plan.md` line 115 (marked `[NEEDS REVISION — see
arms/hcl-raw/README.md]`) and `../../DECISIONS.md` "s3-lambda-log-retention catch is
falsified by the pinned provider".

## What `terraform plan` needs

`terraform validate` is the hard, unconditional gate. `terraform plan` has a strictly
higher bar because the AWS provider has to *configure* a working SDK client, which by
default makes a couple of real AWS API calls before it ever looks at your resources:

| Call | Purpose | Suppressed by |
| --- | --- | --- |
| `sts:GetCallerIdentity` | validate the supplied credentials are real | `skip_credentials_validation = true` |
| `sts:GetCallerIdentity` (again) | resolve the account id used to build ARNs | `skip_requesting_account_id = true` |
| region-name validation against a partition list | reject typo'd regions early | `skip_region_validation = true` |
| EC2 instance-metadata probe | opportunistic credential auto-discovery | `skip_metadata_api_check = true` |

`environment/fixtures/main.tf` sets all four plus static dummy credentials
(`access_key`/`secret_key`, never real). With those in place, **`terraform plan` for a
brand-new resource with no prior state and no data sources also succeeds fully
offline** — confirmed here the same way, `docker run --network none`. This is not a
general guarantee, though: a config gains a real network dependency the moment it adds
anything that has to *read* something from AWS to compute the plan —

- a `data "aws_*"` source (AMI lookup, existing VPC, current caller identity via the
  `aws_caller_identity` data source, etc.),
- a resource that already exists in Terraform state and needs a refresh,
- provider features that call AWS regardless of the `skip_*` flags (e.g. some
  regional endpoint resolution paths, or S3 bucket "already exists" checks under
  certain provider versions/configs) — **confirmed, not just hypothetical**, for
  `aws_sfn_state_machine` specifically (sfn-jsonata, Slice D): this resource's own
  `CustomizeDiff` runs a REAL `states:ValidateStateMachineDefinition` API call
  whenever `definition` changes, true for any brand-new resource, and none of the
  four `skip_*` flags above suppress it (they only cover the provider's own
  bootstrap calls, not a resource's own CustomizeDiff-triggered service call) —
  `terraform plan` for this resource type fails offline with
  `UnrecognizedClientException: The security token included in the request is
  invalid` against real AWS, confirmed against the pinned `hashicorp/aws 6.58.0`
  (unresolved upstream: `hashicorp/terraform-provider-aws` issue #39472). Fixed the
  same way `arms/terraconstructs`' `mock-sts.js` fixes its own analogous
  `data "aws_caller_identity"` gap: `environment/workspace/provider.tf`'s
  `endpoints { sfn = "http://127.0.0.1:17772" }` points at
  `environment/workspace/mock-sfn.py` (Python stdlib `http.server`, since this
  arm's image has no `node` — `python3` was added to `environment/Dockerfile`
  specifically for this fixture), started/stopped around the whole `plan_command`
  chain by `generator/gen.py::build_static_tiers_sh`'s hcl_raw branch. Harmless
  no-op for every scenario that never touches `aws_sfn_state_machine`.

For scenario/task authoring downstream of this arm: keep `plan`-tier oracle fixtures to
new-resource, no-data-source configs (as here) if the offline guarantee needs to hold;
anything else needs either a reachable AWS account, a mocked endpoint (see the
`aws_sfn_state_machine` case above for the pattern), or accepts `plan` as
network-dependent and gates on `validate` alone.

`terraform apply` is out of scope for this arm — never invoked in `preflight.sh`, no
credentials in the image are real, and the build plan (`docs/iac-abstraction-aws-bench-plan.md`
§Phase 2) only requires `validate` + `plan`, no deploy.

## Generated-task workspace split (Slice C generator, fixed 2026-08-06)

`environment/workspace/` ships **two** `.tf` files, not one:

- `main.tf` — `output_contract.entry_file` (`specs/SCHEMA.md` §2.4). Agent-owned:
  `generator/gen.py` overwrites this wholesale per scenario with a resource-only
  skeleton, and a normal agent solution rewrites it wholesale too — there is no
  reason for hand-written HCL to preserve boilerplate it never authored and the
  instruction never mentions.
- `provider.tf` — the offline provider bootstrap (`terraform {}` / `provider "aws"
  {}` block + the four `skip_*` flags + dummy credentials from "What `terraform
  plan` needs" above). **Not** agent-owned: byte-copied unmodified into every
  generated task (never regenerated per scenario, never listed as `entry_file`),
  and the generated instruction text tells the agent not to modify it — in every
  step's `instruction.md` on a multi-step task, which has no root one.

This split exists because the two used to be one file (the provider block at the
top of `main.tf`). A normal agent solution that fully rewrites `main.tf` from
scratch — completely reasonable behavior; the instruction never mentions the
fixture and an agent has no reason to preserve boilerplate it didn't write —
silently deleted the `skip_*`/dummy-credential lines along with it, and
`terraform plan` then failed offline with `Error: No valid credential sources
found` **even for an otherwise-correct solution**, scoring it 0.0. Reproduced
before the fix: a bare, oracle-correct `main.tf` (three resources, no provider
block) against the pre-split single-file workspace fails `terraform plan` with
exactly that error; the same `main.tf` against the split workspace (`provider.tf`
untouched alongside it) plans successfully. Splitting the fixture into a file the
generator never treats as `entry_file` makes this failure mode structurally
impossible — the file the agent both fully owns and fully rewrites is no longer
the same file the offline-plan fixture lives in.

## Build + verify locally

```bash
cd arms/hcl-raw/environment
docker build -t cdktn-bench/hcl-raw:dev .          # let BuildKit auto-resolve TARGETARCH
docker run --rm --network none cdktn-bench/hcl-raw:dev /opt/preflight/preflight.sh

# Equivalent, one command from the repo root (or ./arms/hcl-raw):
./preflight.sh
```

`--platform` is intentionally left unset in that command: `ARG TARGETARCH` in the
Dockerfile has **no default value** on purpose, so BuildKit auto-populates it from the
build host/`--platform` flag. (Giving it a literal default like `=amd64` shadows
BuildKit's auto-injected value — a real bug hit while authoring this Dockerfile: it
silently installed the amd64 terraform binary on an arm64 build host, which then only
ran because of qemu binfmt emulation. Fixed by leaving the ARG bare.)

## Result of the local verification run (2026-08-06)

- `docker build -t cdktn-bench/hcl-raw:dev .` — succeeded, arch `linux/arm64` (native
  host arch under Docker/colima).
- Image size: **755 MB** (`docker images` / `docker system df -v`; ~108 MB debian base +
  ~108 MB apt packages (`curl`, `unzip`, `jq`, `git`, `ca-certificates`) + terraform CLI
  binary + ~170 MB mirrored `hashicorp/aws` provider binary).
- `docker run --rm --network none cdktn-bench/hcl-raw:dev /opt/preflight/preflight.sh`
  — **PASS**: `terraform version` → offline `init` → offline `validate` all green, and
  in this run `plan` also succeeded fully offline (see caveats above — not a general
  guarantee for arbitrary future fixtures).

See `../../DECISIONS.md` Amendment 2: the `terraform-aws-modules` arm was dropped from
the v1 build (prereg deviation, user-directed) — this arm is raw HCL only.
