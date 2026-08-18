# Scenario candidates — three-sweep sourcing synthesis (2026-08-18)

Curated from three parallel mining workflows (20 agents, ~2.6M subagent
tokens, one run resumed across an API outage): **provider-pitfall-mining**
(wf_559d97b6-c46 — 11 agents over terraform-provider-aws issues by service
shard + HashiCorp Discuss + blogs; 137 candidates), **hcl-strength-mining**
(wf_e062a830-f57 — 4 agents over tutorials/case-studies/comparatives/sentiment;
43 candidates + 39 confounds), **awscdk-pain-mining** (wf_aebed056-f93 —
4 agents over aws/aws-cdk + cloudformation-coverage-roadmap with mandatory
root-cause tagging, + 1 recon cell; 45 candidates). 225 raw candidates,
deduplicated below into ~60 distinct patterns; evidence includes reaction/
comment counts and closed-not-planned ("permanent sharp edge") markers.
Full structured payloads live in the three workflow journals; this doc is the
ranked, curated index.

## The decomposition frame (what sweep 3 adds to the pre-reg)

"CDK pain" conflates two layers, and the three-arm design can separate them:

- **cdk-l2-library** pain (L2 lag, escape hatches, surprising defaults) taxes
  the *typed-authoring* layer → hits awscdk (and terraconstructs where it
  mirrors the design).
- **cfn-engine** pain (SecureString impossibility, rollback locks, stuck
  stacks, coverage lag where *no L1 exists*, logical-ID rigidity, drift
  blindness) taxes the *deployment engine* → hits **awscdk only**;
  terraconstructs keeps the typed authoring and never touches CloudFormation.

**terraconstructs is therefore the control arm that isolates the authoring-
substrate effect from the engine cost.** Sweep 2 independently confirmed the
split matters: 20 of its 43 HCL-favorable candidates are cfn-limitation, not
HCL-authoring wins. Portfolio predictions now come in four colors:
L2-favorable · hcl-favorable · terraconstructs-favorable (cfn-engine) ·
parity controls (anti-L2) — plus deliberate thesis-can-lose entries.

## Portfolio balance (falsifiability check)

| predicted winner | count (curated) | sourced from |
|---|---|---|
| typed L2 arms (typed-value/nested/graph) | ~28 | sweep 1 |
| hcl-raw | ~10 | sweep 2 (import/moved/data-sources/lifecycle) |
| terraconstructs (cfn-engine pain) | ~12 | sweeps 2+3 |
| parity controls (anti-L2) | ~8 | all three |
| thesis-can-lose for L2 (defaults/L3 no-ops/escape hatches) | ~7 | sweep 3 |
| terraconstructs-unfavorable control | 1 | recon (durable engine-semantic drift) |

The portfolio contains scenarios every arm can lose. Selection for actual spec
work should preserve that property.

---

## Tier A — ready now, static (existing oracle machinery or trivial additions)

Ranked by signal × distinctness × cheapness. All synth/plan-graded, no live
apply, no new harness capability.

| # | candidate | family | cx | signal anchor | one-line |
|---|---|---|---|---|---|
| A1 | `s3-bucket-hardening-decomposition` | nested-attribute | S | 300 reactions / 93 comments (v4 refactor) ×3 sweeps | "versioned, KMS, TLS-only, BPA bucket" = 6+ HCL resources each silently omittable; `s3.Bucket{enforceSSL}` derives the SecureTransport policy — unforgettable by construction |
| A2 | `default-tags-vs-tags-all` | nested-attribute | S | **507 reactions** (highest single issue found) | org-tagging via provider default_tags → tags_all perpetual-diff traps vs `Tags.of(app).add()` |
| A3 | `sg-inline-vs-standalone-rules` | graph-dependency | S | ×3 sweeps independently | inline ingress/egress + rule resources silently clobber each other; CDK has one authoring surface |
| A4 | `s3-lifecycle-rule-filter-shape` | nested-attribute | S | 161 reactions / 36 comments | every intuitive whole-bucket filter spelling fails differently (some only at apply); L2 has no filter concept to get wrong |
| A5 | `sqs-fifo-name-suffix-redrive` | typed-value-trap | S | tier-0 synth throw | `.fifo` suffix + redrive JSON blob vs typed `Queue{fifo:true, deadLetterQueue}` — cheapest scenario in the set |
| A6 | `ddb-gsi-projection-attribute-defs` | typed-value-trap | S | 57-comment #1 dynamodb thread + discuss | INCLUDE-without-non_key_attributes, attribute_definitions drift vs typed GSI props |
| A7 | `apigw-integration-timeout-duration` | typed-value-trap | S | unit-in-name trap | `timeout_milliseconds = 30` (meant seconds) vs `Duration.seconds(30)` — the unit lives in the type |
| A8 | `apigwv2-payload-format-default` | typed-value-trap | S | divergent defaults | provider defaults 1.0, CDK defaults 2.0; handler written for v2 events silently gets v1 shape (2-arm: no tcons v2 constructs) |
| A9 | `sg-mutual-reference-cycle` | graph-dependency | S | classic cycle error | ALB↔app SG cross-reference: HCL plan fails on cycle, `connections.allowTo` renders standalone rules automatically |
| A10 | `eventbridge-lambda-target-permission` | graph-dependency | S | invoke-permission family | rule matches, invoke silently fails without `aws_lambda_permission`; CDK target derives it |
| A11 | `lambda-function-url-auth-none` | graph-dependency | S | 60 reactions | function URL with authorization NONE still needs the resource policy; `addFunctionUrl` derives it |
| A12 | `method-caching-cache-cluster` | graph-dependency | S | verified stage.ts:490 | `caching_enabled` without stage cache cluster = silent no-op; CDK auto-enables the cluster |
| A13 | `cloudfront-cache-policy-migration` | typed-value-trap | S | 57 reactions, migration era | legacy `forwarded_values` vs managed cache policies; CDK steers to `CachePolicy.CACHING_OPTIMIZED` |
| A14 | `iam-principal-in-identity-policy` | nested-attribute | S | tier-0 for both L2 arms | `principals` block in an identity policy: L2 `validateForIdentityPolicy()` throws at synth; HCL applies then fails |

**Thesis-can-lose, static, ready now** (sweep 3, run these early for honesty):
- `ecs-patterns-typed-props-silent-noop` — L3 `ScheduledFargateTask` accepts
  typed `cpu`/`memoryLimitMiB` that it *ignores* (closed by adding a warning,
  not honoring the props). The typed arm's failure mode at its worst.
- `escape-hatch-array-index-object` — `addPropertyOverride('X.0.Y')` creates
  an object keyed `"0"`, docs wrong for 5+ years; CDK-arm-only trap.
- `grants-silent-noop-on-imported` — `bucket.grantRead(role)` on imported
  constructs emits zero statements, green everywhere.
- `s3-access-logs-acl-flag-dependent` — L2 emits deprecated ACL shape unless a
  cdk.json feature flag is set; behavior forks on config outside the code.

**Parity controls (anti-L2), static, ready now:** `eventbridge-event-pattern`
(content filters, ×3 sweeps), `lambda-reserved-concurrency-zero-sentinel`,
`s3-access-point-delegation`, `cw-metric-math-expression`,
`athena-workgroup-enforcement`, `glue-partition-projection`,
`kms-key-policy-service-condition`.

## Tier B — ready now, live (reuses the apigw-redeploy harness + reset)

| # | candidate | pred. winner | cx | signal | note |
|---|---|---|---|---|---|
| B1 | `ssm-securestring-app-config` | **terraconstructs/hcl** | S | 204 reactions, ~7y open, ×3 sweeps | CFN cannot create SecureString; `CfnParameter{type:'SecureString'}` synths clean and detonates at deploy — measures *where in the pipeline* each arm's failure lands. Fastest live scenario available. Use AWS-managed key (avoids KMS deletion-window issue). Upgrade path for toy-ssm-parameter. |
| B2 | `apigw-restapi-policy-not-in-deployment` | L2 | M | 105 reactions | resource policy change doesn't redeploy in HCL; CDK's deployment hash covers it — directly reuses apigw-redeploy's two-phase machinery |
| B3 | `dynamodb-gsi-swap-one-update` | hcl/tcons | M | **247 reactions** | end state needs 2 GSI changes: CFN refuses >1 per update (two deploys); provider serializes internally (one apply). Long GSI-backfill waits — budget them. |
| B4 | `sns-subscription-pending-confirmation` | parity | M | top-5 sns | email/https subscription drift — anti-L2 live control |
| B5 | `stage-vs-deployment-ownership` | L2 | M | 136 reactions | defer if apigw saturation is a concern (3rd apigw scenario) |

## Tier C — needs a toolkit feature (grouped BY feature = the toolkit roadmap)

Build the feature once, unlock the cluster. Ordered by unlock value.

1. **Differential two-pass static oracle** (synth → mutate source → re-synth →
   diff artifacts; generalizes apigw-redeploy's salted-hash proof into a
   reusable tier): unlocks `lambda-code-hash-drift` (×4 sweeps, 38 reactions,
   7y open), `lambda-alias-tracks-unpublished-latest`,
   `user-data-change-silent-noop` (35 reactions, 8y),
   `count-vs-foreach-identity-churn` (64 reactions, anti-L2 control).
2. **Policy-JSON semantic oracle** (extract policy from plan-json/CFN incl.
   interpolations; order/Sid-insensitive set compare): full-parity grading for
   `iam-principal-in-identity-policy`, `trust-policy-service-principal`,
   `policy-document-merge-sid-semantics`, `caller-identity-arn-as-principal`,
   `nonexistent-iam-action` (+ vendored service-authorization action catalog).
3. **Post-apply idempotence oracle** (`terraform plan -detailed-exitcode == 0`
   / empty `cdk diff` as a graded tier): `policy-json-normalization-diff`
   (252 + 333 reactions — two of the highest-signal threads found),
   `iam-exclusive-vs-additive-attachment` (×3 sweeps),
   `ecs-taskdef-json-perpetual-revision`.
4. **Plan-graph/depends_on reader** (Rego over `configuration.root_module`
   edges): `iam-eventual-consistency-depends-on` (×4 sweeps),
   `s3-acl-vs-object-ownership`, `s3-bpa-vs-bucket-policy-ordering` (84 r.).
5. **Apply→modify→re-apply generalization** (exists for apigw; make it a
   spec-level capability): `role-rename-path-cascade`,
   `sg-in-use-replacement-wedge` (43 comments),
   `custom-named-resource-replacement` (AWS KB article exists for the failure),
   `refactor-without-replacement` (moved-block vs logical-ID rigidity — ×4,
   open on the CFN roadmap since 2020), `cross-stack-export-deadly-embrace`,
   `cloudfront-publickey-rotation`.
6. **Out-of-band fixture + adoption oracle** (deploy.sh pre-creates resources;
   oracle asserts *physical identity preserved*): `import-adopt-stateful`
   (×5 sources; cdk import needs hand-authored resource-mapping JSON in a
   TTY-less harness — that asymmetry is the measurement),
   `s3-notification-on-unowned-bucket` (**479 reactions — #1 open CFN roadmap
   issue**), `tag-existing-subnet`, `default-sg-lockdown-adoption`,
   `drift-reconcile-out-of-band`.
7. **Induced-failure injection** (deterministic mid-apply failure):
   `cfn-rollback-vs-partial-apply` (fix-forward vs rollback-lock; the
   engine-difference headline), `clean-teardown-delete-failed`.
8. **Account-level-setting policy** (one-per-region resources surviving
   reset): `account-baseline-hardening` (no CFN types at all),
   `apigw-account-cloudwatch-role` (×2 sweeps).
9. **cfn-lint in the awscdk image** — without it, schema-invalid templates
   (SecureString!) sail through tiers 0–1 and tier-attribution is unfairly
   generous to the CDK arm. Small, unlocks honesty for B1.
10. **Pre-provisioned fixtures** (VPC, boundary policy, ACM/domain):
    `lambda-vpc-eni-role`, `permissions-boundary-every-role`,
    `base-path-mapping` custom-domain variants.
11. **Slow-resource budget**: CloudFront live variants, `rds-blue-green`,
    ECS L-complexity entries. Park until the budget exists.

**Durable terraconstructs-unfavorable control** (from recon; needs no new
toolkit): `ssm-dynamic-ref-plan-drift` — TerraConstructs/base#38: CFN resolves
`{{resolve:ssm:...}}` server-side per deploy; TF caches the data-source read
and diffs forever. An engine-semantic pain that *survives any* CDK→TF
synthesizer — the honest mirror image of B1.

## Confounds (real advantages the bench cannot plant — bound the claims)

From sweep 2 (39 recorded; the ones that most constrain interpretation):
state surgery / `terraform state mv` culture; targeted `-target` applies;
plan-output review culture as a human workflow (we grade outcomes, not
reviewability); module ecosystem (excluded by design — no terraform-aws-modules
arm); multi-cloud consistency; provider release cadence as an *ecosystem*
property (we can plant specific lag instances, not the cadence itself);
CFN-events debuggability complaints (live_check measures outcome, not debug
experience — turn-count partially proxies it).

## CDK→TF synth recon (status: verified where load-bearing)

Ran during a classifier outage; its two load-bearing claims were independently
re-verified 2026-08-18: aws-cdk-rfcs **#217 closed `not_planned` 2023-10-27**
("strategy decision, out of scope"); **hashicorp/terraform-cdk archived
2025-12-10** (CDKTF deprecated; community forked as CDK Terrain → cdktn).
**No public AWS CDK→TF synthesizer exists.** Framing for tcons gaps:
- pure L2-surface gaps (no EIP L2 — TerraConstructs/base#130; Route53 grant
  surface) = transitional, ordinary community velocity; any hypothetical
  AWS-built TF-target L2 would *reset them to zero, not eliminate them*;
- **engine-semantic gaps (base#38 SSM drift) are durable under every
  synthesizer** — they belong in the benchmark as permanent controls.
Re-check after re:Invent 2026.

## Recommended next five (when scenario-authoring resumes)

Standing directive remains *iterate with live runs before adding scenarios*.
When authoring resumes, this order maximizes information per scenario:
1. **B1 `ssm-securestring-app-config`** — three-arm live, terraconstructs-
   favorable, upgrade of an existing toy, fastest live loop; forces the
   cfn-lint decision (C9).
2. **A1 `s3-bucket-hardening-decomposition`** — highest-signal static
   L2-favorable; near-zero toolkit cost.
3. **`ecs-patterns-typed-props-silent-noop`** — thesis-can-lose entry, static,
   keeps the portfolio honest early.
4. **A2 `default-tags-vs-tags-all`** — 507-reaction signal, static, cheap.
5. **C3's `policy-json-normalization-diff`** — build the idempotence oracle
   (small), unlock the two biggest-signal threads in the entire mine
   (252 + 333 reactions) as one scenario.

Cross-check against the 60/40 train/holdout split and prompt-parity gates at
spec time; every candidate above still requires the falsifiability +
grading-proof discipline before it becomes a scenario.
