# hcl_modules spec matrix: what the module arm needs to build every image

Verified on 2026-09-22 against `registry.terraform.io` (live) and
`raw.githubusercontent.com`/`codeload.github.com` tag/commit tarballs.
Target pins: `hashicorp/aws` **6.66.0**, `terraform` **1.15.8**, no `direct`
fallback (`docs/design/tf-modules-arm.md`, `tf-module-registry-loopback.md`,
DECISIONS.md Amendment 46). 20 real specs in `specs/*.yaml` (`split.yaml` is
the train/holdout file, not a scenario; no toy spec lives under `specs/`).

## 1. Per-spec resources -> candidate module

Resource types from `tasks/*/<id>-hcl-raw/solution/**/solve.sh`. Module column
from `registry.terraform.io/v1/modules/terraform-aws-modules/<name>/aws`.

| spec | hcl_raw resource types | module(s)/submodule(s) | fit |
|---|---|---|---|
| acm-dns-validation-record-wiring | route53_zone, acm_certificate(_validation), route53_record | `acm` (root creates cert+validation+record together) | full |
| apigw-openapi | api_gateway_rest_api/deployment/integration/method/resource/stage, lambda_function/permission, iam_role | `lambda` (+`iam//modules/iam-role`); **no module for REST v1 API** | partial |
| apigw-redeploy | same REST-v1 set as apigw-openapi | same as above | partial |
| apigwv2-route-settings-zero-vs-unset | apigatewayv2_api/integration/route/stage, lambda, iam_role | `apigateway-v2` (not in current 16-set) + `lambda` | full, needs vendoring |
| asg-launch-template-tag-propagation | autoscaling_group, launch_template, vpc, subnet | `autoscaling` (not in current 16-set) + `vpc` | full, needs vendoring |
| caller-identity-arn-as-principal | s3_bucket, s3_bucket_policy | `s3-bucket` (root `attach_policy`/`policy`) | full |
| ddb-gsi-attribute-definitions | dynamodb_table (+ `global_secondary_index` block; the alt reference solution uses standalone `aws_dynamodb_global_secondary_index`) | `dynamodb-table` (root, inline GSI, `any`-typed passthrough) | full |
| ecr-repo-destroy-force-delete | ecr_repository, ecr_lifecycle_policy | `ecr` (root) | full |
| ecs-swappiness | ecs_task_definition | `ecs//modules/service` with `create_service=false` (+`container-definition` for `linuxParameters`) | full |
| iam-managed-policy-exclusive-vs-attachment | iam_role, iam_policy_attachment, iam_role_policy_attachment, iam_role_policy_attachments_exclusive | `iam//modules/iam-role` (`policies` map -> plain attachment only) | partial: no module makes `..._exclusive` or the deprecated global `aws_iam_policy_attachment` |
| lambda-alias-tracks-unpublished-latest | lambda_function, lambda_alias, iam_role, s3_bucket, s3_object | `lambda` + `lambda//modules/alias` (+`s3-bucket//modules/object`) | full |
| lambda-log-group-ownership-and-retention | cloudwatch_log_group, lambda_function, iam_role | `lambda` root (`use_existing_cloudwatch_log_group`, `cloudwatch_logs_*`) | full |
| named-resource-replacement | security_group, subnet, vpc, vpc_endpoint | `vpc` root + `vpc//modules/vpc-endpoints` (or standalone `security-group`) | full |
| s3-acl-vs-object-ownership-log-delivery | s3_bucket_acl/logging/ownership_controls/policy, s3_bucket | `s3-bucket` root (all four sub-resource types are root inputs) | full |
| s3-bucket-hardening-decomposition | kms_key, s3_bucket_policy/public_access_block/server_side_encryption_configuration/versioning, s3_bucket | `s3-bucket` root + `kms` | full |
| s3-lambda-log-retention | cloudwatch_log_group, iam_role, lambda_function/permission, s3_bucket_notification, s3_bucket | `lambda` + `s3-bucket//modules/notification` | full |
| s3-notification-authoritative-singleton | s3_bucket, lambda_function/permission, sns_topic(_policy), iam_role_policy, s3_bucket_notification | `s3-bucket//modules/notification` + `lambda` + `sns` | full |
| s3-notification-custom-resource-tax | s3_bucket, lambda_function/permission, iam_role, s3_bucket_notification | `s3-bucket//modules/notification` + `lambda` | full |
| sfn-jsonata | sfn_state_machine, iam_role | `step-functions` 5.1.1 (vendored) | full; arm ENABLED |
| singleton-child-resource-clobber | s3_bucket, s3_bucket_lifecycle_configuration | `s3-bucket` root (`lifecycle_rule`) | full |

No module exists on the registry for API Gateway REST v1 (`aws_api_gateway_rest_api`
et al.) at all — `terraform-aws-modules` only ships `apigateway-v2` (HTTP/WS).
apigw-openapi and apigw-redeploy therefore keep every API-Gateway resource raw
on this arm regardless of vendoring; only the Lambda side gets a module. These
are the two specs with **no module counterpart** for their trapped resources.

## 2. Catch -> module exposure (feeds `hcl_modules_override` / `applies_to`)

Format per spec: `catch: input (exposed, default) | HIDDEN by default=X | REMOVED (why)`.
Citations are `module@version:file:line` from the fetched `variables.tf`/`main.tf`.

**acm@6.3.1** (`main.tf:6,52-54,69`, `variables.tf:61-64,90-93,25-28`):
`no-validation-records-at-all`/`dns-validation-without-hosted-zone`/`email-validation-instead`:
`validation_method` (var:61, default `null`) and `zone_id` (var:90, default `""`)
are plain exposed inputs — unchanged from raw, catches representable.
`one-record-for-two-domains`: **REMOVED** — `local.distinct_domain_names` (main.tf:6)
always `distinct()`s the SAN list before the one-record-per-domain `count` (main.tf:52-54);
the module cannot emit a duplicate/ambiguous record for two SANs sharing a name.
`missing-certificate-validation-resource`: **HIDDEN** — `wait_for_validation`
(var:25-28) defaults `true`, so `aws_acm_certificate_validation` is created
unless the agent explicitly flips it to `false`.

**lambda@8.8.2** (`variables.tf:449-489,837-853`):
`retention-left-at-the-construct-default`: `cloudwatch_logs_retention_in_days`
(var:455, default `null`) — unchanged, never-expire by default same as raw, and
the module-default shape is denied at tier 0 with a resolved `0`.
`log-group-retained-on-delete`: `cloudwatch_logs_skip_destroy` (var:467, default
`false`) — exposed, safe default, still representable by flipping it.
`log-group-left-implicit`: **REMOVED**, correcting this file's earlier reading of
it as unchanged — the module creates `aws_cloudwatch_log_group.lambda`
unconditionally, so the omission shape cannot produce an implicit group at all.
The one input that reaches it, `use_existing_cloudwatch_log_group = true`
(var:449), needs a `logs:DescribeLogGroups` the host stub does not answer
(`gates/aws_stub.py`), so the fixture would be a failed toolchain step rather
than a catch; the catch is excluded on this arm until the stub grows that call.
`log-group-name-diverges-from-function`: **REMOVED VIA `logging_log_group`**
(var:849), and through a different input than this file first claimed — set, it
feeds BOTH the created group's `name` and the function's `logging_config.log_group`
(main.tf:142, 279), and that explicitly wired shape is a CORRECT solution shipping
as a second reference rather than a fixture. NOT removed from the module as a
whole: `lambda_at_edge = true` names the group `/aws/lambda/us-east-1.<fn>` at
main.tf:279 while `logging_config.log_group` stays the raw, unset
`logging_log_group` at main.tf:142 — the divergence itself, through a published
input, measured at 0.0 on tier 1. It ships as a non-catch negative (flipping an
edge flag is not this ticket's plausible mistake) and is what makes the arm's
tier-1 rule falsifiable.

**lambda//modules/alias@8.8.2** (`variables.tf:1-63`): `alias-still-serves-the-previous-version`/
`alias-removed-instead-of-repointed`: `function_version` is a required
passthrough with no module-side smoothing — fully representable, unchanged tier.

**s3-bucket@5.16.1** (`variables.tf:174-178,184-197,438-441,513-587`):
`subresource-omitted`, `sse-left-at-s3-managed`, `kms-key-not-referenced`: `versioning`
(var:174, default `{}`) and `server_side_encryption_configuration` (var:184,
default `{}`, nested `kms_master_key_id` optional) — both empty-default,
byte-identical omission behaviour to raw, catches unchanged.
`bpa-partially-set`: `block_public_acls`/`block_public_policy`/`ignore_public_acls`/
`restrict_public_buckets` (var:565-587) all default **`true`** — opposite of
raw's implicit-absence trap; the broken fixture must now explicitly regress one
flag to `false` rather than omit the resource. Still representable, tier
unchanged (still a `planned_values` read), but the "natural" mistake shape moves.
`tls-policy-misses-object-arn`: **HIDDEN/REMOVED when the module's own flag is used** —
`attach_deny_insecure_transport_policy` (var:513, default `false`) and
`attach_require_latest_tls_policy` (var:519, default `false`) generate a
correct bucket+object-ARN policy internally; the missing-`/*` mistake has no
module input that reproduces it. Still reachable if the agent bypasses the
flags and sets `attach_policy=true` + a hand-written `policy` JSON (raw
passthrough), so `applies_to` should not drop the catch outright — note the
alternate-shape risk instead.

**s3-bucket//modules/notification@5.16.1** (`variables.tf:39-58`): the
`lambda_notifications`/`sns_notifications`/`sqs_notifications` object types
have **no `source_arn` override field** — `create_lambda_permission`/`create_sns_policy`
default `true` and the module computes `source_arn`/policy scope from the
bucket internally. **REMOVED THROUGH THIS SUBMODULE ONLY**: the permission- and
policy-scoping catches cannot be produced through its public interface, and the
submodule-authored permission is a correct solution kept as a second reference
on both s3 specs. It is NOT removed from the arm, which is what this file first
claimed: `lambda@8.8.2` exposes `allowed_triggers[*].source_arn` (var:429 →
main.tf:347,369), a published input that reaches the mistake with no raw
resource anywhere, so `lambda-permission-not-scoped-to-bucket`
(s3-lambda-log-retention, s3-notification-custom-resource-tax) stays on the arm
with its own fixture. One `allowed_triggers` entry plans TWO permissions (the
current-version and unqualified-alias triggers), which is why the tier-0 assert
on their principal is a `set_eq` rather than an `eq`.

**dynamodb-table@5.5.2** (`variables.tf:13-29,73-77`): `attributes` (list(map),
default `[]`) and `global_secondary_indexes` (type `any`, default `[]`) are an
unvalidated structural passthrough — every ddb-gsi catch
(`attribute-definitions-include-non-key-attributes`, `gsi-key-attribute-not-declared`,
`attribute-definitions-include-an-unrequested-key`, `gsi-projection-type-is-keys-only-not-include`,
`gsi-missing-entirely`, `include-projection-without-non-key-attributes`)
is exactly as representable as on raw — no defaults change, no tier move.

**ecs//modules/container-definition@7.6.1** (`modules/container-definition/variables.tf:186-206`):
`swappiness-nested-attribute`/`swappiness-requires-maxswap`: `linuxParameters.swappiness`/
`.maxSwap` are typed `optional(number)` fields inside an object with `default={}`
— but the submodule still `jsonencode()`s the whole thing into the same
`container_definitions` string the raw resource stores, so the tier-0
`|fromjson` jsonpath reads identically either way. Unchanged.

**apigateway-v2@6.1.1** (`variables.tf:334-344`): `burst-limit-left-unset`/
`throttle-set-to-zero`: **HIDDEN** — `stage_default_route_settings` is an
object type whose fields carry their own second-argument defaults
(`throttling_burst_limit = optional(number, 500)`,
`throttling_rate_limit = optional(number, 1000)`, lines 340-341) while the
*variable itself* defaults to `{}`. Terraform's `optional()` type conversion
fills the missing keys, so simply not touching the variable yields **explicit**
500/1000 in the plan — the opposite of raw's "omitted block = unlimited"
trap. The bad state is only reachable by explicitly writing
`throttling_burst_limit = null` inside the object, which is a deliberate
regression, not an omission; `hcl_modules_override` should move this catch or
`applies_to` should exclude it, pending an owner call on whether the module's
built-in 500/1000 counts as "the correct behaviour" for this scenario.

**vpc//modules/vpc-endpoints@6.7.3** (`variables.tf:59-87`): `rename-replaces-an-in-use-security-group`/
`ingress-widened-to-the-internet`: `security_group_name` (default `null`,
free string, no forced `_prefix`) and `security_group_rules`/`cidr_ipv4`
(standalone `security-group@6.0.0` `variables.tf:66-72`) are plain exposed
inputs — AWS's own SG-name-immutability forces the same replacement either
way. Unchanged.

**iam//modules/iam-role@6.8.2** (submodule resource list, §1 registry query):
creates only `aws_iam_role`/`aws_iam_role_policy`/`aws_iam_role_policy_attachment`/
`aws_iam_instance_profile`. **No submodule anywhere in `iam@6.8.2` creates
`aws_iam_role_policy_attachments_exclusive` or the deprecated global
`aws_iam_policy_attachment`** — `account-exclusive-policy-attachment`,
`deprecated-exclusive-role-attribute`, `role-scoped-exclusive-attachment` have
**no module path at all**; they stay raw regardless of arm, same as
apigw-openapi's REST resources. `policy-attached-to-one-role-only`/
`s3-readonly-missing-on-one-role`/`trust-principals-not-split-across-both-roles`
map onto `policies` (map(string), default `{}`) and `trust_policy_permissions`
— plain passthrough, unchanged.

**sfn-jsonata**: `step-functions@5.1.1` root takes `definition` as a single
string var with no schema over its contents — the JSONata-vs-JSONPath mistake
lives entirely inside that string on every arm; module changes nothing.
The measurement that had to precede enabling: `main.tf:25` assigns
`definition = var.definition` with no `jsonencode`/`templatefile` wrapper and no
value the module computes interpolated in, so the document stays plan-time-known
and the tier-0 `|fromjson` asserts resolve — had the module built the ASL around
the role ARN it creates, a correct solution would have scored 0.0. `create_role`
defaults true, so one call composes the state machine, the execution role and
the `states.<region>.amazonaws.com` trust policy and nothing stays raw. Both
catches measured unchanged in tier and mistake; no `hcl_modules_override`.

## 3. Provider requirements per module@version

All fetched from `versions.tf`/registry `provider_dependencies` (root has no
`versions.tf` -> "(submodules only)").

| module@version | root `required_providers` | relevant submodule | submodule providers |
|---|---|---|---|
| s3-bucket@5.16.1 | aws >= 6.42 | notification, object | aws >= 6.42 |
| lambda@8.8.2 | aws >= 6.28, external >= 1.0, local >= 1.0, null >= 2.0 | alias (used); docker-build (unused: adds `kreuzwerker/docker` >= 3.5.0) | aws >= 6.28 |
| acm@6.3.1 | aws >= 6.28 | — | — |
| route53@6.5.1 | aws >= 6.28 | delegation-sets (unused) | aws >= 6.28 |
| ecr@3.2.0 | aws >= 6.28 | repository-template (unused) | aws >= 6.28 |
| ecs@7.6.1 | aws >= 6.41 | service, container-definition (used); cluster (unused, adds time >= 0.13) | aws >= 6.41 |
| autoscaling@9.3.2 | aws >= 6.56 | — | — |
| vpc@6.7.3 | aws >= 6.28 | vpc-endpoints | aws >= 6.28 |
| security-group@6.0.0 | aws >= 6.29 | (60+ protocol wrappers, unused) | aws >= 6.29 |
| dynamodb-table@5.5.2 | aws >= 6.28 | — | — |
| kms@4.2.2 / 4.0.0 | aws >= 6.28 / aws >= 6.0 | — | — |
| sns@7.1.1 | aws >= 6.28 | — | — |
| apigateway-v2@6.1.1 | aws >= 6.28 | (calls `acm` module, see §4) | — |
| step-functions@5.1.1 | aws >= 6.28 | — | — |
| iam@6.8.2 | none (no root `versions.tf`) | iam-role (used); iam-oidc-provider (unused, adds tls >= 3.0) | aws >= 6.28 |
| eks@21.25.1 (decoy) | aws >= 6.59, tls >= 4.0, time >= 0.9 | self-managed-node-group / \_user\_data (unused, adds cloudinit >= 2.0, null >= 3.0) | — |
| alb / sqs (decoys) | aws >= 6.28 | — | — |
| rds@7.2.2 (decoy) | aws >= 6.28, **terraform >= 1.11.1** | — | — |

**Every constraint above is satisfied by `hashicorp/aws` 6.66.0 and terraform
1.15.8** — including `eks@21.25.1`'s `>= 6.59`, which the loopback memo (dated
2026-09-21, pinned mirror then at 6.58.0) recorded as the one failure; the
Amendment-48 bump to 6.66.0 resolves it. No module in the registry's current
latest-version listing (`registry.terraform.io/v1/modules/terraform-aws-modules`,
queried today) needs `aws > 6.66.0` or `terraform > 1.15.8`.

## 4. The union

### 4a. Vendored module manifest

Commit shas are the `X-Terraform-Get` value from each module's live `download`
response (`git::https://github.com/terraform-aws-modules/terraform-aws-<m>?ref=<sha>`).

| module | version | commit sha | role |
|---|---|---|---|
| vpc | 6.7.3 | b3abd6df2ecf052451a361ed55b8f06f8742a795 | used (named-resource-replacement) |
| ecr | 3.2.0 | b6ef04d088cf91d5ba9505132e9ff7c9f847ed5d | used |
| lambda | 8.8.2 | 9d32ec285f7c30c784516ff546ae282cce71e8a7 | used |
| acm | 6.3.1 | aae84c011dd68ace1beb5d10e1feddfe9a334953 | used |
| route53 | 6.5.1 | 883f987d6bb328c09bd4dfc5a04024534b371d59 | used |
| dynamodb-table | 5.5.2 | c38423ae6c92825e7cc4376c7f81deb20a676f2b | used |
| sns | 7.1.1 | 61ac1dc530fd08965a0ce480352e554cc827ff05 | used |
| kms | 4.2.2 | d25e459bd43d8d0bdff7c250ba6b237a12be7381 | used (agent's natural pick) |
| kms | **4.0.0** | 28846a0d9ba83629f006847f25f0e69bd05116b1 | pinned transitive dep of eks + route53 (route53 main.tf:115, DNSSEC key) |
| security-group | 6.0.0 | 58d8e895915f5573767081142d063b7caf7a2b47 | used or decoy-vs-vpc-endpoints |
| ecs | 7.6.1 | 60b428812ddcffe48abc6af0988fe826c89da961 | used |
| s3-bucket | 5.16.1 | 5dc2f1f89743ab935114b0b039bc88044a672ca2 | used |
| iam | 6.8.2 | 55514b7873c411040395e024a422684998da77c2 | used |
| alb | 10.5.1 | 6c6e48c10d450d01cf6715346e926df0b858efc2 | decoy (no spec needs an LB) |
| sqs | 5.2.2 | dd73a96c0155bc324dda5256f3e7a9ea2c710195 | decoy |
| rds | 7.2.2 | 175da043429cbbe41c512f976105719f6d0e538c | decoy |
| eks | 21.25.1 | 5bb7855c49194aabb2e36448ed990931f1c932ae | decoy |
| **step-functions** | 5.1.1 | 16c7a1ffaa72643d714a7b3924216edce9413482 | **new: needed for sfn-jsonata** |
| **apigateway-v2** | 6.1.1 | 95e6a1d56d6d761ec12c89b36b29aad03a421b2f | **new: needed for apigwv2-route-settings-zero-vs-unset** |
| **autoscaling** | 9.3.2 | f90a581bcca0bab571022a021db155f2860e9b32 | **new: needed for asg-launch-template-tag-propagation** |
| **acm** | **6.2.0** | 0fb9ca5d0b8ea28414fdf085bc3a2628d700758e | **new: transitive dep of apigateway-v2** (`main.tf:172-173`, unconditional module call, `create_certificate` only gates the *resources inside it*, not the call) |

`cloudwatch@5.7.3` was considered and **rejected**: every log-group-creating
spec already has a closer-fitting module (`lambda`'s `cloudwatch_logs_*` vars,
`ecs`'s per-submodule log group) — adding it would be a pure decoy with no
spec demand. `notify-slack`, `eventbridge`, `appsync`, `ec2-instance`,
`rds-aurora`: none of the 20 specs' resource types touch them; not added.

Union count: **19 distinct module names, 21 module@version entries** (kms and
acm each ship 2 versions) — versus the current 16-module/17-entry pinned set.

### 4b. Provider mirror (min version satisfying every constraint in the union)

| provider | min version needed | pulled in by |
|---|---|---|
| hashicorp/aws | 6.66.0 (pinned, satisfies every `>=` above) | every module |
| hashicorp/external | >= 1.0 | lambda root |
| hashicorp/local | >= 1.0 | lambda root |
| hashicorp/null | >= 2.0 (>= 3.0 if eks decoy's `_user_data` submodule is ever called) | lambda root, eks decoy |
| hashicorp/tls | >= 4.0 (eks root) / >= 3.0 (iam-oidc-provider, unused) | eks decoy |
| hashicorp/time | >= 0.13 (max of eks root's >= 0.9 and ecs cluster submodule's >= 0.13, ecs cluster unused by ecs-swappiness) | eks decoy |
| hashicorp/cloudinit | >= 2.0 | eks decoy, only if self-managed-node-group called |
| terraform (CLI) | 1.15.8 (rds root's `>= 1.11.1` is the tightest floor) | rds decoy |

### 4c. Size estimate

Baseline 16-module/17-entry set: **17 MB raw, 3.8 MB pruned** (verified,
`tf-module-registry-loopback.md` §5; prune list `examples/ tests/ wrappers/
docs/ .github/ *.md *.png`). New entries, same prune, measured today from
`codeload.github.com` tag-commit tarballs:

| module | tarball | pruned, extracted |
|---|---|---|
| step-functions@5.1.1 | 24K | 76K |
| apigateway-v2@6.1.1 | 36K | 80K |
| autoscaling@9.3.2 | 60K | 136K |
| acm@6.2.0 | — | 48K |

Union: **3.8 MB + ~0.34 MB ~= 4.1 MB** pruned, extracted.

## 5. Risks

* **No module for API Gateway REST v1** — apigw-openapi and apigw-redeploy's
  entire trapped surface (deployment/integration/method/stage graph) stays raw
  HCL on this arm; only the Lambda side gets a module, reducing the arm to
  "hcl_raw with a Lambda wrapper" for either — worth weighing before scenario
  selection (`tf-modules-arm.md` §3's pilot three are bucket-hardening/ACM/IAM,
  neither apigw spec, which sidesteps this).
* **No module makes the deprecated/exclusive IAM attachment resources** —
  `aws_iam_role_policy_attachments_exclusive` and `aws_iam_policy_attachment`
  have zero coverage across all 9 `iam@6.8.2` submodules (confirmed against
  every submodule's resource list, not assumed); three of
  iam-managed-policy-exclusive-vs-attachment's six catches (§2) need
  `applies_to` review for this arm regardless of module choice.
* **No module needs `aws` above the mirror or `terraform` above 1.15.8 today**
  (§3) — the 6.66.0 bump already clears the one known failure (`eks@21.25.1`,
  `>= 6.59`) the loopback memo flagged at 6.58.0. Moving target: recheck on
  every refresh, `terraform-aws-modules` floats its aws floor forward often
  (autoscaling `>= 6.56`, s3-bucket `>= 6.42`, both mid-2026 releases).
* **`dynamic`/`for_each` over sets on trapped resources**: `s3-bucket`'s
  `versioning`/`server_side_encryption_configuration`/notification maps and
  `dynamodb-table`'s `global_secondary_indexes` (`any`) all `for_each`-over-
  **map** (keyed), not `toset()`, so the normaliser's "indexed module output"
  blind spot (`tf-modules-arm.md` §1) does not apply — no `[0]`/`[1]` numeric
  instance key for these inputs, only stable map keys. `security-group`'s 52
  protocol submodules and `ecs`'s per-container map are the same shape. No
  `toset()` for_each found in any fetched `variables.tf`/`main.tf`.
* **`data "aws_caller_identity"`/`aws_partition`/`aws_region` inside modules**:
  confirmed present (loopback memo §8: `iam-role`'s assume-role logic calls
  STS at plan time) — every module here building an `assume_role_policy`
  (`iam-role`, `lambda`, `ecs//service`, `ecs//cluster`, `step-functions`,
  `autoscaling`'s instance profile) needs the same STS stub `gates/aws_stub.py`
  already answers for hcl_raw/terraconstructs.
* **Feature-flagged provider/module declarations**: `apigateway-v2@6.1.1`
  unconditionally declares `module "acm" { source = "terraform-aws-modules/acm/aws",
  version = "6.2.0" }` (`main.tf:172-173`) — the module *call* has no
  `count`/`for_each`; only the certificate *resources inside acm* are gated by
  `create_certificate`/`create_domain_name` locals (`main.tf:167,177`). `init`
  needs `acm@6.2.0` vendored the moment `apigateway-v2` is, regardless of
  whether apigwv2-route-settings-zero-vs-unset ever sets a `domain_name` (it
  does not, §1) — invisible unless `main.tf` is read past `variables.tf`. No
  other such case found in the 3 newly-vendored modules' trees.
