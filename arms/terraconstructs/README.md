# arms/terraconstructs

Third, **limited-coverage** arm (Amendment 2, 2026-08-06): the
[`terraconstructs`](https://www.npmjs.com/package/terraconstructs) library —
AWSCDK-style L2 constructs, authored in TypeScript, that synthesize to plain
Terraform (via `cdktn` under the hood) instead of CloudFormation.

**Status: BUILT, preflight green.** Research verdict below; per-scenario
availability verdict for the four seed scenarios is in §4.

---

## 0. Provenance note (read this first)

`terraconstructs` (npm) and its underlying `cdktn` / `cdktn-cli` (the fork of
HashiCorp's `cdktf`/`terraform-cdk`, published under the `open-constructs`
GitHub org as "CDK Terrain") are maintained by **so0k**, npm email
`vincent.drl@gmail.com` — **the same account this benchmark repo's owner
(Vincent) uses.** This surfaced during registry research (`npm view
terraconstructs`, `npm view cdktn`), not from anything in the task prompt, so
it's flagged here transparently rather than silently built around.

What this means and doesn't mean:
- It **is** a real, working, published, Apache-2.0 project with an actual
  GitHub org (`TerraConstructs/base`, `open-constructs/cdk-terrain`), real
  version history back to `0.0.8` (npm, first published 2024-12-23), a
  documented workshop site, and source that — where checked against
  `aws-cdk-lib` below — is a faithful, sometimes byte-for-byte, port.
- It **is** a small/personal-scale project (single primary maintainer per npm
  `maintainers`), not an org-backed one — consistent with its own "Alpha"
  self-description.
- Because the benchmark author and the library's maintainer are the same
  person, **this arm's "limited coverage" framing should be read as
  self-reported by the person building both**, not as independent
  third-party validation. The coverage table below is this agent's own
  source-level verification (grepping the actual `src/aws/**` tree and
  diffing specific behaviors against the local `aws-cdk` clone), done
  specifically so the verdict doesn't rest on trust alone. Still worth an
  explicit human sign-off given the relationship — see "Open items" at the
  end.

---

## 1. What it is, how synth works

- **Package**: `terraconstructs` on npm, current `0.2.13` (published
  2026-07-27). Peer-depends on `cdktn` (not `cdktf` — see below),
  `constructs`, `@cdktn/provider-{aws,tls,time,docker,cloudinit,archive}`,
  and two small `@aws-cdk/*` metadata packages (`cloud-assembly-schema`,
  `region-info` — reused as-is from upstream AWS CDK, unforked).
- **`cdktn` is a rebrand/fork of `cdktf`**, not a different tool: same CLI
  shape, and its **config file is still literally named `cdktf.json`**
  (confirmed against the fork's own `examples/typescript/aws-prebuilt`
  template — there is no `cdktn.json`). The CLI binary is `cdktn`
  (`cdktn-cli` package, `bin: {"cdktn": "bin/cdktn"}`).
- **Synth is `cdktn synth`**, which shells out to the app command in
  `cdktf.json`. Here that command is
  **`npx tsc -p tsconfig.json && node main.js`** — a real `tsc` compile
  (emitting `main.js`/`lib/*.js` in place; the tsconfig sets no `outDir`)
  chained ahead of plain `node` on the freshly-emitted JS. So synth still
  type-checks your TypeScript, and a type error still short-circuits into a
  synth failure exactly as it did under the previous `npx ts-node main.ts`,
  but the type-check and the execution are now *sequential processes* —
  peak RSS is `max(compile, synth)` rather than ts-node's concurrent sum
  (2,385 → ~1,092 MB measured; `docs/ts-runtime-spike2-results.md`). The
  compile is **chained into the app string on purpose**: with a bare
  `node main.js`, editing `main.ts`/`lib/scenario-stack.ts` into a
  type-broken state would still synth exit-0 off the stale good JS
  (`noEmitOnError: true` means a failed build never overwrites it) — a
  broken solution scoring as correct. Output lands at
  `cdktf.out/stacks/<stack-id>/cdk.tf.json` — plain Terraform JSON, one file
  per stack, no CloudFormation involved at any point.
- **Fully offline.** `@cdktn/provider-aws` ships **prebuilt, jsii-generated
  npm bindings** for the whole `terraform-provider-aws` schema — there is no
  `cdktn get` step and no network call needed to synth (verified: this
  arm's preflight runs `docker run --network none` and passes). `terraform
  init`/`validate`/`plan` (needed for the arm's actual oracle gate, not for
  synth) still need the provider binary/plugin available, same as the
  `hcl-raw` arm.
- **Construct shape mirrors AWS CDK deliberately**: `App` (from `cdktn`) →
  `AwsStack` (terraconstructs, replaces CDK's `Stack`/CDKTF's
  `TerraformStack`) → constructs like `storage.Bucket`,
  `compute.Function`, `cloudwatch.LogGroup`, with the same `Grant`/`IGrantable`
  IAM permission model as `aws-cdk-lib`.

---

## 2. Version pins (and why these exact ones)

Pinned to what `terraconstructs@0.2.13` was **itself built and tested
against** (its own `devDependencies`), not just "whatever satisfies the
peer-range floor" — maximizes the chance the coverage actually matches what
was verified upstream:

| Package | Pinned | Peer range required | Latest on npm (2026-08-06) |
|---|---|---|---|
| `terraconstructs` | `0.2.13` | — | `0.2.13` |
| `cdktn` | `0.23.0` | `^0.23.0` | `0.23.4` |
| `cdktn-cli` | `0.23.0` | (devDep) | `0.23.4` |
| `constructs` | `10.6.0` | `^10.6.0` | `10.8.1` |
| `@cdktn/provider-aws` | `24.8.0` | `^24.8.0` | `24.12.0` |
| `@cdktn/provider-archive` | `13.1.0` | `^13.1.0` | `13.1.0` |
| `@cdktn/provider-cloudinit` | `13.1.0` | `^13.1.0` | `13.1.0` |
| `@cdktn/provider-docker` | `15.3.0` | `^15.3.0` | `15.3.0` |
| `@cdktn/provider-time` | `13.1.0` | `^13.1.0` | `13.1.0` |
| `@cdktn/provider-tls` | `13.1.0` | `^13.1.0` | `13.1.0` |
| `@aws-cdk/cloud-assembly-schema` | `49.4.0` | `^49.4.0` | `54.16.0` (out of peer range) |
| `@aws-cdk/region-info` | `2.233.0` | `^2.233.0` | `2.263.0` |
| `typescript` | `5.7.3` | `~5.7` | — |
| `ts-node` | `10.9.1` | — | — (no longer on any execution path: the `cdktf.json` app command is `npx tsc … && node main.js`; the pin is kept only so dropping it doesn't force a `package-lock.json` regeneration) |
| `terraform` (CLI, apt) | `1.15.8` | — | `1.15.8` (current stable, 2026-07-08) |
| `hashicorp/aws` (TF provider, mirrored) | `6.52.0` | fixed by `@cdktn/provider-aws@24.8.0`'s jsii bindings (not a peer range — the generated `cdk.tf.json`'s `required_providers.aws.version` hardcodes this) | `6.58.0` (`arms/hcl-raw`'s independent pin — see `../../DECISIONS.md` "TF provider version per arm" for why the two TF arms don't share one version) |
| `node` | `20.20.2` (base image `node:20-bookworm-slim`) | `>=20.9.0` | — |

Note `@aws-cdk/cloud-assembly-schema`'s peer range (`^49.4.0`) caps at
`<50.0.0` under npm's caret rule — the registry's overall "latest" (`54.16.0`)
is **not** installable here without violating the peer contract; the
Dockerfile pins the highest version actually inside `49.x` (`49.4.0`, which
is also the newest `49.x` release).

---

## 3. Coverage table (source-verified against `src/aws/**`)

`terraconstructs` ports **the majority of `aws-cdk-lib`'s L2 surface for a
single cloud** (AWS only — the project's own roadmap says GCP/Azure L2s are
"next", i.e. not yet present). Verified by listing
`github.com/TerraConstructs/base`'s `src/aws/**` tree directly (not from
marketing copy):

| Area (`src/aws/<dir>`) | AWS services covered | Notes |
|---|---|---|
| `storage` | S3 (bucket, policy, notifications, website config, lifecycle), DynamoDB (table, grants), ECR (repository, lifecycle) | |
| `compute` | Lambda (function, alias, event sources, URLs, VPC config), API Gateway REST (`RestApi`, `SpecRestApi`, methods, integrations, authorizers, usage plans, stages), ECS (cluster, EC2 + Fargate + external launch types, container definitions, linux parameters, log drivers), Step Functions (state machine, all state types, task integrations), EC2/VPC (VPC, subnets, security groups, NAT, VPN, client VPN, launch templates, ASG), ELBv2 (ALB, NLB, target groups) | Large and broad — this is the biggest ported surface |
| `cloudwatch` | Alarms (incl. composite), dashboards, log groups/streams, metric filters, subscription filters, log-based queries | |
| `iam` | Roles, users, groups, managed/inline policies, policy statements, grants, principals, OIDC/SAML providers, instance profiles | |
| `encryption` | KMS (key, alias, rotation), Secrets Manager (secret, rotation) | |
| `edge` | CloudFront (distribution, origin, response-headers policy, key-value store, CloudFront Functions), Route53 (zone, records, DNS aliases), ACM (certificate) | |
| `notify` | SNS (topic, subscriptions), SQS (queue, policy), EventBridge (event bus, rules, targets, archive), Kinesis (stream) | |
| `network` | Simple VPC helper constructs | Thinner than `compute`'s own VPC support |

**Confirmed gap, source-verified**: **Step Functions has no JSONata /
`QueryLanguage` support at all.** Grepped every file under
`src/aws/compute/{state-machine.ts,state-machine-fragment.ts,
stepfunctions-api.ts,states/*.ts,task-*.ts}` for `jsonata`/`QueryLanguage` —
zero matches. Only classic JSONPath-mode ASL (`ResultPath`, `Parameters`,
`InputPath` etc.) is portable. Confirmed via GitHub code search there's no
open PR adding it either (one unrelated open PR, `#137`, ports a
`BatchSubmitJob` SFN task — nothing about query language). This is a real,
current gap, not a stale doc.

**Stability signal**: the npm package's own `keywords`/description say
"Alpha". Construct-level JSDoc and structure closely mirror `aws-cdk-lib`
(same prop names, same defaults, same validation messages in the two areas
diffed below) — reads as a genuine line-by-line port for the modules it
covers, not a thin reimplementation.

---

## 4. Per-seed-scenario verdict

> **Point-in-time coverage analysis — the FOUR ORIGINAL SEED SCENARIOS only.**
> This table predates `apigw-redeploy` (multi-step) and
> `named-resource-replacement` (brownfield) and does not cover them. It is not
> the current per-scenario coverage list; for that, read each spec's own
> `arms.terraconstructs.enabled`/`reason` block, which is the authority and is
> required to be independently checkable against §3/§4 below.

Checked against the local `aws-cdk` clone the same way the seed-scenario
catches were originally verified (per `docs/iac-abstraction-aws-bench-plan.md`
Phase 1 table).

| Scenario | Verdict | Evidence |
|---|---|---|
| **s3-lambda-log-retention** | **SUPPORTED** | `storage.Bucket` (`src/aws/storage/bucket.ts`) + `compute.Function` (`src/aws/compute/function.ts`) + S3→Lambda notification wiring (`src/aws/storage/bucket-notifications.ts`, has a dedicated `LAMBDA` destination type) + `cloudwatch.LogGroup` (`src/aws/cloudwatch/log-group.ts`) with a typed `RetentionDays` enum (`src/aws/log-retention.ts`). **The exact same catch reproduces**: `ONE_WEEK = 7`, `TWO_WEEKS = 14` — no literal `10` exists in the enum, confirmed by direct source read. Since `RetentionDays` is a TS enum, `retention: 10` fails `tsc` the same way it does against `aws-cdk-lib`. This preflight's `main.ts` exercises exactly this construct pair. |
| **ecs-swappiness** | **SUPPORTED, catch reproduces byte-for-byte** | `src/aws/compute/ecs/linux-parameters.ts` has a typed `swappiness?: number` prop, a synth-time `ValidationError` for non-integer/out-of-0-100-range values (matches `aws-cdk-lib`'s `linux-parameters.ts:128-134`), **and the identical silent-drop-unless-`maxSwap`-is-set behavior**: `this.swappiness = props.maxSwap ? props.swappiness : undefined;` (line 108) — same construct, same footgun, same line-level logic as the CDK original this scenario was designed against. |
| **sfn-jsonata** | **NOT SUPPORTED — exclude from this arm** | No JSONata/`QueryLanguage` support anywhere in the Step Functions construct (§3). The scenario's core catch (an embedded `{% ... %}` JSONata expression that's wrong, invisible to the type system) has no substrate to exist in: there's no way to author a JSONata-mode state machine with this library at all, so there's nothing for the anti-L2 catch to be planted in. Recommend: **this arm's applicable scenario set excludes `sfn-jsonata`**, consistent with the "limited-coverage third arm... running only scenarios its L2 coverage supports" framing in Amendment 2. Do not author a JSONPath-mode variant just for this arm — that would break prompt/catch parity with the other two arms (prereg §6). |
| **apigw-openapi** | **SUPPORTED** | `compute.SpecRestApi` + `ApiDefinition.fromInline()` / `.fromAsset()` (`src/aws/compute/api-definition.ts`) cover exactly the v1 scope (OpenAPI spec supplied inline or as a local asset, per-route Lambda integrations via `compute.integrations`, deployment/stage wiring). Only `ApiDefinition` from an **S3 location** is unimplemented (explicitly commented out in source: `"s3location not supported by Terraform Provider AWS"`) — irrelevant here since the scenario's v1 scope never needed S3-sourced specs. |

**Net: 3 of 4 seed scenarios supported (s3-lambda-log-retention,
ecs-swappiness, apigw-openapi); sfn-jsonata is out of scope for this arm.**

---

## 5. Delivered

```
arms/terraconstructs/
├── README.md                    (this file)
└── environment/
    ├── Dockerfile                node:20.20.2-bookworm-slim (digest-pinned) + pinned toolchain (§2)
    ├── preflight.sh              versions + offline `cdktn synth` + output assertions + offline `terraform init`/`validate`
    ├── terraformrc                filesystem_mirror-only CLI config (byte-for-byte same contract as arms/hcl-raw)
    ├── mirror-src/main.tf         build-time-only: `terraform providers mirror` input (hashicorp/aws 6.52.0)
    └── app/                      minimal preflight app (not a scenario task)
        ├── package.json
        ├── package-lock.json      committed — `npm ci` in the Dockerfile is reproducible
        ├── cdktf.json             {"language":"typescript","app":"npx tsc -p tsconfig.json && node main.js"}
        ├── tsconfig.json
        ├── main.ts                App/provider bootstrap only — imports lib/scenario-stack.ts
        └── lib/
            └── scenario-stack.ts  PreflightStack: AwsStack → Bucket + LogGroup(RetentionDays.TWO_WEEKS)
```

`environment/app/` here is this arm's own toolchain smoke test — not one of
the per-scenario task dirs the generator will produce in Slice C. Those will
reuse this Dockerfile's toolchain pins and get their own `lib/scenario-stack.ts`
per scenario (see "Generated-task workspace split" immediately below).

### Generated-task workspace split (Slice C generator, fixed 2026-08-06)

`main.ts` and `lib/scenario-stack.ts` are two separate files on purpose, not
one — same reasoning as `arms/awscdk`'s `bin/app.ts` / `lib/example-stack.ts`
split:

- `lib/scenario-stack.ts` — `output_contract.entry_file` for generated tasks
  (`specs/SCHEMA.md` §2.4). Agent-owned: `generator/gen.py` overwrites this
  wholesale per scenario with a resource-only `ScenarioStack` skeleton, and a
  normal agent solution rewrites it wholesale too.
- `main.ts` — the `App`/`AwsStack` bootstrap: just `providerConfig: { region:
  "us-east-1" }`, no explicit credentials of any kind — the AWS provider's own
  default credential chain resolves the ambient credentials aws-bench stages
  for the trial. **Not** agent-owned: regenerated by the generator every run
  (like `bin/app.ts`), never listed as `entry_file`, and the generated
  instruction text tells the agent not to modify it — in every step's
  `instruction.md` on a multi-step task, which has no root one
  (`specs/SCHEMA.md` §8.3, `DECISIONS.md` Amendments 26/27).

The split matters regardless of what the bootstrap contains: a normal agent
solution that fully rewrites `main.ts` from scratch (entirely reasonable; the
instruction never mentions the bootstrap) must never be able to delete the
provider bootstrap by rewriting the one file it owns — the identical reasoning
behind `arms/hcl-raw`'s `main.tf`/`provider.tf` split. Splitting the stack
body into `lib/scenario-stack.ts` (now `entry_file`) out of `main.ts` (now the
non-agent-owned bootstrap, no longer `entry_file`) makes the bootstrap immune
to an agent's full rewrite of the file it owns.

## 6. Build + preflight result

**Build context is `environment/` itself, not the arm root.** aws-bench/Harbor
always builds a task's `environment/` directory AS the Docker build context
(`harbor/environments/docker/docker.py` `context_dir=self.environment_dir`) —
it never uses the arm root as context, and there is no nested `environment/`
inside `environment/` for a context-root-prefixed `COPY` to resolve against.
Every `COPY` in the Dockerfile is context-relative (`COPY app/...`, `COPY
mirror-src/...`, `COPY preflight.sh ...`), matching `arms/awscdk` and
`arms/hcl-raw`:

```
cd arms/terraconstructs/environment && docker build -t cdktn-bench/terraconstructs:dev .
docker run --rm --network none --memory 4g cdktn-bench/terraconstructs:dev    # preflight PASSED
```

(`--memory 4g` because of the OOM finding in §"Memory finding" below — the
host Docker daemon's own memory ceiling matters here even though the build
step itself doesn't run `tsc`.)

See `../../DECISIONS.md` "Arm build-context contract" for why this matters:
the copy-the-arm-environment-into-a-task pattern
(`tasks/anchor/smoke/environment/` is a byte-copy of `arms/awscdk/environment/`)
requires every arm's Dockerfile to build with `environment/` as context.

Preflight output (versions, then offline synth, then structural assertions
on the synthesized `cdk.tf.json`, then offline `terraform init` +
`terraform validate` against the pre-warmed provider mirror — see
"Offline terraform tier" below):

```
node:            v20.20.2
npm:             10.8.2
typescript:      Version 5.7.3
cdktn (cli):     0.23.0
terraform:       1.15.8
terraconstructs: 0.2.13

Generated Terraform code for the stacks: cdktn-bench-preflight
resource types found: aws_cloudwatch_log_group, aws_s3_bucket
OK: aws_s3_bucket + aws_cloudwatch_log_group present, retention_in_days=14

=== provider filesystem mirror contents ===
/opt/terraform-plugin-mirror/registry.terraform.io/hashicorp/aws/6.52.0.json
/opt/terraform-plugin-mirror/registry.terraform.io/hashicorp/aws/index.json
/opt/terraform-plugin-mirror/registry.terraform.io/hashicorp/aws/terraform-provider-aws_6.52.0_linux_arm64.zip

=== terraform init (offline: filesystem_mirror only, no direct{} fallback) ===
Terraform has been successfully initialized!

=== terraform validate (offline) ===
Success! The configuration is valid.

preflight PASSED
```

Ran with `--network none` to prove the "offline" claim, not just assert it —
now for the `terraform init`/`validate` tier as well as `cdktn synth`, not
just synth (see "Offline terraform tier" below for why the old synth-only
preflight was vacuous with respect to the tier this arm is actually graded
on).

### Offline terraform tier (`terraform validate`, mirroring arms/hcl-raw)

The plan (`docs/iac-abstraction-aws-bench-plan.md` Phase 2) requires both TF
arms to run `terraform validate` -> `terraform plan` in-image, no
credentials, no apply. This arm's Dockerfile now runs `terraform providers
mirror` at build time (same mechanism as `arms/hcl-raw/environment/Dockerfile`)
and ships a `filesystem_mirror`-only `terraformrc`
(`environment/terraformrc`, byte-for-byte the same contract as
`arms/hcl-raw`'s), so `terraform init`/`validate` need zero network access at
container-run time — verified above with `docker run --network none`.

**Mirrored provider version is 6.52.0, not 6.58.0 (arms/hcl-raw's pin).**
`@cdktn/provider-aws@24.8.0`'s jsii bindings hardcode
`terraform.required_providers.aws.version = "6.52.0"` in every synthesized
stack (verified by running this arm's own `cdktn synth` and reading the
emitted `cdk.tf.json`'s `terraform{}` block) — mirroring any other version
would make `terraform init` fail to find a matching package. See
`../../DECISIONS.md` "TF provider version per arm" for why the two TF arms
are not forced onto one shared provider version.

`terraform plan` is deliberately **not** run by this preflight (same split as
`arms/hcl-raw`): plan needs a real AWS account to authenticate against, which
this build-time smoke test has no business reaching. Per-scenario generated
`tests/static_tiers.sh` runs `plan` (and, for a mutating scenario, `apply`)
against a real account with the ambient credentials aws-bench stages for the
trial — see `arms/hcl-raw/README.md` "What `terraform plan` needs".

### Memory finding (record for Slice C/D task authoring)

> Historical record, since superseded by measurement: the OOM risk was
> re-measured in `docs/ts7-spike-results.md` and
> `docs/ts-runtime-spike2-results.md`, and the shape this section describes
> (an in-process `ts-node` type-check inside the synth process) was removed —
> `DECISIONS.md` Amendment 25. Peak RSS is now `max(compile, synth)`, not the
> concurrent sum. The memory *class* of risk below still explains why.

`tsc`/`ts-node` type-checking against terraconstructs + the full
jsii-generated `@cdktn/provider-aws` type surface is genuinely memory-heavy —
this is the same class of risk the build plan already flags for the CDK
Tier-0 `cdk synth` oracle (`docs/iac-abstraction-aws-bench-plan.md`, "chant-
bench's CDK-synth-OOM incident"). Observed directly while building this arm:

- With the local Docker VM (colima) capped at its **default 2 GiB**, both
  `npx tsc --noEmit` and full (non-transpile-only) `cdktn synth` reliably
  **OOM-killed** (`FATAL ERROR: ... JavaScript heap out of memory`,
  container exit 137).
- Bumped the local VM to **6 GiB / 4 CPU** (`colima stop && colima start
  --memory 6 --cpu 4`) — both now pass cleanly in ~4-5s.

**Action for later slices**: any `task.toml [environment]` using this arm's
Dockerfile should set `memory_mb >= 4096` (the `awscdk` arm will very likely
need the same floor, for the same reason — `aws-cdk-lib`'s own type surface
is comparably large). Below that floor, treat an OOM the same way the plan
doc already prescribes for the CDK oracle: **infrastructure-invalid, not a
scored failure** — never record it as "the construct doesn't type-check."

---

## 7. Overall verdict

**USABLE as the third, limited-coverage arm.** Not dead, not broken — a real
port with source-verified fidelity to `aws-cdk-lib` on the two scenarios
diffed line-by-line (log retention enum, ECS swappiness silent-drop). Ships
prebuilt provider bindings so synth is genuinely offline. One real, confirmed
coverage gap (Step Functions JSONata) that excludes exactly one of the four
seed scenarios, which is precisely the outcome Amendment 2 anticipated by
scoping this arm to "only scenarios its L2 coverage supports."

No pulumi, no chant, no terraform-aws-modules — see `../../DECISIONS.md`
Amendment 2.

## 8. Open items needing Vincent's input

1. **Provenance disclosure (§0)**: confirm you're fine with the benchmark
   including an arm built on a library you personally maintain, documented
   transparently rather than substituted quietly. No action needed if so —
   flagging so it's a decision, not an accident.
2. **sfn-jsonata exclusion (§4)**: confirm excluding this arm from that
   scenario (rather than, say, dropping the scenario from the whole
   benchmark, or writing a JSONPath-only variant) is the right call — this
   follows Amendment 2's wording but is worth an explicit sign-off since it
   shrinks this arm's n from 4 scenarios to 3 relative to `awscdk`/`hcl-raw`.
3. **Memory floor (§6)**: `memory_mb >= 4096` in this arm's future
   `task.toml [environment]` blocks — flag if that conflicts with any budget
   assumption elsewhere in the plan.
