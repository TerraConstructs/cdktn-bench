# Batch A — greenfield scenario blueprints (12)

**Status: DESIGN ONLY. Nothing here is generated, specced or committed as a
scenario.** This document is the authoring input for the twelve scenarios the
2026-08-20 grading pass placed in its *"Ready with today's harness"* bucket
(`docs/scenario-grades/2026-08-20-summary.md`). Each blueprint is a
pre-spec: the identity, the prompt, the oracle tier plan, the trap mechanics
with re-verified evidence, the pre-registered arm prediction, and the effort /
risk notes. A blueprint becomes a scenario only by being written as
`specs/<id>.yaml` under `docs/adding-scenarios.md`'s procedure and passing
`make falsifiability` / `make grading-proof`.

Written 2026-08-20 while a live trial was running against `886312446417`;
**no generation, no AWS calls, no `tasks/` writes** were made producing it.

Inputs read in full: `docs/scenario-grades/2026-08-20-summary.md`,
`docs/scenario-grades/2026-08-20-graded.json` (the operator comments are
treated as binding), `docs/scenario-candidates.md`, `specs/SCHEMA.md`,
`specs/s3-lambda-log-retention.yaml` and `specs/apigw-openapi.yaml` (as
templates), `docs/adding-scenarios.md`, `DECISIONS.md` Amendments 23-28.
Source-verified at authoring time: `aws-cdk-lib` **2.263.0** (the pinned
version, local clone at `a9e6639`), `terraconstructs` **0.2.13** (the pinned
package), `hashicorp/aws` provider docs on `main` (latest release **6.61.0**;
the arms pin **6.58.0** hcl-raw / **6.52.0** terraconstructs).

---

## 0. Batch-level

### 0.1 Conventions applied to all twelve

**(1) Identity separation, and the greenfield trap in it.** `SCHEMA.md` §0.1.1:
the spec `id` is operator-facing and *may* name the pitfall; every name the
agent can see must name only this step's open goal. For a **single-step
greenfield** spec `workspace_title` is *forbidden* — which means **`title` IS
the agent-visible header**, byte-for-byte, stamped into `lib/scenario-stack.ts`,
`main.tf`, `bin/app.ts`'s CFN description and `main.ts`. Every blueprint below
therefore ships three names:

- `id` — operator-facing, names the pitfall (used in `specs/`, `tasks/`,
  `oracles/`, results tables);
- `title` — **agent-visible**; written in ticket voice, naming only the goal;
- `workspace_id` — declared explicitly wherever the `id` would leak through
  `environment/` (terraconstructs construct id, `gridUUID`, `preflight.sh`'s
  `cdktf.out/stacks/<id>/`, and the arm's own `npx cdktn synth` output).

Each blueprint states the result of running its proposed `workspace_id` and
`title` against `generator/spec_model.py`'s `AGENT_MECHANISM_DENY_PATTERNS` +
`AGENT_FORESHADOW_DENY_PATTERNS` (the union `AGENT_IDENTITY_DENY_PATTERNS`).
Note that `Spec._agent_visible_identity_is_deny_list_clean` validates
`workspace_id` and `workspace_title` — **not** a greenfield `title` — so the
title's cleanliness rests on review plus
`generator/tests/test_scenario_identity.py`'s emitted-bytes sweep. That gap is
**operator question Q1** below.

Words that recur in this problem space and are **banned** in any agent-visible
name or prompt: `lifecycle`, `perpetual`, `flip-flop`, `replacement/replaced/
replacing`, `re-create`, `in-use`, `explicitly named`, `already exists`,
`drift`, `idempotent/idempotence`, `stale`, `create-before-destroy`, plus the
meta class (`pitfall`, `gotcha`, `trap`, `latent`, `poisoned`, `brownfield`,
`find the bug`, `fix the mistake`, `review this config`). The foreshadowing
class (`re-deploy`, `re-apply`, `day 2`, `next step`, `change request`,
`iteration`, `subsequent`, `follow-up`) is *allowed* in a stepless task's own
`instruction.md` (SCHEMA.md §0.1's scope table) but **not** in `workspace_id` /
`workspace_title` / anything under `environment/`.

**(2) Prompt voice (operator directive, 2026-08-20).** Write the `shared_body`
as a real ticket would state the goal. Forbidden: mechanism constraints that
exist only to force the oracle's expected implementation shape; any mention of
grading; any coaching about toolchain differences ("if your toolchain needs a
code archive…") — *discovering* that Terraform wants an archive while CDK
bundles for free is the measured differential, and telling the agent kills the
signal. `seeded_files` are listed as "path — what it is", one line, no usage
instructions. Where a genuinely different implementation shape exists that
would also satisfy the ticket, each blueprint carries a separate,
operator-facing **"Oracle must tolerate / defend"** subsection naming that
shape and stating the resolution — **behavioralize the assert** (default), or
*sparingly* one in-world motivating sentence in the ticket. Never a defensive
enumeration of what not to do.

**(3) Oracle default is static.** Batch A is the "ready with today's harness"
bucket: prefer static-only wherever the trap is provable offline against the
synthesized template / `terraform show -json` plan. Two blueprints need live
(§5 apigwv2 zero-vs-unset, §12 ECR teardown) and each says why. Tier-0 asserts
must respect `SCHEMA.md` §4.2.1 (never target an attribute that can be
plan-time-unknown); graph-edge facts go to
`.configuration.root_module.resources[].expressions.<attr>.references`.

**(4) Predicted tiers are evidence-checked, never assumed** — the standing
`s3-lambda-log-retention` lesson. Every cross-arm claim below cites the file
and line it was read from, in `aws-cdk-lib` 2.263.0 or `terraconstructs`
0.2.13. Provider-behaviour claims must be re-verified against **both** arm pins
(6.58.0 and 6.52.0) at spec time; the mirrors are two versions apart and the
latest release is already 6.61.0.

### 0.2 Recommended authoring order

Value-first, subject to dependencies. Items 1-5 need nothing that does not
exist today; 6 waits on one shared harness fix; 11-12 are gated.

Cross-references everywhere else in this document use **§N** = the blueprint
section number below (which follows the operator's own list order), never the
authoring rank in this table.

| rank | blueprint | Why here |
|---|---|---|
| 1 | §1 `s3-bucket-hardening-decomposition` | Cheapest on existing rails, highest raw signal (300 reactions), zero new machinery. Loud (tier-0) catch by design — a **token-cost differential probe**, and the spec must label it as such so it is never pooled into silent-catch statistics (operator's own note on the `s3-bucket-inline-subresources` sibling). |
| 2 | §6 `ddb-gsi-attribute-definitions` | Pure `set_eq` asserts, no new helper, both typed arms verified immune. Fastest second scenario. |
| 3 | §2 `iam-managed-policy-exclusive-vs-attachment` | Exercises `catches[].applies_to` (the mistake is structurally unreachable on the CDK arm) — worth doing early because that discipline recurs. |
| 4 | §9 `s3-notification-authoritative-singleton` | Builds the reusable **"cardinality of an authoritative child resource per parent"** Rego helper that §10, §8 and the brownfield clobber sibling all reuse. |
| 5 | §10 `s3-notification-custom-resource-tax` | Reuses §9's helper plus the "count of resources of type X" primitive. Deliberate thesis-can-lose entry — keeps the portfolio honest early (prereg falsifiability). |
| 6 | §4 `caller-identity-arn-as-principal` | Operator: *"very high value"*. Blocked only by the shared hcl-raw offline-STS fix (§0.4 D1); do that fix, then this. |
| 7 | §8 `acm-dns-validation-record-wiring` | Needs §9's group-by-parent cardinality helper. Best three-arm story in the batch (three genuinely different artifact shapes for one intent). |
| 8 | §11 `lambda-log-group-ownership-and-retention` | Cheap, but its graded evidence set was **falsified** (§0.5) — author only after the replacement issues below are folded into the spec's provenance. |
| 9 | §3 `asg-launch-template-tag-propagation` | Largest plan in the batch, and needs the literal-AMI decision (§0.4 D2) so all three arms stay offline-synthable. |
| 10 | §7 `lambda-function-url-partner-scoped-invoke` | **Re-scoped** (see §7): the graded trap does not exist on provider 6.x. Author only in its new shape. |
| 11 | §5 `apigwv2-route-settings-zero-vs-unset` | Operator: *"high value"*, but live, and its tier-0 shape cannot be frozen before an empirical plan-shape probe (§5 (c)). |
| 12 | §12 `ecr-repo-destroy-force-delete` | Last: the batch's only harness-feature dependency (`verifier.teardown`, specced in §12). |

### 0.3 Provider-mirror delta

**The mirrors are per-provider, not per-resource.** `terraform providers mirror`
populates the whole plugin from `arms/hcl-raw/environment/mirror-src/main.tf`
(`hashicorp/aws 6.58.0`) and `arms/terraconstructs/environment/mirror-src/
main.tf` (`hashicorp/aws 6.52.0` + `hashicorp/archive 2.8.0`), so **every AWS
resource type any of the twelve blueprints needs is already mirrored**. The
delta is therefore not a resource list; it is these three items:

1. **One real candidate: `hashicorp/archive` on the hcl-raw arm.** Five
   blueprints are Lambda-bearing (§5, §7, §9, §10, §11) and every Terraform-shaped
   Lambda needs a deployment package. There are two ways to supply it, and they
   are not equivalent for the measurement:
   - **(a) Seed a placeholder package** as a `seeded_files` entry, the way
     `apigw-openapi` does. Cheapest, no mirror change — but it **hands both
     TF-shaped arms the answer to the bundling problem** and thereby erases a
     genuine differential (CDK's `Code.fromInline`/`fromAsset` bundles for free;
     Terraform does not).
   - **(b) Seed nothing** and let each arm solve packaging itself. This is the
     honest measurement, and it is what the operator's prompt rules imply
     ("discovering that terraform needs an archive while CDK bundles for free IS
     the measured differential"). It requires **`hashicorp/archive 2.8.0` in
     `arms/hcl-raw/environment/mirror-src/main.tf`** so that a solution using
     `data "archive_file"` can `terraform init` offline. The terraconstructs arm
     already mirrors exactly that version and for exactly this reason
     (`compute.Code.fromInline` constructs a `@cdktn/provider-archive`
     `DataArchiveFile`), so this makes the two TF-shaped arms symmetric rather
     than adding an asymmetry.
   **Recommendation: (b) — the batch's one provider-mirror delta is
   `hashicorp/archive 2.8.0` added to the hcl-raw mirror**, matching the
   terraconstructs pin. Keep (a) as the fallback for any single scenario where
   the packaging work would dominate the trap being measured, and record that
   choice in that spec's own comments. Note the second-order effect either way:
   the arm that must author packaging spends output tokens on it, and
   tokens-to-green is the headline metric — so this choice must be made
   **once, batch-wide**, not per scenario, or the arms' token counts stop being
   comparable across the batch.

2. **Version-skew re-verification, per scenario.** Six blueprints rest on
   provider *behaviour* (not just schema): §2 (`aws_iam_policy_attachment`
   exclusivity, `managed_policy_arns` deprecation), §3 (`propagate_at_launch`),
   §4 (`aws_caller_identity` / `aws_iam_session_context`), §7 (function-URL
   auto-permission), §9/§10 (`aws_s3_bucket_notification` atomicity), §12
   (`force_delete`). Each must be checked against 6.58.0 **and** 6.52.0 before
   its `predicted_tier_caught` freezes.
3. **A mirror bump is a separate, logged decision.** If any blueprint turns out
   to need 6.61.0 behaviour, bumping either mirror moves both arms' plan bytes
   and is an amendment, not a scenario detail.

### 0.4 Harness deltas this batch needs (none of them new *capabilities*)

- **D1 — hcl-raw offline STS endpoint (blocks §4, cheap).** The terraconstructs
  arm already ships `mock-sts.js` because `AwsStack.account` lazily creates a
  real `data "aws_caller_identity"`; the hcl-raw arm has **no** STS mock and
  runs with `skip_requesting_account_id = true`, so an hcl-raw solution that
  declares `data "aws_caller_identity" "current"` — the idiomatic spelling, and
  the *correct* one for several scenarios — fails `terraform plan` offline with
  a 403 against real STS. Fix: mirror the existing `endpoints.sfn` pattern in
  `arms/hcl-raw/environment/workspace/provider.tf` (a `dynamic "endpoints"`
  block, live-conditional) plus a loopback responder started around the plan
  step exactly as `build_static_tiers_sh` already does for `mock-sfn.py`. This
  touches a byte-shared, non-agent-owned bootstrap file → **every** hcl-raw task
  regenerates. Operator question **Q2**.
- **D2 — a literal AMI id in §3's prompt.** `cdk synth --no-lookups` refuses
  context lookups (`MachineImage.latestAmazonLinux2()`), and hcl-raw has no EC2
  mock for `data "aws_ami"`. Supplying one AMI id as a `placeholders` literal
  keeps all three arms offline and is a fact, not a hint.
- **D3 — `verifier.teardown` (blocks §12 only).** Fully specced in §12 (c);
  it is a near-clone of §5.1's `verifier.idempotence` and reuses its
  state-probe / completion-marker machinery.
- **D4 — `make split` churn.** Adding twelve ids to six existing ones re-ranks
  the 60/40 split and can flip an existing scenario `train ↔ holdout`
  (`docs/adding-scenarios.md` §7). Operator question **Q5**.

### 0.5 Evidence re-verification (2026-08-20, `gh` CLI reads only)

Every load-bearing URL in `docs/scenario-grades/2026-08-20-graded.json` for
these twelve was re-read. **Nine URLs no longer support the claim the
candidates doc attaches to them**, concentrated in four candidates; one whole
candidate's mechanism is falsified by provider evolution.

| Candidate | URL | Verdict |
|---|---|---|
| asg-tag-propagation | tfp-aws#729 | **DOES NOT SUPPORT** — `aws_instance.volume_tags` with >1 volume; zero mentions of ASG / launch template / `propagate_at_launch`. |
| asg-tag-propagation | tfp-aws#19890 | **DOES NOT SUPPORT** — `default_tags` not reaching `aws_instance` root block devices; wrong resource. |
| caller-identity-arn-as-principal | tfp-aws#11801 | **DOES NOT SUPPORT** — 252 👍 but it is the policy-statement **ordering** bug ("KMS just saves in a random order"), not the assumed-role-ARN-as-principal bug. The high reaction count in the synthesis doc is attached to the wrong claim. |
| ddb-gsi-attribute-definitions | tfp-aws#671 | **DOES NOT SUPPORT** — ignoring GSI **capacity** diffs. |
| ddb-gsi-attribute-definitions | tfp-aws#3828 | **DOES NOT SUPPORT** — spurious GSI recreation (old SDK hashing bug). |
| ddb-gsi-attribute-definitions | tfp-aws#556 | **DOES NOT SUPPORT** — 2017 `range_key` limitation, long fixed. |
| ddb-gsi-attribute-definitions | tfp-aws#728 | **DOES NOT SUPPORT** — DRY ergonomics request; its example actually *correctly* sets `non_key_attributes`. |
| acm-dns-validation | tfp-aws#27386 | **DOES NOT SUPPORT** — `aws_route53_zone_association` count/`depends_on`; nothing to do with ACM validation. |
| auto-created-log-groups | aws-cdk#22307, #24656, #37797 | **ALL THREE DO NOT SUPPORT** — every one is about auto-created `AWS::Logs::ResourcePolicy` (account limit of 10 / drift false-positives), a different CDK footgun entirely. The candidate's actual mechanism (implicit `/aws/lambda/<fn>` group: orphan, collide, never expire) has **no surviving evidence** in the graded set. Replacements found and cited in §8. |
| lambda-function-url-public-invoke | tfp-aws#38260, #35920 | **DOES NOT SUPPORT the claim as graded** — and they point the other way: the **provider itself** creates the public permission. See §9; the candidate is re-scoped. |
| lambda-function-url-public-invoke | tfp-aws#44829, #24325 | **PARTIALLY** — adjacent (a new mandatory second permission; the `AWS_IAM` condition key), not the graded claim. |
| iam-managed-policy-exclusive | 3× discuss.hashicorp.com | **UNVERIFIABLE via `gh`** (not GitHub). Replaced by provider-repo primary sources — see §2 (d). |
| s3-bucket-decomposition (5 URLs) | tfp-aws#23106 +4 | **ALL SUPPORT.** #23106 confirms 300 reactions / 93 comments exactly. |
| s3-notification singleton (7 URLs) | tfp-aws#501 +6 | **ALL SUPPORT** (#38402 partially — closed not-planned, bot-only thread). #1715 carries the best root cause (apparentlymart: the S3 API has one notification configuration and no create/update distinction); #48509 (OPEN, 2026-06-22) confirms the API still lacks per-rule/If-Match writes. |
| singleton-child-clobber (3 URLs) | tfp-aws#6334, #16791, #39376 | **ALL SUPPORT**; **#39376 is the strongest single artifact in the whole batch** — HashiCorp's own OPEN meta-issue formalizing "exclusive relationship management resources" across IAM / Organizations / Route53 / SSO / VPC. |
| cfn s3-notification tax | cfn-roadmap#79 | **SUPPORTS** — OPEN since 2019-08-01, **461 👍** live (the graded figure of 479 is stale but the same order), 52 comments. |
| cfn s3-notification tax | aws-cdk#2004, #29004, #28915, #35352 | **SUPPORT**; #16811 **PARTIALLY** (handler reliability, not clobber). |
| apigwv2 zero-vs-unset (3 URLs) | tfp-aws#30373, #14742, #27674 | **ALL SUPPORT**; #30373 (66 👍) and #27674 still **OPEN**. |
| ecr force_delete (2 URLs) | tfp-aws#33523, #9911 | **BOTH SUPPORT.** |

Two source-file claims were also re-checked directly:
`aws-cdk-lib/aws-s3/lib/notifications-resource/notifications-resource.ts`
still exists on `main` and still defines `class BucketNotifications` backed by a
custom-resource handler — **but** the handler's `managed=false` path now
*merges* with pre-existing configuration on unowned buckets rather than
replacing it wholesale, so "CDK eats your existing config" is now
"CDK attempts a fragile merge" (recent bugs: aws-cdk#29004, #28915, #35352).
That nuance belongs in the *unowned-bucket* live candidate, not in batch A.

### 0.6 Open questions for the operator

- **Q1 — greenfield `title` is agent-visible.** `workspace_title` is *forbidden*
  on single-step greenfield specs (§0.1), so a greenfield `title` cannot name
  the pitfall the way `id` may, and the pydantic identity validator does not
  even scan it. Widen §0.1 to *allow* (not require) `workspace_title` on
  greenfield specs, giving one uniform rule — operator-facing `id` + `title`,
  agent-facing `workspace_id` + `workspace_title`? All twelve blueprints below
  are written for **today's** rule (safe, goal-only titles), so this is a
  simplification, not a blocker.
- **Q2 — approve D1** (hcl-raw offline STS endpoint + loopback responder in the
  shared `provider.tf`), and: should both arms' mock STS identities return an
  **assumed-role** ARN (`arn:aws:sts::123456789012:assumed-role/…`, matching
  what a real trial's credentials actually look like) instead of today's IAM
  *user* ARN? That single change turns §4's headline catch from a graph-shape
  check into a plain tier-0 value check — and makes the offline fixture honest
  about the credential shape every live trial actually uses.
- **Q3 — `verifier.teardown` now or later?** It is §12's only blocker and is
  independently useful (§11's orphan half and §7's destroy-residue half both
  become gradeable with it). Build it inside batch A, or split §12 out into a
  small harness-feature batch?
- **Q4 — the terraconstructs arm for API Gateway v2.** 0.2.13 has **no**
  `aws-apigatewayv2` L2 (verified: `lib/aws/compute/` carries `restapi.ts`
  only). Disable the arm for §5 (my recommendation — an L1-binding arm
  measures "raw L1 TypeScript vs HCL", which is exactly what
  `s3-lambda-log-retention`'s own history says is *not* the comparison we
  want), or keep it as an explicitly-labelled L1 arm in its own stratum?
- **Q5 — when to re-run `generator/split.py --write`:** once after all twelve
  land (one logged diff, one possible round of equipping retirement), or per
  scenario (twelve diffs, twelve chances of a `train → holdout` flip)?
- **Q6 — evidence policy for the four weakened candidates.** §3, §4 and §11
  keep their mechanism but lose most of their cited signal, and §7's graded
  mechanism is falsified outright. Is re-mining required before speccing, or is
  it enough that each spec's provenance cites the replacements found here
  (which for §11 are strong: aws-cdk#11549 at 55 👍 plus three still-open issues)?
- **Q7 — is §10's guardrail sentence acceptable prompt content?** "This account
  does not permit the stack to create Lambda functions other than the ones that
  process events" is a real platform-team constraint, and it is what forces the
  awscdk arm off its own L2 onto an L1 escape hatch. It is *not* oracle-defensive
  spec-ese (it constrains the outcome, not the implementation shape), but it is
  the one prompt in the batch whose entire purpose is to make the thesis's
  favoured arm lose. Approve the framing, or drop §10 to a shape-metric-only
  variant of §9?
### 0.7 Seeded-artifact neutrality test

Operator rule (2026-08-20): **a seeded input file must not bias an
implementation shape.** If the artifact is the idiomatic input for exactly one
implementation (a machine-readable `openapi.json` practically demands
body-import), then either that shape is an oracle-accepted solution, or the
artifact is replaced by a shape-neutral one — e.g. a human API-design note in
markdown (routes, purpose, expected responses; PRD voice) that leaves
"hand-author an importable document" vs "build the resources individually" a
free agent choice. Traps should be shape-invariant wherever possible.

**Applied to this batch, the answer is: no blueprint seeds anything at all.**
That is a deliberate consequence of §0.3's option (b). The one artifact this
family of scenarios would otherwise want to seed is a Lambda deployment package,
and seeding it is exactly the biasing move the rule forbids in its strongest
form: a placeholder `.zip` is the idiomatic input for `filename` +
`filebase64sha256()` on the TF arms and for `Code.fromAsset` on awscdk, and
handing it to every arm erases the packaging differential the benchmark exists
to measure. Each blueprint's (b) section states "**Seeded files:** none"
explicitly, so the decision is visible per scenario rather than inherited
silently.

Two consequences to carry into the specs:

1. The five Lambda-bearing blueprints (§5, §7, §9, §10, §11) each let the agent
   choose its own packaging (inline source, `data "archive_file"`, an asset
   directory). The oracle must therefore grade the *function's* existence and
   wiring, never how its code got there — no assert may mention `filename`,
   `source_code_hash`, `Code`, or an archive resource.
2. Handler behaviour must never be graded statically. Where a live tier needs
   the function to actually respond (§5, §12), the live check asserts an HTTP
   outcome, and the ticket states the required response in outcome terms.


---

## 1. `s3-bucket-hardening-decomposition`

Merges the three graded siblings the operator's cluster note calls
near-duplicates on one evidence base: `s3-bucket-decomposition-missing-subresource`,
`s3-bucket-inline-subresources` and tier-A1 `s3-bucket-hardening-decomposition`.
One scenario.

### (a) Identity

| field | value |
|---|---|
| `id` | `s3-bucket-hardening-decomposition` |
| `workspace_id` | `document-archive` |
| `title` (agent-visible) | `Document archive bucket with versioning, KMS encryption, TLS-only access and no public access` |
| `difficulty` | 2 |
| `services` | `[s3, kms]` |

**Leak test.** The `id` names the pitfall (*decomposition* — that the four
controls are one construct on two arms and six resources on the third); the
agent must not see that word, hence the explicit `workspace_id`. `document-archive`
and the title name only the four things the ticket asks for, which the prompt
states anyway.
**Deny-list run** (`AGENT_IDENTITY_DENY_PATTERNS`): `document-archive` — no
match on any mechanism pattern (`lifecycle`, `replace*`, `drift`, `in[ _-]?use`,
`already exists`, …) or foreshadow pattern; clean. Title — contains no banned
token; `versioning` is not `\breplacements?\b`, and `access` is not on either
list. Clean. (Watch: an earlier draft used *"lifecycle rules"* in the title —
`\blifecycle\b` is a **mechanism** pattern and would have been refused; the
scenario deliberately does not ask for lifecycle rules.)

### (b) Prompt

`instruction.shared_body` (ticket voice):

```
We need an S3 bucket for archived customer documents.

Every version of an object must be kept, including after an overwrite or a
delete. Objects must be encrypted at rest with a KMS key that we control,
not with S3's default key. Any request that is not made over TLS must be
rejected. The bucket and its contents must not be reachable by anyone
outside this account under any circumstances.
```

Per-arm `language_line` (the standard trio; no per-scenario deltas needed):
- awscdk — "Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs."
- hcl_raw — "Author this as hand-written Terraform HCL (no modules)."
- terraconstructs — "Author this using terraconstructs (TypeScript) L2 constructs, synthesized via cdktn."

**Seeded files:** none.

**Oracle must tolerate / defend.**
- *"KMS key that we control"* admits two shapes: an `aws_kms_key` created in the
  same configuration, or an existing customer-managed key referenced by alias.
  Offline plan cannot read an alias data source, and referencing a key that does
  not exist is not a working solution — the oracle **behavioralizes**: the SSE
  configuration's `kms_master_key_id` / `KMSMasterKeyID` must reference a KMS key
  resource declared in this configuration (graph edge), and `sse_algorithm` must
  be `aws:kms`. It does **not** require a particular key-policy shape.
- *"must not be reachable from outside this account"* admits (i) the four
  public-access-block flags, (ii) a bucket-policy `Deny` on
  `aws:PrincipalAccount != <account>`, or (iii) both. The **oracle accepts (i)
  alone or (i)+(ii); it does not accept (ii) alone** — the ticket says "under any
  circumstances", and a policy-only answer is defeated by an ACL. That
  asymmetry is stated in `oracle.intent` so the strictness is reviewable, and it
  is the same on all three arms.
- *"Every version kept, including after a delete"* is satisfied by versioning
  alone; MFA-delete is **not** required and must not be asserted (it cannot be
  set by an API caller at all).

### (c) Oracle tier plan — **static only**

Tier-0 `structural_asserts` (all plan-time-known; no `jsonencode` contagion
because none of these reference a computed ARN):

| name | cfn_jsonpath | tf_jsonpath | op / expected |
|---|---|---|---|
| `versioning-enabled` | `$.Resources[?(@.Type=='AWS::S3::Bucket')].Properties.VersioningConfiguration.Status` | `$.planned_values..resources[?(@.type=='aws_s3_bucket_versioning')].values.versioning_configuration[*].status` | `eq` `"Enabled"` |
| `sse-is-kms` | `…Properties.BucketEncryption.ServerSideEncryptionConfiguration[*].ServerSideEncryptionByDefault.SSEAlgorithm` | `…[?(@.type=='aws_s3_bucket_server_side_encryption_configuration')].values.rule[*].apply_server_side_encryption_by_default[*].sse_algorithm` | `eq` `"aws:kms"` |
| `bpa-block-public-acls` … ×4 | `…Properties.PublicAccessBlockConfiguration.BlockPublicAcls` (+3) | `…[?(@.type=='aws_s3_bucket_public_access_block')].values.block_public_acls` (+3) | `eq` `true` |
| `tls-deny-statement-present` | `$.Resources[?(@.Type=='AWS::S3::BucketPolicy')].Properties.PolicyDocument.Statement[*].Condition.Bool['aws:SecureTransport']` | `…[?(@.type=='aws_s3_bucket_policy')].values.policy\|fromjson.Statement[*].Condition.Bool['aws:SecureTransport']` | `eq` `"false"` |

Tier-1 (Rego + cfn-guard, hand-authored):
1. **`tls-deny-covers-objects-too`** — the `Deny`-when-not-TLS statement's
   `Resource` set must contain **both** the bucket ARN and the objects ARN
   (`…/*`). This is the "covers both bucket and object ARNs" set-containment
   helper the graded data asks for. On the TF arms the policy string is
   plan-time-**unknown** whenever it is built from `aws_s3_bucket.x.arn`
   (§4.2.1) — so the TF-side rule resolves
   `.configuration…expressions.policy.references` transitively through a
   `data.aws_iam_policy_document` hop and asserts *two distinct* references to
   the bucket (`.arn` and an `${…}/\*` interpolation), and declares a
   `not_verifiable` entry for the case where the value is unresolved and the
   graph edge already passed. On awscdk the template is fully static, so it is a
   direct two-element check.
2. **`every-subresource-targets-this-bucket`** — each
   `aws_s3_bucket_*` sub-resource's `bucket` expression must reference the
   bucket created here, not a literal name (the per-bucket-coverage edge the
   graded data names).

**Catches** (4):

| name | taxonomy | broken fixture does | predicted tier |
|---|---|---|---|
| `subresource-omitted` | nested-attribute | drops `aws_s3_bucket_versioning` (the most-forgotten of the six); on awscdk/tcons the equivalent is dropping `versioned: true` | 0 / 0 |
| `tls-policy-misses-object-arn` | nested-attribute | writes the `Deny` statement with `Resource = [bucket_arn]` only — **the plausible-wrong solution**: it reads correctly, passes every existence check, and leaves every `GetObject` over plain HTTP allowed | 1 / 1 |
| `bpa-partially-set` | nested-attribute | sets `block_public_acls` + `block_public_policy` but leaves `ignore_public_acls` / `restrict_public_buckets` at their `false` defaults | 0 / 0 |
| `sse-left-at-s3-managed` | anti-L2 (see note) | uses `AES256`/`BucketEncryption.S3_MANAGED` — a *typed, valid, autocompleted* enum member on both typed arms that silently violates "a key we control" | 0 / 0 |

The `anti-L2` label on the last catch is honest: the CDK/tcons enum makes the
*wrong* value exactly as easy to pick as the right one, and the type system
cannot help — the falsifiability catch (H2) this scenario contributes.

**Static vs live:** everything above is provable offline on the synthesized
artifact. **No live_check.** Nothing here needs an apply.

### (d) Trap mechanics + evidence

Provider v4 split `aws_s3_bucket`'s inline blocks into ~10 standalone
sub-resources, so "a versioned, KMS-encrypted, TLS-only, non-public bucket" is
**one construct with four props** on awscdk/terraconstructs and **six resources**
(`aws_s3_bucket`, `_versioning`, `_server_side_encryption_configuration`,
`_public_access_block`, `_policy`, plus `aws_kms_key`) on hcl-raw, each
independently and silently omittable. The TLS statement is the sharp edge inside
the sharp edge: `aws-cdk-lib`'s `enforceSSL` **derives both ARNs** —
`aws-s3/lib/bucket.ts:2689-2704`, `resources: [this.bucketArn,
this.arnForObjects('*')]` — while a hand-written statement naming only the
bucket ARN looks right and protects nothing. terraconstructs ports the same
mechanism (`lib/aws/storage/bucket.js:694-695, 914-920`,
`enforceSSLStatement()` with the `aws:SecureTransport` condition), but has
**no `blockPublicAccess` prop at all** (verified: the only
`S3BucketPublicAccessBlock` in 0.2.13 is inside the `public: true` branch at
`bucket.js:726`, and it sets all four flags **false**) — so that arm must reach
for the `@cdktn/provider-aws` L1.

Evidence, all re-verified 2026-08-20 and all **SUPPORTING**:
`tfp-aws#23106` (CLOSED/completed, 2022-02-10, **300 reactions / 93 comments** —
HashiCorp's own pinned v4-decomposition mega-thread), `#23103` (29 👍, "SSE,
versioning and acl now labeled as Unconfigurable Attributes"), `#25325`
(closed not-planned — "Creating a fully configured s3 bucket unnecessarily
complex"), `#23758` (14 👍), `#26328` (a bucket failing an AWS Config encryption
rule after the split — the silent-omission failure in the wild).

### (e) Arm prediction (pre-registered)

**awscdk wins on tokens-to-green; terraconstructs second; hcl-raw last and
most likely to score 0.0.** Mechanism: one `s3.Bucket` with
`versioned/encryption/encryptionKey/enforceSSL/blockPublicAccess` versus six
resources plus a hand-written policy document. terraconstructs pays a small,
*measurable* escape-hatch tax for public-access block (one L1 resource) — the
first scenario in the corpus where the two typed arms are predicted to diverge
for a coverage reason rather than an engine reason. **The catch is LOUD**
(tier-0 on every arm): this scenario is a token-cost differential probe, not a
silent-failure probe, and its rows must not be pooled into silent-catch
statistics.

### (f) Effort / risk

- **S**. No new oracle machinery beyond the two tier-1 rules; no live tier; no
  mirror change; no fixtures.
- terraconstructs coverage: `storage.Bucket` ✅, `encryption.Key` ✅
  (`lib/aws/encryption/`), public-access block ❌ (L1 escape hatch — state this
  verbatim in `arms.terraconstructs.reason`).
- Risk: the KMS key makes the plan slightly bigger on every arm; keep the key
  policy out of the intent (do not grade it) or the scenario silently becomes an
  IAM-policy scenario.
- Watch: `aws_s3_bucket_versioning`'s `versioning_configuration` is a block →
  the tf_jsonpath needs the `[*]` list hop shown above; verify with
  `make check-paths` against a real plan before freezing.

---

## 2. `iam-managed-policy-exclusive-vs-attachment`

### (a) Identity

| field | value |
|---|---|
| `id` | `iam-managed-policy-exclusive-vs-attachment` |
| `workspace_id` | `batch-service-roles` |
| `title` (agent-visible) | `Two service roles that share the same managed policies` |
| `difficulty` | 2 |
| `services` | `[iam]` |

**Leak test.** The `id` names the diagnosis (*exclusive vs attachment* is
precisely what the agent is supposed to work out); it must not reach the agent →
explicit `workspace_id`. `batch-service-roles` and the title say only what the
ticket says.
**Deny-list run:** `batch-service-roles` — clean. Title: "share the same
managed policies" — no mechanism pattern (`exclusive` is not on the list, but it
is *diagnostic*, so it stays out of the agent-visible half regardless — the leak
test is "does this name reveal more than the prompt does?", not "does it match a
regex"). Clean.

### (b) Prompt

```
Our batch platform needs two IAM roles:

- `batch-runner`, assumed by ECS tasks, and
- `report-writer`, assumed by Lambda.

Both roles need read access to our reporting data in S3 (the AWS managed
policy AmazonS3ReadOnlyAccess), and both need the same team-defined policy
allowing them to write metrics to CloudWatch. Other teams attach their own
policies to these roles out of band; that must keep working.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- The last sentence is the **one in-world motivating sentence** the operator's
  rule allows. It is a fact about the environment (other teams attach policies),
  not a mechanism constraint and not a description of the fix. Without it the
  additive-vs-exclusive distinction is unobservable in a greenfield plan and the
  scenario would be measuring nothing; with it, every arm's task is the same.
- Three shapes satisfy the ticket on the TF arms: `aws_iam_role_policy_attachment`
  (additive — correct), `aws_iam_role_policy_attachments_exclusive` (exclusive
  but role-scoped and *declared* as such — also acceptable, and arguably the
  most deliberate answer, so **the oracle accepts it**), and
  `aws_iam_policy_attachment` (exclusive **account-wide** for that policy —
  rejected). The deprecated `managed_policy_arns` argument on `aws_iam_role` is
  also rejected. The oracle grades the *resource type used*, which is the
  behavioural fact, not the authoring style.
- On awscdk/terraconstructs the ticket is satisfied by `role.addManagedPolicy`
  in both; the third shape does not exist there (see (c)'s `applies_to`).

### (c) Oracle tier plan — **static only**

Tier-0:

| name | check |
|---|---|
| `two-roles-exist` | two `aws_iam_role` / `AWS::IAM::Role` resources, with the two `assume_role_policy` service principals `ecs-tasks.amazonaws.com` and `lambda.amazonaws.com` (`contains`, per role) |
| `no-account-exclusive-attachment` | `tf_jsonpath` `$.planned_values..resources[?(@.type=='aws_iam_policy_attachment')]` → `not_exists`; **`applies_to: [hcl_raw, terraconstructs]`** |
| `no-deprecated-managed-policy-arns` | `…[?(@.type=='aws_iam_role')].values.managed_policy_arns` → `not_exists`; `applies_to: [hcl_raw, terraconstructs]` |
| `managed-policy-attached-to-both-roles` | awscdk: each role's `ManagedPolicyArns` `contains` the S3 read-only ARN; TF arms: two `aws_iam_role_policy_attachment` resources whose `policy_arn` is that ARN |

Tier-1 (Rego/cfn-guard): **`customer-policy-is-attached-to-both-roles`** — the
team policy resource created in this configuration must be attached to *both*
roles. On the TF arms `policy_arn` referencing `aws_iam_policy.x.arn` is
plan-time-unknown, so this is a graph-edge rule over
`.configuration…expressions.policy_arn.references` grouped by `role`; on awscdk
it is a `Fn::Ref`/`Fn::GetAtt` containment check on each role's
`ManagedPolicyArns`.

**Catches** (3):

| name | taxonomy | broken fixture | `applies_to` | predicted tier |
|---|---|---|---|---|
| `account-exclusive-policy-attachment` | graph-dependency | uses one `aws_iam_policy_attachment` with `roles = [both]` — **the plausible-wrong solution**: it plans clean, applies clean, satisfies every functional assert, and silently detaches that managed policy from every *other* principal in the account | `[hcl_raw]` | 0 / — |
| `deprecated-exclusive-role-attribute` | nested-attribute | sets `managed_policy_arns` on the roles *and* adds one `aws_iam_role_policy_attachment` — the detach/reattach churn shape | `[hcl_raw]` | 0 / — |
| `policy-attached-to-one-role-only` | graph-dependency | attaches the team policy to `batch-runner` only | all 3 | 1 / 1 |

`applies_to` is doing exactly the job `SCHEMA.md` §3 describes: on awscdk the
first two mistakes have **no expressible form** (`aws-iam/lib/role.ts:600`
renders `managedPolicyArns` onto the role's own resource; `addManagedPolicy`
(`:684-689`) pushes into that same array and creates no attachment resource at
all), so those arms report `N/A`, not `MISSING`.

**Static vs live:** static. The *consequence* (churn on re-apply) is live, but
the *mistake* is a resource type visible in the plan, and grading the type is
strictly more robust than grading the churn.

### (d) Trap mechanics + evidence

Terraform models "policy X is attached to role Y" three ways with different
ownership semantics, and two of them are authoritative. `aws_iam_policy_attachment`
takes exclusive ownership of a **policy's** entire attachment set account-wide;
`aws_iam_role.managed_policy_arns` takes exclusive ownership of a **role's**
managed-policy set; `aws_iam_role_policy_attachment` is the additive one. Mixing
an authoritative form with an additive one produces attach/detach churn on every
apply. CloudFormation has one surface (`ManagedPolicyArns` on the role) and no
additive alternative, so the mistake cannot be made there — the CDK arm's
"advantage" here is a *narrower* API, which is worth stating plainly in the spec.

**The graded evidence for this candidate is three `discuss.hashicorp.com`
threads, which `gh` cannot verify.** Replaced with primary sources in the
provider repo, read on `main` 2026-08-20:
- `website/docs/r/iam_role.html.markdown`: `managed_policy_arns` is
  **"(Optional, Deprecated)"**, "Set of **exclusive** IAM managed policy ARNs";
  the note: *"this resource will take over exclusive management of the role's
  respective policy types… incompatible with … `aws_iam_policy_attachment`,
  `aws_iam_role_policy_attachment` … you will get resource cycling and/or
  errors"*; migration guidance names `aws_iam_role_policy_attachment` and
  `aws_iam_role_policy_attachments_exclusive`.
- `website/docs/r/iam_role_policy_attachments_exclusive.html.markdown` exists
  (2,674 bytes) — the purpose-built exclusive resource, with its own
  "removal of managed IAM policies which are not explicitly configured" warning.
- **`tfp-aws#39376`** (OPEN, 2024-09-18 → 2026-01-30, 11 👍, 29 comments) —
  HashiCorp's own meta-issue *"[Provider]: Implement exclusive relationship
  management resources"*, cataloguing this exact pattern across IAM inline
  policies, IAM customer-managed policies, Organizations policies, Route53
  records, SSO managed policies, VPC prefix lists, route tables and security
  groups. This is the strongest artifact in the batch and should anchor the
  spec's provenance.

### (e) Arm prediction

**Both typed arms reach green in fewer tokens and cannot commit the headline
mistake; hcl-raw carries the whole risk.** This is a scenario where the thesis
is predicted to win *for a reason worth stating honestly*: CFN's single
attachment surface is less expressive, and the benchmark scores the outcome, not
the expressiveness. Secondary prediction: hcl-raw solutions that reach for
`aws_iam_policy_attachment` will do so because it is the resource whose name most
resembles the question — a name-similarity failure, not a knowledge failure.

### (f) Effort / risk

- **S**. No new machinery; the tier-1 rule is a small graph-edge grouping.
- terraconstructs coverage: `iam.Role` + `iam.ManagedPolicy` ✅ — and verified
  **immune by construction**: `lib/aws/iam/role.js:212-215` has
  `managedPolicyArns` commented out with a citation to the provider's own
  exclusive-relationship design decision, and `lib/aws/iam/managed-policy.js:43`
  emits `IamRolePolicyAttachment` (the additive resource) per attached role.
- Risk: the "other teams attach policies out of band" sentence is load-bearing.
  If review deems it a hint, the alternative is to move the scenario to the
  brownfield queue (a seed already carrying an out-of-band attachment) — a
  different form, different stratum, and no longer batch A.

---

## 3. `asg-launch-template-tag-propagation`

### (a) Identity

| field | value |
|---|---|
| `id` | `asg-launch-template-tag-propagation` |
| `workspace_id` | `worker-fleet` |
| `title` (agent-visible) | `Auto Scaling worker fleet whose instances and volumes carry cost-allocation tags` |
| `difficulty` | 3 |
| `services` | `[autoscaling, ec2]` |

**Leak test.** The `id` names the mechanism (*tag propagation*, and where it
lives — the launch template) which is exactly the thing the hcl-raw agent must
discover; `worker-fleet` names the workload. The title states the goal in
outcome terms ("instances and volumes carry the tags") without naming
`propagate_at_launch` or `tag_specifications`.
**Deny-list run:** `worker-fleet` clean; title clean (no mechanism/foreshadow
match — "carry", "instances", "volumes", "cost-allocation" are unlisted).

### (b) Prompt

```
Stand up an Auto Scaling group of worker instances for the batch platform:
2 instances, scaling to at most 6, in a new VPC with two private subnets.
Instances run AMI {{WORKER_AMI_ID}} on t3.small.

Finance reconciles our EC2 spend from tags. Every instance the group
launches, and every EBS volume attached to it, must carry
CostCenter=platform-42 and Environment=prod — including instances the group
launches later when it scales out.
```

`placeholders`: `WORKER_AMI_ID`, `source: literal` (an `ami-…` id, `us-east-1`).
Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- Two working shapes exist on the TF arms: ASG `tag { … propagate_at_launch =
  true }` blocks, or launch-template `tag_specifications { resource_type =
  "instance" / "volume" }`, or both. **All are accepted** — the oracle asserts
  the *outcome* (every launched instance and volume carries both tags) by
  accepting either mechanism, because both genuinely produce it. What is
  rejected is tagging only the ASG resource, only the launch-template resource,
  or setting `propagate_at_launch = false`.
- "including instances the group launches later" is outcome language, not a
  hint: it distinguishes the requirement from "tag the two instances you
  create", which is what a naive `aws_instance`-based answer would do.
- The volume half is only reachable through the launch template's
  `tag_specifications` (`resource_type = "volume"`); on the CDK arms it is
  reached the same way through the ASG's launch template. Accepting either
  mechanism keeps the *instance* half shape-invariant while the *volume* half is
  the discriminating one.

### (c) Oracle tier plan — **static only**

Tier-0 (per arm, because the artifacts genuinely differ):

| name | arm | check |
|---|---|---|
| `asg-exists-with-capacity` | all | ASG resource exists, `min_size`/`max_size` (2/6) |
| `asg-tags-propagate-at-launch` | hcl_raw, terraconstructs | `$.planned_values..resources[?(@.type=='aws_autoscaling_group')].values.tag[*].propagate_at_launch` → `eq true` for each of the two required keys |
| `asg-tags-propagate-at-launch-cfn` | awscdk | `$.Resources[?(@.Type=='AWS::AutoScaling::AutoScalingGroup')].Properties.Tags[*].PropagateAtLaunch` → `eq true` |
| `volume-tags-present` | all | launch-template `tag_specifications` / `TagSpecifications` contains a `volume` entry carrying both keys |

Tier-1 (Rego/cfn-guard): **`every-required-tag-reaches-instances`** — for each
of `CostCenter` and `Environment`, at least one accepted mechanism carries it to
`instance`, and at least one to `volume`. Written as a quantified rule over the
union of the two mechanisms so that either shape passes; this is the
"tag map normalized across representations" helper the graded data asks for,
scoped down to one scenario (the batch does not need the full three-way
`tags`/`tags_all`/`Tags` normalizer that `default-tags-vs-tags-all` would).

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `tags-only-on-the-asg-resource` | nested-attribute | writes the tags where a `tags = { … }` map would go and never sets `propagate_at_launch` — **the plausible-wrong solution**: `aws_autoscaling_group` has *no* flat `tags` map at all, only `tag` blocks with a **required** `propagate_at_launch`, so this fixture is the shape an agent reaches for from muscle memory | 0 / 0 |
| `instance-tags-but-no-volume-tags` | nested-attribute | tags instances (either mechanism) and omits the `volume` tag specification — silently leaves every EBS volume untagged and the finance reconciliation half-broken | 0 / 0 |
| `provider-default-tags-instead` | anti-L2 | relies on the provider-level `default_tags` block to carry both tags — plans clean, and does not reach launched instances at all | 0 / — (`applies_to: [hcl_raw]`) |

**Static vs live:** static. A live variant would have to wait for instances to
launch and for tags to settle — the graded data flags exactly that slow-resource
cost, and plan-grading avoids it entirely.

### (d) Trap mechanics + evidence

`aws_autoscaling_group` has **no `tags` map argument at all** — only repeated
`tag` blocks, each requiring `key`, `value` and `propagate_at_launch` (verified
in `website/docs/r/autoscaling_group.html.markdown` on `main`, 2026-08-20; there
has never been a map form and there is no deprecation note). Tags set on the
launch template resource tag *the template*, not what it launches; reaching
launched instances and volumes needs `tag_specifications` with the right
`resource_type`. Provider `default_tags` do not propagate either. **The provider
docs are entirely silent on how ASG `tag` blocks and launch-template
`tag_specifications` interact — zero hits for either term in the other's
section — and that silence is itself part of the evidence** for why this is a
recurring failure.

Both typed arms handle it and were verified doing so:
- `aws-cdk-lib` routes ASG tags through a dedicated TagManager formatter —
  `core/lib/tag-manager.ts:105-142` `AsgFormatter.formatTags()`:
  `propagateAtLaunch: tag.applyToLaunchedInstances !== false`, registered at
  `:227` for `TagType.AUTOSCALING_GROUP` (`core/lib/cfn-resource.ts:640`).
  `aws-autoscaling/lib/auto-scaling-group.ts` itself contains **no**
  tag-handling and no `TagSpecifications` code — worth knowing, because it means
  the **volume** half on the awscdk arm is *not* automatic and the agent must do
  it explicitly. That makes the second catch bite all three arms.
- `terraconstructs` 0.2.13 does the same and goes further:
  `lib/aws/aws-tags.js:81-131` has a dedicated `visitAutoScalingGroup()` that
  merges into the `tag` blocks with `propagateAtLaunch:
  this.props.applyToLaunchedInstances !== false`, and its `applyToLaunchedInstances`
  JSDoc (`aws-tags.d.ts:30-42`) states it also keeps the tag *out of* the launch
  template's instance/volume tag specifications when false — i.e. this library
  wires **both** mechanisms.

Evidence status: of the three graded URLs, **two do not support the claim**
(`tfp-aws#729` is `aws_instance.volume_tags`; `#19890` is `default_tags` and root
block devices — neither mentions ASGs). The surviving one is
**`tfp-aws#7926`** (CLOSED/completed, 2019-03-13, **507 reactions**, 33 comments
— the `default_tags` feature request), whose comment thread explicitly discusses
`aws_autoscaling_group` needing special handling because `propagate_at_launch`
is per-tag and interacts badly with provider-level defaults. Spec provenance
should cite `tfp-aws#7926` + the two provider doc facts above, and should **not** repeat
the 507-reaction figure as if it were this candidate's own signal.

### (e) Arm prediction

**terraconstructs first, awscdk close second, hcl-raw last** — and this is the
one blueprint where terraconstructs is predicted to beat awscdk outright, because
it wires the launch-template tag specifications that `aws-cdk-lib`'s ASG does
not. The instance half is one aspect call on both typed arms and a required
per-tag flag on hcl-raw; the volume half is manual on awscdk and hcl-raw. If the
result contradicts this — e.g. awscdk agents routinely add volume tag
specifications by hand — that is a genuine falsification of the "L2 derives the
fiddly part" story for this family and must be reported as such.

### (f) Effort / risk

- **M-L**: the biggest plan in the batch (VPC + 2 subnets + launch template +
  ASG). Budget authoring time for the VPC scaffolding on all three arms, and
  keep the VPC out of the intent (do not grade it).
- **D2 applies**: the AMI id must be a `placeholders` literal, because
  `cdk synth --no-lookups` refuses `MachineImage.latestAmazonLinux2()`'s SSM
  context lookup and hcl-raw has no `data "aws_ami"` mock.
- terraconstructs coverage: `compute.AutoScalingGroup` ✅
  (`lib/aws/compute/auto-scaling/auto-scaling-group.js`), `compute.LaunchTemplate`
  ✅, `compute.Vpc` ✅ — the graded note's guess ("expect aws-autoscaling to be
  absent") is **wrong** for 0.2.13; the arm is fully supported and is the
  predicted winner.
- Risk: three VPC implementations is a lot of surface for one catch family.
  Mitigation if it proves too heavy — drop to a single-AZ VPC with one subnet;
  nothing in the catch set depends on two.

---

## 4. `caller-identity-arn-as-principal`

Operator comment: **"very high value"**.

### (a) Identity

| field | value |
|---|---|
| `id` | `caller-identity-arn-as-principal` |
| `workspace_id` | `release-artifact-store` |
| `title` (agent-visible) | `Artifact bucket writable only by the pipeline identity that deploys it` |
| `difficulty` | 2 |
| `services` | `[s3, iam, sts]` |

**Leak test.** The `id` *is* the wrong answer — it names the exact expression
the agent is supposed to avoid. Explicit `workspace_id` is mandatory here, more
so than anywhere else in the batch. `release-artifact-store` names the workload;
the title names the requirement in outcome terms ("the identity that deploys
it") without naming `aws_caller_identity`, `aws_iam_session_context`, or the
word *assumed-role*.
**Deny-list run:** `release-artifact-store` — clean (no mechanism/foreshadow
match; note `\breplacements?\b` does **not** match "release"). Title — clean.
Add `agent_deny_vocab: ["caller_identity", "caller identity", "session_context",
"assumed-role", "MalformedPolicyDocument"]` so the scenario's own reserved
vocabulary is reviewed in the same file as the trap.

### (b) Prompt

```
Create the release-artifact bucket for the delivery pipeline.

Only the pipeline identity — the IAM role this configuration is deployed
with — may read or write objects in it. No other principal in the account
may, including other roles and users; the bucket policy is the control we
are relying on, so it has to name that role and nothing broader.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- Three shapes satisfy the ticket on the TF arms: resolving the deploying role
  from `data "aws_iam_session_context"` (fed by
  `data.aws_caller_identity.current.arn`, which is what that data source is
  *for*); referencing an `aws_iam_role` declared in the same configuration (a
  pipeline role the agent also creates); or a literal role ARN built from
  `data.aws_caller_identity.current.account_id`. **All three are accepted** —
  each names a role, which is the behavioural requirement. What is rejected is
  a principal that is the raw `…current.arn` (an STS *session* ARN, not a valid
  policy principal) and a principal that is the account root
  (`arn:aws:iam::<acct>:root`, which silently grants every principal in the
  account and directly contradicts "nothing broader").
- On awscdk the idiomatic move is `new iam.AccountRootPrincipal()` /
  `AccountPrincipal(Stack.of(this).account)` — **which is the over-grant, and is
  rejected on that arm too.** The CDK arm's correct answer is an
  `iam.ArnPrincipal` naming a role it creates or is given. This is what makes
  the scenario three-armed rather than a Terraform-only quirk.
- "the bucket policy is the control we are relying on" is one in-world
  motivating sentence; it exists so that an answer of "attach an identity policy
  to the role instead" is out of scope for a reason the ticket states, not for a
  reason the oracle invents.

### (c) Oracle tier plan — **static, once D1 lands; a live variant is the stronger form and should follow**

**Blocking harness fact (D1).** An hcl-raw solution that declares
`data "aws_caller_identity" "current"` cannot `terraform plan` offline today:
the arm sets `skip_requesting_account_id = true` and has **no STS endpoint
override**, so the data source hits real STS with dummy credentials and 403s.
The terraconstructs arm already solves this (`mock-sts.js`, started around the
plan step by `build_static_tiers_sh`). Until the same loopback responder exists
for hcl-raw, a *correct* solution scores 0.0 on one arm for a reason unrelated
to the catch — the exact G1-class failure `provider.tf`'s own header describes.
**Do D1 first.**

With D1 in place, and if the mocks return an **assumed-role** ARN (operator
question Q2), the headline catch becomes a plain tier-0 value check, because a
data source's value is resolved *at plan time*:

| name | tier | check |
|---|---|---|
| `bucket-policy-principal-is-not-an-sts-session-arn` | 0 | `tf_jsonpath` `…[?(@.type=='aws_s3_bucket_policy')].values.policy\|fromjson.Statement[*].Principal.AWS` → `not_regex` `":sts::.*assumed-role"` |
| `bucket-policy-principal-is-not-account-root` | 0 | same path → `not_regex` `":root"`; `cfn_jsonpath` equivalent on `AWS::S3::BucketPolicy` |
| `bucket-policy-principal-is-a-role-arn` | 0 | same path → `regex` `"^arn:aws:iam::[0-9]{12}:role/"` |
| `policy-grants-object-actions` | 0 | statement `Action` `contains` `s3:PutObject` and `s3:GetObject` |

If Q2 is declined (mocks keep returning an IAM *user* ARN), the same three facts
are still checkable, but only as **tier-1 graph-edge rules** over
`.configuration…expressions.policy.references`: deny when the reference set
contains `data.aws_caller_identity.current.arn` and does **not** contain a
`data.aws_iam_session_context.*` or `aws_iam_role.*` hop. That is strictly
weaker (it cannot see through a `data.aws_iam_policy_document` composition
without transitive resolution) and is the second-best design.

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `sts-session-arn-as-principal` | typed-value-trap | uses `data.aws_caller_identity.current.arn` directly as the policy principal — **the plausible-wrong solution**: it reads as exactly what the ticket asked for, and produces `arn:aws:sts::…:assumed-role/Role/session`, which AWS rejects with `MalformedPolicyDocument` (or, where accepted, silently never matches) | 0 or 1 / — (`applies_to: [hcl_raw, terraconstructs]`) |
| `account-root-principal-over-grant` | graph-dependency | grants `AccountRootPrincipal` — plans clean everywhere, and hands the bucket to the whole account | 0 / 0, all arms |
| `principal-hardcoded-to-a-foreign-arn` | anti-L2 | hardcodes a plausible role ARN that no resource in the plan creates — passes every value-shaped check, fails the graph edge | 1 / 1 |

**Live variant (recommended as a follow-on, not a blocker).** The live trial's
credentials genuinely *are* assume-role credentials
(`QALocalInvocationApplicationAdmin`), so a live run reproduces the real
failure at `terraform apply`, not just its shape — the graded data's own note
("the trial's credentials must be assume-role credentials for the live variant
to reproduce") is satisfied by the existing IAM model (Amendment 24). Add it as
`live_check` asserting the deployed bucket policy's principal is a role ARN
**and** that a `GetObject` from a second, non-pipeline identity is denied.

### (d) Trap mechanics + evidence

`data.aws_caller_identity.current.arn` returns whatever STS says the current
credentials are. Under an assumed role — i.e. under every CI pipeline, every
`aws-vault` session and every aws-bench trial — that is
`arn:aws:sts::<acct>:assumed-role/<RoleName>/<SessionName>`, which is **not a
valid IAM policy principal**: it is an ephemeral session identity, not an
identity ARN. The correct resolution is the provider's own
`data "aws_iam_session_context"`, which maps a session ARN back to its issuer
role ARN. CloudFormation has no equivalent data source at all — the CDK-shaped
answer reaches for account-scoped principals, which is why the *over-grant* is
the CDK arm's characteristic failure and the *invalid principal* is the
Terraform arm's.

Evidence, re-verified 2026-08-20:
- **`tfp-aws#16657`** — *"service/ec2: Using STS GetCallerIdentity ARN As
  Principal Can Fail"*, CLOSED/not-planned, 2020-12-09 → 2024-03-07, 6 👍.
  **SUPPORTS** directly: the STS assumed-role ARN is rejected as
  `InvalidPrincipal`, and one commenter reports the `aws_iam_session_context`
  workaround still failing for their case.
- **`tfp-aws#42545`** — *"provider-defined function parsing 'session arn' from
  AssumeRole operation into Role Arn"*, CLOSED/not-planned, 2025-05-08 →
  2026-02-26. **SUPPORTS**: closed only because `aws_iam_session_context`
  already exists — i.e. the provider maintainers confirm the problem and its
  one blessed workaround.
- **`tfp-aws#11801` — DOES NOT SUPPORT.** The 252-reaction thread the synthesis
  doc attaches to this candidate is the policy-statement **ordering** bug
  ("KMS just saves in a random order"), an unrelated diff-noise issue. **The
  headline signal figure for this candidate is wrong and must not be carried
  into the spec.** Real signal is the two small-but-exact issues above; the
  candidate's value is its mechanism, not its reaction count — which is
  consistent with the operator's own "very high value" call, made on the
  mechanism.

### (e) Arm prediction

**No arm is predicted to sweep this one, and that is why it is valuable.**
hcl-raw and terraconstructs are exposed to the invalid-principal failure and
have a real, discoverable fix (`aws_iam_session_context`); awscdk cannot commit
that mistake but is steered by its own API surface toward the account-root
over-grant, which is *worse in production and equally scored here*. Prediction:
**awscdk fails the over-grant catch more often than the TF arms fail the
session-ARN catch**, because `AccountRootPrincipal()` is a first-class, typed,
autocompleted, widely-copied CDK idiom while the session-ARN mistake at least
announces itself at apply. If that holds it is a clean thesis-can-lose result on
a high-value security-shaped task.

### (f) Effort / risk

- **S** for the spec, **S-M** for D1 (one `dynamic "endpoints"` block plus a
  loopback responder wired into `build_static_tiers_sh`, mirroring `mock-sfn.py`
  exactly).
- **D1 is the blocker**, and it touches a byte-shared bootstrap file → every
  hcl-raw task regenerates. Operator sign-off (Q2) before touching it.
- Q2's second half (make both mocks return an assumed-role ARN) is what moves
  this scenario from a tier-1 graph rule to a tier-0 value check. It also makes
  the offline fixture honest about the credential shape every live trial uses.
  Cost: any existing scenario whose plan embeds the caller-identity ARN changes
  bytes — today none do.
- terraconstructs coverage: `storage.Bucket` + `iam.PolicyStatement`/
  `iam.ArnPrincipal` ✅. Note the arm reads caller identity *implicitly*
  (`AwsStack.account`) for ARN formatting, so its plan already contains the data
  source — the scenario does not add a new offline hazard there.

---

## 5. `apigwv2-route-settings-zero-vs-unset`

Operator comment: **"High value"**.

### (a) Identity

| field | value |
|---|---|
| `id` | `apigwv2-route-settings-zero-vs-unset` |
| `workspace_id` | `orders-http-api` |
| `title` (agent-visible) | `HTTP API for the orders service, throttled at 100 requests per second` |
| `difficulty` | 2 |
| `services` | `[apigatewayv2, lambda, iam]` |

**Leak test.** The `id` names the mechanism (*zero vs unset*) — the entire
diagnosis. `orders-http-api` and the title name the goal, including the number
the ticket states anyway.
**Deny-list run:** `orders-http-api` clean; title clean.

### (b) Prompt

```
Publish the orders service behind an HTTP API (API Gateway v2) on a stage
called `prod`, backed by a Lambda function on `GET /orders` that returns
{"orders": []} with HTTP 200.

Sustained traffic must be limited to 100 requests per second across the
API. Short spikes are normal for this service and must still be served —
up to 200 requests in a burst.
```

Language lines: awscdk and hcl_raw as standard; terraconstructs **not enabled**
(see (f)).
**Seeded files:** none.

**Oracle must tolerate / defend.**
- Two shapes satisfy the ticket: default route settings on the stage, or
  per-route settings on `GET /orders`. Both genuinely throttle the only route
  that exists. **The oracle accepts either** — the assert reads "the settings
  that apply to `GET /orders` carry rate 100 / burst 200", expressed as a union
  over the two locations, not "`default_route_settings.throttling_rate_limit ==
  100`".
- The burst number is in the ticket because the *requirement* has two halves
  (sustained rate and tolerated spikes), which is how a real throttling ticket
  is written — not to defend the oracle. The trap does not depend on the agent
  being told only one number; see (d).
- Handler behaviour (`{"orders": []}`) is stated so the live check has an
  outcome to assert. No static assert may read the handler's code.

### (c) Oracle tier plan — **live is required; static is necessary but not sufficient**

Tier-0 (static):

| name | check |
|---|---|
| `stage-named-prod-exists` | `aws_apigatewayv2_stage` / `AWS::ApiGatewayV2::Stage` with `name == "prod"` |
| `route-get-orders-exists` | `aws_apigatewayv2_route` with `route_key == "GET /orders"` |
| `throttle-rate-is-100` | the union path over default/per-route settings → `eq` 100 |
| `throttle-burst-is-200` | same → `eq` 200 |
| `integration-targets-the-function` | tier-1 graph edge: the integration's `integration_uri` references the Lambda created here |

**The live tier is what makes this scenario worth building.** The graded
evidence's sharpest fact is that *the plan does not reflect the drift*
(`tfp-aws#27674`): an unset `throttling_burst_limit` is applied as `0` by the
API, and `0` means "reject everything". A plan-only oracle can assert the
happy-path values but **cannot** distinguish "unset" from "explicitly 0" in the
one direction that matters, because an unset optional attribute is simply absent
from `planned_values`.

`verifier.live_check` (hand-authored, `gating: true`), asserting:
1. `GET /orders` on the deployed stage returns **200** with the expected body;
2. a short burst of 5 sequential requests returns **no 429**;
3. the deployed stage's settings, read back with
   `apigatewayv2:GetStage`, carry a **non-zero** burst limit.

Assertion 3 is the actual catch. `concurrency_mode: "mutating"`;
`agent_role_name` per Amendment 24 (`QALocalInvocationApplicationAdmin`).

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `burst-limit-left-unset` | typed-value-trap | sets only `throttling_rate_limit = 100` — **the plausible-wrong solution**: plan-green, apply-green, and every request 429s because the omitted burst is applied as 0 | **live** / — (`applies_to: [hcl_raw]`) |
| `throttle-set-to-zero` | typed-value-trap | sets both limits to `0` (a literal reading of "no burst allowance") | 0 / 0 |
| `settings-on-the-wrong-stage` | graph-dependency | attaches route settings to `$default` while deploying `prod` | 0 / 0 |

The first catch is `predicted_tier_caught: "live"` **by construction**, so
`gates/oracle_falsifiability.py`'s `"live"` branch applies: the fixture must
keep static reward `1.0` and its offline run must print
`CDKTN_BENCH_LIVE_ONLY_CONFIRMED`, earned mechanically (here: a two-plan diff
showing the burst attribute absent from `planned_values` in both the correct and
the broken fixture — which *is* the proof that no static tier can separate them).

### (d) Trap mechanics + evidence

`aws_apigatewayv2_stage`'s `default_route_settings.throttling_burst_limit` /
`throttling_rate_limit` are plain optional ints (verified in
`website/docs/r/apigatewayv2_stage.html.markdown` on `main` — the docs say
nothing more than "(Optional) Throttling burst limit for the default route",
which is itself part of the pain). Omitting one, or removing it later, results
in **0** being applied rather than "not configured", and 0 throttles everything.
`aws-cdk-lib` renders the same two fields but from an optional *object*:
`aws-apigatewayv2/lib/http/stage.ts:213-215` —
`defaultRouteSettings: props.throttle || props.detailedMetricsEnabled ? {
throttlingBurstLimit: props.throttle?.burstLimit, throttlingRateLimit:
props.throttle?.rateLimit } : undefined` — so on the CDK arm an unset half is
`undefined` and is simply **absent from the template**, i.e. genuinely "not
configured". Note the same code preserves an explicit `0` (the branch tests the
object, not the number), so the CDK arm is exposed to the *second* catch and not
the first: a real, asymmetric, source-verified tier split.

Evidence, all re-verified and all **SUPPORTING**:
- **`tfp-aws#30373`** — *"Removal of the Default route throttling for an API
  GatewayV2 sets the limits to 0"*, **OPEN**, 2023-03-31 → 2026-06-17, **66 👍**,
  10 comments.
- **`tfp-aws#27674`** — *"Empty `default_route_settings.throttling_burst_limit`
  results in 0, not 'not configured'"*, **OPEN**, 2022-11-07 → 2026-01-08, 15 👍;
  explicitly notes the plan does not reflect the drift.
- **`tfp-aws#14742`** — CLOSED/not-planned, 2020-08-19 → 2026-01-30, 31 👍:
  the same zero-vs-null behaviour producing 429s on a live endpoint.

### (e) Arm prediction

**awscdk wins, and for a reason the type system genuinely owns**: `throttle?:
{rateLimit, burstLimit}` is one optional object whose halves are either both
supplied or both absent, so the "half-configured" state the provider punishes is
awkward to express. hcl-raw's two independent optional ints make it the default
state. Predicted outcome: awscdk green; hcl-raw green *at plan* and failing the
live tier at a materially higher rate than any other scenario in the batch —
which is exactly the "where in the pipeline does each arm's failure land"
measurement that the excluded `ssm-securestring` candidate was going to provide.

### (f) Effort / risk

- **M**, and it is the batch's second-most expensive scenario after §12: live,
  mutating, needs a real deploy and a hand-authored `live_check.py`.
- **terraconstructs: recommend `enabled: false`**, reason: 0.2.13 has no
  `aws-apigatewayv2` L2 surface at all (verified — `lib/aws/compute/` carries
  `restapi.ts`, `stage.ts`, `deployment.ts` for REST v1 only; there is no
  `http/` tree). An L1-binding arm would measure "raw `@cdktn/provider-aws`
  TypeScript vs HCL", which `s3-lambda-log-retention`'s own history says is not
  the comparison we want. Operator question **Q4**.
- **Blocking authoring step:** before freezing any tier-0 assert, run a real
  plan for both spellings (burst set / burst omitted) and record what
  `planned_values` actually contains. Everything above assumes "absent when
  unset"; if the provider marks it computed-and-known, the catch may be
  partially static and the tier prediction changes. This is the §4.2.1
  discipline, and it is a hard gate for this scenario.
- Reuses `apigw-redeploy`'s live machinery wholesale (mutating concurrency,
  reset, `TF_VAR_cdktn_bench_live`), so the marginal harness cost is zero.

---

## 6. `ddb-gsi-attribute-definitions`

### (a) Identity

| field | value |
|---|---|
| `id` | `ddb-gsi-attribute-definitions` |
| `workspace_id` | `orders-table` |
| `title` (agent-visible) | `Orders table with a per-customer query index` |
| `difficulty` | 2 |
| `services` | `[dynamodb]` |

**Leak test.** The `id` names the mechanism (*attribute definitions* — the exact
block the hcl-raw agent gets wrong); `orders-table` and the title name the data
model the ticket describes.
**Deny-list run:** `orders-table` clean; title clean.

### (b) Prompt

```
Create the DynamoDB table for the orders service.

Each order is identified by orderId. The support tooling needs to list one
customer's orders newest-first, and for that listing it only ever shows the
order's status and total — nothing else should be read from the index.

Items also carry shippingAddress, lineItems and a paymentReference.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- The last line exists so the item shape is realistic, and it is the whole
  scenario: an agent that reads "items carry these attributes" as "declare these
  attributes" writes the failure. That is a data-model fact a ticket would
  state, not a mechanism constraint — and it is stated identically to all three
  arms, where only one of them can act on it wrongly.
- Two shapes satisfy the listing requirement: a GSI with `INCLUDE` projection of
  `status` + `totalAmount`, or `KEYS_ONLY` plus a follow-up read. **The oracle
  accepts `INCLUDE` only**, because the ticket says the listing shows status and
  total and reads nothing else — `KEYS_ONLY` forces a second read of the whole
  item, which is the opposite. This is stated in `oracle.intent`. `ALL` is
  rejected for the same reason ("nothing else should be read from the index").
- Billing mode is deliberately unstated and ungraded.

### (c) Oracle tier plan — **static only**

Tier-0, and this is the scenario `set_eq` was added for:

| name | cfn_jsonpath | tf_jsonpath | op / expected |
|---|---|---|---|
| `attribute-definitions-are-exactly-the-key-attributes` | `$.Resources[?(@.Type=='AWS::DynamoDB::Table')].Properties.AttributeDefinitions[*].AttributeName` | `$.planned_values..resources[?(@.type=='aws_dynamodb_table')].values.attribute[*].name` | `set_eq` `["orderId","customerId","createdAt"]` |
| `gsi-partition-and-sort-key` | `…Properties.GlobalSecondaryIndexes[*].KeySchema` | `…values.global_secondary_index[*].hash_key` / `.range_key` | `eq` `customerId` / `createdAt` |
| `gsi-projection-is-include` | `…GlobalSecondaryIndexes[*].Projection.ProjectionType` | `…global_secondary_index[*].projection_type` | `eq` `"INCLUDE"` |
| `gsi-projects-exactly-status-and-total` | `…Projection.NonKeyAttributes` | `…global_secondary_index[*].non_key_attributes` | `set_eq` `["status","totalAmount"]` |
| `table-key-schema` | `…Properties.KeySchema[*]` | `…values.hash_key` | `eq` `"orderId"` |

Every one of these is a static echo of agent-supplied config — no computed ARNs,
no `jsonencode` contagion — so all five are sound at tier 0 (§4.2.1). **No
tier-1 rules are needed**, which is what makes this the cheapest scenario in the
batch after §1.

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `attribute-definitions-include-non-key-attributes` | typed-value-trap | declares `attribute` blocks for `shippingAddress`, `lineItems`, `paymentReference` too — **the plausible-wrong solution**: it is what "declare your schema" means in every other database, it is what the prompt's last line invites, and the provider answers with *"all attributes must be indexed. Unmatched indexes"* at apply and a permanent plan loop | 0 / — (`applies_to: [hcl_raw]`) |
| `include-projection-without-non-key-attributes` | typed-value-trap | sets `projection_type = "INCLUDE"` and omits `non_key_attributes` | 0 / 0 |
| `gsi-key-attribute-not-declared` | graph-dependency | adds the GSI on `customerId`/`createdAt` but leaves those out of the `attribute` set — the mirror image of the first catch, and the one the typed arms cannot commit | 0 / — (`applies_to: [hcl_raw]`) |

**Static vs live:** static. The failure is a provider-side validation error and
a plan loop; both are visible without an apply.

### (d) Trap mechanics + evidence

`aws_dynamodb_table` requires the `attribute` set to be **exactly** the
attributes used as table or index keys — no more, no fewer — which is
counter-intuitive for a schemaless store where every other tool wants the full
item shape. The provider docs are explicit
(`website/docs/r/dynamodb_table.html.markdown`, read on `main` 2026-08-20):

> "**Note:** Only define attributes on the table object that are going to be
> used as a hash key or range key for the table itself, or for LSI/GSI keys.
> Adding attributes not used in these scenarios **causes an infinite plan
> loop**." — and `non_key_attributes`: "Only required with `INCLUDE` as a
> projection type".

Both typed arms derive the set instead of accepting it, and both were read
directly:
- `aws-cdk-lib` — `aws-dynamodb/lib/table.ts:1802-1813` `registerAttribute()`
  pushes into `this.attributeDefinitions` only for keys, called from the table
  PK/SK path and from every GSI/LSI (`:1749`, `:1789`), rendered at `:1365`.
  Projection validation at `:1760-1767` throws *"non-key attributes should be
  specified when using INCLUDE projection type"* and the converse.
- `terraconstructs` 0.2.13 — `lib/aws/storage/table.js:1085-1093`
  `registerAttribute()` with the identical de-dup-and-type-check shape, rendered
  at `:685` (`attribute: this.attributeDefinitionsInternal`); the same INCLUDE
  validation at `:1048-1056`.

So on both typed arms the mistake is **unreachable through the public API**, and
the INCLUDE mistake is a synth-time `ValidationError` — tier 0 on all three arms
but for structurally different reasons (a thrown validation vs a provider schema
rejection).

Evidence status: **four of the five graded URLs do not support the claim** —
`tfp-aws#671` (GSI capacity `ignore_changes`), `#3828` (spurious GSI recreation),
`#556` (2017 `range_key` gap), `#728` (DRY ergonomics request, whose example
actually sets `non_key_attributes` correctly). The surviving one is
**`tfp-aws#46322`** — *"terraform 6.30 failed with aws_dynamodb_table Error: all
indexes must match a defined attribute. Unmatched indexes"*, CLOSED/completed,
2026-02-04 → 2026-05-16, 10 👍, 11 comments — recent, exact, and it fires on
provider 6.x. Spec provenance: `tfp-aws#46322` + the two doc quotes above.

### (e) Arm prediction

**Both typed arms green with near-identical token counts; hcl-raw carries all
the risk.** This is a clean, small, L2-favourable entry whose value is precisely
that it is *cheap and unambiguous* — a control against which the noisier
scenarios can be read. Secondary prediction: the failure mode on hcl-raw is
over-declaration (catch 1), not under-declaration (catch 3), because the prompt's
item description invites it and because "declare the schema" is the transferable
instinct from every relational tool.

### (f) Effort / risk

- **S** — smallest oracle in the batch (five tier-0 asserts, zero Rego).
- terraconstructs coverage: `storage.Table` ✅ with GSI support verified above;
  set `arms.terraconstructs.enabled: true` citing `lib/aws/storage/table.js`.
- Risk: none material. Watch only that `values.attribute` is a list of blocks
  (`[*].name`) in plan JSON and that the GSI list hop is right — confirm with
  `make check-paths` before freezing.

---

## 7. `lambda-function-url-partner-scoped-invoke` — **RE-SCOPED**

> **The graded candidate's trap does not exist on any supported provider
> version.** `lambda-function-url-public-invoke` was graded on the claim that an
> `aws_lambda_function_url` with `authorization_type = "NONE"` needs a separate
> `aws_lambda_permission` or returns 403, while `addFunctionUrl` derives it. That
> is false today and has been false since Function URLs shipped. **Do not spec
> the graded shape.** What follows is the re-scope; §0.6 Q6 asks whether it
> should be authored at all in batch A.

### (a) Identity

| field | value |
|---|---|
| `id` | `lambda-function-url-partner-scoped-invoke` |
| `workspace_id` | `webhook-endpoint` |
| `title` (agent-visible) | `Webhook endpoint invocable only by our partner's account` |
| `difficulty` | 2 |
| `services` | `[lambda, iam]` |

**Leak test.** `webhook-endpoint` and the title state the goal. The `id` names
the mechanism half (*partner-scoped invoke*) that the oracle grades.
**Deny-list run:** `webhook-endpoint` clean; title clean.

### (b) Prompt

```
Our partner posts events to us over HTTPS. Stand up a Lambda function with
a function URL that they call directly — no API Gateway in front of it.

Only the partner may invoke it: their AWS account is {{PARTNER_ACCOUNT_ID}}
and they call with SigV4-signed requests from a role in that account.
Nobody on the public internet may invoke the URL.
```

`placeholders`: `PARTNER_ACCOUNT_ID`, `source: literal` (an illustrative
12-digit id, per SCHEMA §2.2's `literal` guidance).
Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- Two shapes satisfy "only the partner": `authorization_type = AWS_IAM` plus a
  resource-based permission scoped to the partner principal, or `AWS_IAM` plus
  no permission at all and a cross-account role assumption on their side.
  **The oracle accepts either only if `authorization_type` is `AWS_IAM`**; the
  permission, when present, must name the partner account and must carry
  `function_url_auth_type = "AWS_IAM"` (a field that is easy to omit and whose
  omission makes the statement not match function-URL invocations).
- `NONE` is rejected regardless of any additional policy: the ticket says nobody
  on the public internet may invoke it, and with `NONE` the provider itself
  attaches a public statement the agent cannot opt out of (see (d)).

### (c) Oracle tier plan — **static; the residue half is live and belongs with §12**

Tier-0:

| name | check |
|---|---|
| `function-url-auth-is-iam` | `…[?(@.type=='aws_lambda_function_url')].values.authorization_type` / `AWS::Lambda::Url.Properties.AuthType` → `eq` `"AWS_IAM"` |
| `no-public-invoke-permission` | no `aws_lambda_permission` / `AWS::Lambda::Permission` with `principal == "*"` → `not_exists` |
| `permission-auth-type-matches` | any permission with `action == "lambda:InvokeFunctionUrl"` must have `function_url_auth_type == "AWS_IAM"` (`absent_or_eq` is wrong here — the field is required for the statement to match, so `eq`) |

Tier-1: **`invoke-permission-scoped-to-the-partner`** — the permission's
`principal`/`source_account` must be the partner account id, not `*` and not
this account.

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `auth-type-none-makes-it-public` | typed-value-trap | uses `authorization_type = "NONE"` and adds a partner-scoped permission on top, believing the permission narrows it — **the plausible-wrong solution**: on the TF arms the provider *additionally* attaches its own public statement, and on the CDK arms `FunctionUrl` does the same; the endpoint is world-invocable in every arm | 0 / 0 |
| `permission-missing-function-url-auth-type` | nested-attribute | grants `lambda:InvokeFunctionUrl` to the partner without `function_url_auth_type`, so the statement never matches a function-URL call | 0 / — (`applies_to: [hcl_raw]`) |
| `permission-principal-is-wildcard` | graph-dependency | scopes to `*` with a `source_account` condition only | 1 / 1 |

**The live half, deliberately deferred to §12's tier.** The genuinely new fact
found during re-verification is that on the TF arms the auto-attached public
statements are **not tracked in Terraform state and are left behind on
`destroy`** — a residue that only a teardown-grading oracle can see. That makes
an excellent hcl-unfavourable entry (rare in this portfolio) but it is *the same
harness feature* §12 needs, so it should be authored as a second catch on this
scenario **after** `verifier.teardown` exists, not as a reason to hold up batch A.

### (d) Trap mechanics + evidence (re-verified; the graded mechanism is falsified)

On `hashicorp/aws` (verified against `main`, behaviour present since the original
Function URLs PR **#24053**, 2022-04-07, and in every release since):

> `website/docs/r/lambda_function_url.html.markdown`: *"When
> `authorization_type` is `"NONE"` the `lambda:InvokeFunctionUrl` permission
> allowing a public endpoint and `lambda:InvokeFunction` permission with the
> `InvokedViaFunctionUrl` flag set to `true` are automatically added to the
> Lambda function on creation. **These policies are NOT removed from AWS when
> the resource is destroyed.**"*

The provider itself calls `AddPermission` with statement ids
`FunctionURLAllowPublicAccess` and (since PR **#44858** → **v6.28.0**,
2026-01-07, made compulsory by AWS in Oct 2025) `FunctionURLAllowInvokeAction`.
**There is no opt-out** — the resource schema carries only `authorization_type`,
`cors`, `function_name`, `invoke_mode`, `qualifier`. So:

- the graded claim ("NONE + no permission ⇒ 403") is **wrong**: it yields a real
  public 200;
- the actual TF-side pitfalls are (i) `NONE` is *silently, unstoppably public*
  and (ii) it leaves untracked resource-policy residue after `destroy`.

`aws-cdk-lib` behaves symmetrically for (i): `aws-lambda/lib/function-url.ts:269-273`
adds `invoke-function-url` with `AnyPrincipal`, `lambda:InvokeFunctionUrl` and
`functionUrlAuthType: NONE` whenever the auth type is `NONE` — but as a
*template resource*, i.e. tracked and deleted with the stack. `terraconstructs`
0.2.13 ports it line-for-line (`lib/aws/compute/function-url.js:159-165`).

Evidence re-verification:
- `tfp-aws#39396` — **SUPPORTS** a different, live-only fact: account-level
  Lambda block-public-access makes the public-permission creation fail with
  `PublicPolicyException` for new functions. Relevant as a *feasibility warning*
  for any live variant in the sandbox account.
- `tfp-aws#38260` (closed not-planned) and `#35920` (closed not-planned) —
  **DO NOT SUPPORT the graded claim**; both describe the auto-created permission
  and its orphaning, i.e. the opposite dynamic.
- `tfp-aws#44829` (60 👍, closed/completed) and `#24325` — **PARTIALLY**: the
  first is about exposing the new `invoked_via_function_url` field; the second
  about the `AWS_IAM` condition key. Adjacent, not the graded claim.

### (e) Arm prediction

**Near-parity, with a small awscdk edge, and an hcl-raw teardown penalty once
§12's tier exists.** All three arms express `AWS_IAM` + a scoped permission
comparably; the discriminator is the `function_url_auth_type` field, which
hcl-raw must supply by hand and both typed arms derive
(`grantInvokeUrl`/`addPermission` set it). This is best registered as a
**parity control**: if the typed arms show no advantage, that is a correct
result for a scenario whose mechanism is one field.

### (f) Effort / risk

- **S** for the re-scoped static form; the interesting half waits on §12.
- terraconstructs coverage: `compute.LambdaFunction` + `compute.FunctionUrl` ✅
  (`lib/aws/compute/function-url.js`), `grantInvokeUrl` present.
- Risk: **this is the batch's weakest scenario** now that its graded mechanism is
  gone. Recommend authoring it last (rank 10) or returning it to the mining pool
  in favour of a candidate with a live mechanism — operator question Q6.
- Do **not** build a live variant that needs a public function URL in the
  sandbox: `#39396` says account-level block-public-access may refuse the public
  statement outright, which would fail the trial for an environment reason.

---

## 8. `acm-dns-validation-record-wiring`

Operator comment: *"Very relevant, even used as an example in CDKTF / CDK
Terrain docs — `edge.Certificate` handles this in TerraConstructs transparently."*

### (a) Identity

| field | value |
|---|---|
| `id` | `acm-dns-validation-record-wiring` |
| `workspace_id` | `storefront-certificate` |
| `title` (agent-visible) | `Public certificate for the storefront domain and its www alias` |
| `difficulty` | 3 |
| `services` | `[acm, route53]` |

**Leak test.** The `id` names the mechanism (*validation record wiring*) — the
whole job on the hcl-raw arm. `storefront-certificate` and the title name the
deliverable.
**Deny-list run:** `storefront-certificate` clean; title clean.

### (b) Prompt

```
We are moving the storefront to a new domain. Create the public hosted zone
for `{{ZONE_NAME}}` and an ACM certificate covering both `{{ZONE_NAME}}` and
`www.{{ZONE_NAME}}`, validated through DNS in that zone.

The certificate has to be usable by the load balancer we add next quarter —
so it must reach ISSUED on its own, without anyone clicking through the
console.
```

`placeholders`: `ZONE_NAME`, `source: literal` (e.g. `storefront.example.com`).
Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- "without anyone clicking through the console" is one in-world motivating
  sentence: it is what makes DNS validation's *automation* the requirement,
  rather than merely requesting a certificate. It names no mechanism.
- "the load balancer we add next quarter" is realistic day-1 context that names
  no specific future change — explicitly allowed by `docs/adding-scenarios.md`
  §1 item 2b ("realism is fine, prophecy is not"). It is **not** a `steps:`
  trigger: nothing in this scenario's grading depends on a second point in time.
  Check it against `AGENT_FORESHADOW_DENY_PATTERNS` anyway — it matches none
  (no `next[ _-]?step`, no `subsequent`, no `iteration`).
- Two shapes satisfy the wiring on the TF arms: `for_each` over
  `domain_validation_options` (the modern idiom) or explicit per-domain record
  resources. **Both accepted** — the oracle asserts one validation record per
  distinct domain and a validation resource that waits on them, never a
  particular meta-argument.

### (c) Oracle tier plan — **static only, and necessarily so**

Live is impossible: validation requires real NS delegation for a domain the
account does not own, so the certificate would never leave `PENDING_VALIDATION`.
Plan/synth grading is the entire scenario. The asserts are **per-arm by
necessity**, and this blueprint is the batch's best worked example of
oracle-equivalence across structurally different artifacts:

| name | arm | check |
|---|---|---|
| `certificate-covers-both-names` | all | `domain_name` == zone, `subject_alternative_names` `set_eq` `["www.<zone>"]` (CFN: `DomainName` + `SubjectAlternativeNames`) |
| `validation-method-is-dns` | all | `validation_method` / `ValidationMethod` → `eq` `"DNS"` |
| `validation-records-one-per-domain` | hcl_raw, terraconstructs | count of `aws_route53_record` resources whose `type` is `CNAME` and whose `zone_id` references the zone created here **== 2** — the group-by-parent cardinality helper |
| `validation-waits-for-records` | hcl_raw, terraconstructs | an `aws_acm_certificate_validation` exists and its `validation_record_fqdns` expression references those records (graph edge, tier 1) |
| `validation-options-name-the-zone` | awscdk | `AWS::CertificateManager::Certificate.Properties.DomainValidationOptions[*].HostedZoneId` exists for **both** domain names — the CFN-native equivalent, deliberately a weaker `exists`+cardinality check because there is nothing else to check (recorded in the assert's own description, mirroring `named-resource-replacement`'s asymmetry precedent) |

**Catches** (4):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `no-validation-records-at-all` | graph-dependency | requests the certificate and stops — plan-green, and the certificate never issues | 0 / — (TF arms) |
| `one-record-for-two-domains` | graph-dependency | writes a single `aws_route53_record` from `domain_validation_options[0]` — **the plausible-wrong solution**, and the historically most common one (`tfp-aws#7918`, `#5237`); the apex validates, the `www` SAN never does, and the certificate stays `PENDING_VALIDATION` forever | 0 / — (TF arms) |
| `missing-certificate-validation-resource` | graph-dependency | creates the records but no `aws_acm_certificate_validation`, so nothing downstream ever waits for ISSUED | 0 / — (TF arms) |
| `email-validation-instead` | anti-L2 | picks `EMAIL` validation — a typed, valid enum member on all three arms that silently requires a human to click a link | 0 / 0, all arms |

The fourth catch is what keeps the awscdk arm honestly graded: three of the four
mistakes are structurally impossible there, and `applies_to` says so rather than
pretending otherwise.

### (d) Trap mechanics + evidence

The three arms produce three genuinely different artifacts for one intent:

- **awscdk** — `aws-certificatemanager/lib/certificate.ts:353-356` renders
  `domainValidationOptions: renderDomainValidation(...)`, which for
  `ValidationMethod.DNS` emits `{ domainName, hostedZoneId }` per name
  (`:389+`). **No `AWS::Route53::RecordSet` is synthesized at all** —
  CloudFormation/ACM create and clean up the validation records themselves.
  `DnsValidatedCertificate` is deprecated in this version
  (`dns-validated-certificate.ts:74`).
- **terraconstructs** — `edge.PublicCertificate` (note: the class is
  `PublicCertificate`, not `Certificate` as the operator's note calls it)
  synthesizes the wiring for you: `lib/aws/edge/certificate.js:103-124` loops the
  zone lookup, creates one `RecordSet` per domain from
  `domainValidationOptions.get(index)` with `allowOverwrite: true`, then creates
  `AcmCertificateValidation` with
  `validationRecordFqdns: records.map(r => r.fqdn)`. The operator's claim
  ("handles this transparently") is **confirmed against 0.2.13** — and note the
  graded data's own coverage guess ("no acm/route53 L2s in 0.2.13") is **wrong**;
  `edge/` carries `certificate.js`, `dns-zone.js`, `dns-record.js`.
- **hcl-raw** — every bit of that by hand, including the `for_each`-over-
  `domain_validation_options` transform that the provider made necessary and
  that has its own five-year issue trail.

Evidence, re-verified 2026-08-20 — **six of seven SUPPORT**:
`tfp-aws#10997` (the canonical root cause: `for_each` rejects
`domain_validation_options` because it is a list-of-object, so it must be
transformed into a map first), `#8531` (CLOSED/completed, **332 👍**, 89 comments
— SAN/`domain_validation_options` ordering instability), `#27299` (**OPEN**,
27 👍 — `for_each` "known only after apply" on exactly this wiring), `#14447`
(64 👍, 35 comments), `#7918` (50 👍 — pre-`for_each` index-based wiring failing
for multi-SAN/wildcard), `#5237` (19 comments — count/lookup wiring producing
`DomainLabelEmpty`). **`#27386` DOES NOT SUPPORT** — it is
`aws_route53_zone_association` count/`depends_on`, unrelated; drop it from the
spec's provenance.

### (e) Arm prediction

**awscdk cheapest, terraconstructs a close second, hcl-raw a distant third —
and this is the batch's cleanest three-way separation.** awscdk writes one prop
and CloudFormation does the rest; terraconstructs writes one prop and the
*construct* does the rest (more synthesized resources, same author effort);
hcl-raw writes the certificate, the transform, the records and the validation
resource, and is exposed to three separate silent failures. Secondary
prediction: hcl-raw failures cluster on cardinality (one record for two domains),
not on syntax.

### (f) Effort / risk

- **M**. No new harness capability; one new reusable Rego helper (group plan
  resources by a referenced parent and assert cardinality), which §9 and §10 also
  want — build it here or there, once.
- terraconstructs coverage: `edge.PublicCertificate` + `edge.DnsZone` +
  `edge.RecordSet` ✅, verified by source read; cite `lib/aws/edge/certificate.js`
  in `arms.terraconstructs.reason`, and correct the graded note in the spec's
  own comments.
- Risk: a *correct* terraconstructs solution's record-to-domain mapping depends
  on `domainValidationOptions.get(index)` lining up with a zone list sorted by
  domain name — an assumption inside the library, not the agent's code. If a
  real synth shows the indices misaligned for the two-name case, the arm's own
  reference solution is affected, not the scenario design; record the finding
  either way (it would be a genuine upstream bug worth reporting).
- Watch: creating a hosted zone is a real, billable resource if this ever runs
  live. It must not — keep `live_check.enabled: false` and say why in the spec.

---

## 9. `s3-notification-authoritative-singleton`

**Cluster decision (asked for explicitly): merge one sibling, keep the other
separate.**

- **`s3-notification-clobber` MERGES here.** Same dedupe family, same evidence
  base (`tfp-aws#501` at 74 👍 heads both), same mechanism, same greenfield
  static shape. One scenario.
- **`singleton-child-resource-clobber` STAYS SEPARATE, in the brownfield
  (poisoned-workspace) queue.** Three reasons, in order of weight: (1) the
  operator graded it *"multi step or poisoned workspace"* — a form call, and this
  blueprint is greenfield single-step; (2) its evidence set is deliberately
  **cross-service** — `tfp-aws#6334` (S3 *bucket policy*), `#16791` (MSK SCRAM
  secret associations), `#39376` (HashiCorp's provider-wide
  exclusive-relationship meta-issue) — so folding it into an S3-notification
  scenario would narrow a *pattern* candidate into a single service and throw
  away exactly what makes it worth its own row; (3) the two measure different
  things and their rows may not be pooled anyway (Amendment 28 §6): this one
  measures *authoring* ("can the agent express two requirements against one
  authoritative resource?"), the clobber sibling measures *changing code the
  agent did not write* ("does the agent notice the existing authoritative
  resource already owns a sibling team's config?"). What they share is the Rego
  helper below, which is built once here and reused there.

### (a) Identity

| field | value |
|---|---|
| `id` | `s3-notification-authoritative-singleton` |
| `workspace_id` | `media-ingest` |
| `title` (agent-visible) | `Media bucket that triggers processing on upload and audits deletes` |
| `difficulty` | 2 |
| `services` | `[s3, lambda, sns, iam]` |

**Leak test.** The `id` names the diagnosis (*authoritative singleton*);
`media-ingest` and the title name the two requirements the ticket states.
**Deny-list run:** `media-ingest` clean; title clean (`triggers`, `audits`,
`uploads`, `deletes` are on neither list).

### (b) Prompt

```
The media bucket needs two things wired up.

Product: when a file is uploaded, the ingest function must run so the asset
is transcoded.

Compliance: when any object is deleted, the audit topic must receive a
notification so deletions show up in the quarterly review.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- Presenting the two requirements as two stakeholders' asks is what makes the
  two-call-site authoring shape natural rather than telegraphed — the graded
  data asks for exactly this framing ("prompt framing that presents the two
  requirements as separate tickets"). It is in-world, not oracle-defensive.
- Shapes that satisfy the ticket: one `aws_s3_bucket_notification` with both a
  `lambda_function` and a `topic` block (the only correct TF shape); on the
  typed arms, two `addEventNotification`/`addObjectRemovedNotification` calls.
  **The oracle grades the outcome — both event types wired, and at most one
  authoritative notification resource per bucket** — never the number of call
  sites.
- The SNS topic policy is part of "the topic must receive a notification": S3
  cannot publish without it. Graded as a functional fact, not as a style rule.

### (c) Oracle tier plan — **static only**

Tier-0:

| name | check |
|---|---|
| `object-created-notification-targets-a-function` | notification config contains an `s3:ObjectCreated:*`/`:Put` entry with a lambda target (`contains`) |
| `object-removed-notification-targets-the-topic` | notification config contains an `s3:ObjectRemoved:*` entry with an SNS target |
| `exactly-one-notification-resource-per-bucket` | **TF arms:** count of `aws_s3_bucket_notification` resources whose `bucket` expression references this bucket → **1**. This is the new reusable helper: *cardinality of an authoritative child resource per parent* |
| `lambda-permission-principal-is-s3` | permission with `principal == "s3.amazonaws.com"` exists |

Tier-1 (Rego + cfn-guard):
1. **`authoritative-child-is-unique-per-parent`** — the general form of the
   tier-0 count, written so it can be lifted verbatim for `aws_s3_bucket_acl`,
   `aws_s3_bucket_policy` and the brownfield clobber sibling.
2. **`sns-topic-policy-allows-s3-publish`** — a topic policy statement granting
   `SNS:Publish` to `s3.amazonaws.com` scoped by `aws:SourceArn` to this bucket
   (graph edge on the TF arms; direct on CFN).
3. **`lambda-permission-scoped-to-this-bucket`** — the existing
   `s3-lambda-log-retention` rule, reused verbatim.

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `two-notification-resources-for-one-bucket` | graph-dependency | declares one `aws_s3_bucket_notification` per requirement — **the plausible-wrong solution**: it is the natural shape when two tickets arrive separately, it plans and applies green, and the two resources overwrite each other on every apply so exactly one requirement is ever live | 0 / — (`applies_to: [hcl_raw]`) |
| `sns-publish-not-permitted` | graph-dependency | wires the topic notification with no topic policy — S3 silently drops the event | 0 / 0 (all arms; CDK's `SnsDestination` adds the policy, so this fixture needs an escape hatch there — expected, and `applies_to` may drop awscdk if the mistake proves contrived) |
| `only-one-of-the-two-events-wired` | nested-attribute | wires uploads only | 0 / 0 |

**Static vs live:** static. The clobber is visible in the plan as a resource
count; observing it live would need two consumers, an SQS receive and a long
eventual-consistency wait, for no additional discrimination.

### (d) Trap mechanics + evidence

The S3 API has exactly one notification configuration per bucket and no
create/update distinction — `PutBucketNotificationConfiguration` replaces the
whole document — so Terraform's `aws_s3_bucket_notification` is authoritative
per bucket by necessity, not by design choice. Two of them fight forever. The
provider documents it
(`website/docs/r/s3_bucket_notification.html.markdown`: the API *"is atomic — it
replaces the bucket's entire notification configuration on every call. Only one
`aws_s3_bucket_notification` resource can manage a bucket; declaring more than
one causes a perpetual diff"*), and both typed arms hide it:

- `aws-cdk-lib` — `aws-s3/lib/bucket.ts:1028-1034` lazily creates
  `BucketNotifications` **once** per bucket, and
  `notifications-resource/notifications-resource.ts:133-165` `createResourceOnce()`
  guards the single `Custom::S3BucketNotifications` with `if (!this.resource)`.
- `terraconstructs` — `lib/aws/storage/bucket-notifications.js:47-48`
  `addNotification()` calls `createResourceOnce()` and accumulates lambda/queue/
  topic targets into one `aws_s3_bucket_notification`.

So an agent calling `addEventNotification` twice gets one authoritative resource
on both typed arms and cannot commit the mistake; an agent writing HCL from two
tickets very naturally can.

Evidence, re-verified 2026-08-20 — **six of seven SUPPORT, one partially**:
`tfp-aws#501` (CLOSED/completed, **74 👍**, 45 comments — the canonical thread),
`#1715` (the best root cause: apparentlymart explains the S3 API has one
notification configuration and Terraform cannot tell it is replacing one),
`#23951` (*"Multiple aws_s3_bucket_notification resources flipflop and overwrite
each other"* — the mechanism in the title), `#5299` (maintainer: "all the
notifications must be bundled together in a single resource configuration"),
`#22147` (*"can be silently overwritten"*, consolidated into the provider-wide
plan-time-error request `#14394`), `#48509` (**OPEN**, 2026-06-22 — asks upstream
AWS for per-rule/If-Match writes, i.e. the root cause is still live today).
`#38402` **PARTIALLY** — closed not-planned with a bot-only thread; keep it out
of the spec's provenance.

### (e) Arm prediction

**Both typed arms green; hcl-raw carries the risk, and the failure is silent.**
Unlike §1 (loud, tier-0-everywhere, token-cost probe), this is a genuine
*silent-failure* probe: the broken shape passes plan, passes apply, and loses
half the requirement at runtime. Its rows belong in the silent-catch statistics
that §1's explicitly do not. Secondary prediction: hcl-raw agents that write
both requirements in one pass mostly get it right; the failure correlates with
authoring the two requirements at different points in the trajectory — which the
two-stakeholder prompt framing makes likely without telegraphing anything.

### (f) Effort / risk

- **M**, mostly because of the SNS half. Builds the reusable cardinality helper.
- terraconstructs coverage: `storage.Bucket` + `bucket-notifications` with
  `LAMBDA` and `SNS`/`TOPIC` destination types ✅ (`lib/aws/storage/
  notification-targets/`), `notify.Topic` ✅. Carry over
  `s3-lambda-log-retention`'s known quirk: this library version's
  `addNotification` only registers a target inside its `for (const filter of
  filters)` loop, so a call with **zero** filters registers nothing — the
  reference solution must pass one all-optional-fields filter object `{}`.
- Risk: the awscdk arm's `SnsDestination` adds the topic policy automatically,
  so the second catch may be unreproducible there without contrivance. Decide at
  fixture-authoring time whether to drop awscdk from that catch's `applies_to`
  (the honest option) rather than inventing an escape-hatch fixture.

---

## 10. `s3-notification-custom-resource-tax`

The "static shape" entry. **Deliberate thesis-can-lose scenario** — see operator
question Q7 before authoring.

### (a) Identity

| field | value |
|---|---|
| `id` | `s3-notification-custom-resource-tax` |
| `workspace_id` | `claims-intake` |
| `title` (agent-visible) | `Claims intake bucket that notifies the processor, with no extra compute in the stack` |
| `difficulty` | 2 |
| `services` | `[s3, lambda, iam]` |

**Leak test.** The `id` names the measurement (*custom-resource tax*);
`claims-intake` and the title name the ticket, including the constraint the
prompt states outright.
**Deny-list run:** `claims-intake` clean; title clean. ("compute" and "extra"
are on neither list; nothing here names a fix or a later step.)

### (b) Prompt

```
Claims documents land in an S3 bucket and must be handed to the claims
processor function as they arrive.

Platform constraint for this account: a stack may only contain the compute
it is being deployed to run. The claims processor is the only function this
stack is allowed to create — no helpers, no deployment-time functions, no
functions belonging to the tooling.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- The constraint sentence is an *outcome* constraint (what may exist in the
  deployed stack), not an implementation-shape constraint — it never says which
  API to use, and all three arms have at least one way to satisfy it. It is
  nonetheless the sentence that forces the awscdk arm off its own L2, so it is
  called out for operator approval (Q7).
- Shapes that satisfy it: on the TF arms, the ordinary
  `aws_s3_bucket_notification` (zero extra functions, idiomatic). On awscdk, the
  L1 escape hatch — setting `NotificationConfiguration` on the underlying
  `CfnBucket` — because the L2 `addEventNotification` provisions the
  `Custom::S3BucketNotifications` handler function. **All are accepted**; the
  oracle counts functions and grades the wiring, never the API used.
- A real alternative worth accepting explicitly: EventBridge notifications
  (`EventBridgeConfiguration` + a rule targeting the function) also satisfy the
  ticket with no extra compute on any arm. The oracle **accepts it** — it wires
  uploads to the processor, which is the requirement. Say so in `oracle.intent`
  so a reviewer does not read the assert set as S3-notification-only.

### (c) Oracle tier plan — **static only**

Tier-0:

| name | check |
|---|---|
| `upload-events-reach-the-processor` | (union) an S3 notification configuration targeting the function, **or** an EventBridge rule whose target references it |
| `exactly-one-lambda-function` | count of `AWS::Lambda::Function` / `aws_lambda_function` in the artifact → **1**. This is the "no extra resources of type X" primitive the graded data asks for, and it reads identically on both oracle languages |
| `no-deployment-time-custom-resource` | awscdk: no `Custom::*` resource → `not_exists`; TF arms: vacuous (recorded as `N/A` via `applies_to`, not faked) |
| `invoke-permission-scoped` | as in §9 (tier 1) |

**Catches** (2 + the measurement):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `stack-ships-a-deployment-time-function` | anti-L2 | the *idiomatic* awscdk solution: `bucket.addEventNotification(EventType.OBJECT_CREATED, new s3n.LambdaDestination(fn))`, which synthesizes the stack-wide `BucketNotificationsHandler` singleton **plus** its role — two extra resources and one extra function the ticket forbids | 0 / — (`applies_to: [awscdk]`) |
| `notification-targets-the-wrong-function` | graph-dependency | wires the notification to a function other than the processor | 1 / 1 |

**The measurement, recorded but not graded.** Alongside the reward, record for
each arm: total resource count, number of IAM roles, number of Lambda functions,
and presence of any `Custom::*` / provider-side deployment helper. That is the
"tax" this scenario exists to quantify, and it is a *reported artifact-shape
number*, not a pass/fail — pass/fail is the two catches above. If the harness
has no home for such a number today, the honest interim is a line in the spec's
`oracle.intent` plus the numbers recorded in `DECISIONS.md` when the scenario
first runs.

### (d) Trap mechanics + evidence

CloudFormation has **no** resource for S3 bucket notifications
(`aws-cloudformation/cloudformation-coverage-roadmap#79`, **OPEN since
2019-08-01**, **461 👍**, 52 comments — re-read 2026-08-20; the graded figure of
479 is stale but the same order, and it remains one of the highest-signal open
items on that tracker). `aws-cdk-lib` therefore ships a custom resource:
`aws-s3/lib/notifications-resource/notifications-resource.ts` defines
`class BucketNotifications` creating a `Custom::S3BucketNotifications`, backed by
a stack-wide singleton handler function
(`notifications-resource-handler.ts:33-45`, logical id
`BucketNotificationsHandler050a0587b7544547bf325f094a3db834`) plus its execution
role. That is the tax: **one extra function and one extra role in every stack
that wires an S3 notification through the L2**, for an intent that costs the
Terraform-shaped arms one resource with first-class provider support.

The other half of the graded candidate — "the CDK Lambda eats your existing
notification config" — was re-verified and has **moved on**: the handler now
distinguishes `managed=true` (CDK-owned bucket: whole-config PUT) from
`managed=false` (imported bucket: fetches existing config, computes which
entries are external via a stack-id-prefixed synthetic `Id`, and merges). So the
current, accurate claim is *"a fragile merge with a live bug trail"*, not
*"unconditional clobber"* — and that half belongs to the **unowned-bucket live
candidate**, not to this static one. Supporting bugs, all re-verified:
`aws-cdk#29004` (CLOSED/completed — `cdk destroy` removed **all** notifications
from an existing bucket), `#28915` (CLOSED/completed, 25 comments — the handler
fails with *"Configuration is ambiguously defined"* when PUTting the merged
config), `#35352` (**OPEN**, 2025-08-28 → 2026-07-08 — `NoSuchBucket` during
stack deletion because the custom resource runs after the bucket is gone),
`#2004` (CLOSED/completed, 90 👍, 79 comments — the unowned-bucket support
request itself). `#16811` **PARTIALLY** (handler retry robustness — cite it for
"the tax has operational weight", not for clobber).

### (e) Arm prediction

**hcl-raw and terraconstructs green idiomatically; awscdk fails the constraint
with its own recommended API and must pay an escape-hatch tax to pass.** This is
the batch's deliberate **thesis-can-lose** entry and the honest replacement for
the excluded `ssm-securestring` candidate's measurement ("where in the pipeline
does each arm's cost land") — with the difference that it is entirely static and
costs no live budget. Secondary prediction: awscdk agents that discover the
constraint late will burn a full authoring cycle switching from the L2 to the L1,
which is visible in tokens-to-green rather than in reward.

### (f) Effort / risk

- **M**. Reuses §9's cardinality helper and adds the count-of-type primitive.
- terraconstructs coverage: as §9 ✅ — and note the arm's own notification path
  synthesizes a **genuine `aws_s3_bucket_notification`**, not a custom resource
  (already recorded in `specs/s3-lambda-log-retention.yaml`'s
  `arms.terraconstructs.reason`); this scenario is the one that measures what
  that difference is worth.
- Risk: **Q7 is a real design risk, not a formality.** If the operator judges
  the guardrail sentence to be a scenario built to make one arm lose, the
  fallback is to drop this to a shape-metric-only variant of §9 (same task, no
  constraint sentence, no anti-L2 catch, tax recorded as a number) — which keeps
  the measurement and loses the falsifiability value.
- Do **not** let this scenario drift toward the unowned-bucket variant: that
  needs a pre-provisioned out-of-band fixture and a before/after
  `GetBucketNotificationConfiguration` snapshot, neither of which the harness
  has. It is a different candidate, already graded into the live bucket.

---

## 11. `lambda-log-group-ownership-and-retention`

Graded as `auto-created-log-groups-orphan-collide-and-never-expire`. Operator
comment: *"Terraconstructs might actually handle this better today (it did not
port the RETAIN policy — in TF this would be prevent_destroy and errors on
destroy of those resources). This does remain a CDK Pain."* **The arm prediction
below makes that explicit and pre-registers it.**

### (a) Identity

| field | value |
|---|---|
| `id` | `lambda-log-group-ownership-and-retention` |
| `workspace_id` | `event-processor` |
| `title` (agent-visible) | `Event processor whose logs are kept for 30 days and cleaned up with the stack` |
| `difficulty` | 2 |
| `services` | `[lambda, logs, iam]` |

**Leak test.** The `id` names the diagnosis (*ownership* — that the log group is
not owned by the configuration unless you make it so). `event-processor` names
the workload; the title states both halves of the ticket.
**Deny-list run:** `event-processor` clean. Title — checked word by word:
"cleaned up with the stack" matches no mechanism pattern (`\bdrift`, `\bstale`,
`\bre[ _-]?creat`, `already exists` — none), and no foreshadow pattern
(`re-deploy`, `next step`, …). Clean. (An earlier draft said *"logs that do not
outlive the stack"*, which is also clean but reads as a warning; the current form
states the requirement.)

### (b) Prompt

```
Add the event-processor Lambda to the platform stack.

Its logs must be retained for 30 days — not indefinitely, we are paying for
that today — and when this stack is torn down, nothing of it may be left
behind in the account.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- "when this stack is torn down, nothing may be left behind" is the requirement
  that makes ownership matter; it is stated as an outcome. Note this is a
  stepless task, so foreshadow-class vocabulary is permitted in its own prompt
  (`SCHEMA.md` §0.1 scope table) — but the phrasing above avoids it anyway.
- Shapes that satisfy it on the awscdk arm: (i) `new logs.LogGroup(...)` with
  `logGroupName: '/aws/lambda/<name>'`, `retention: THIRTY_DAYS`,
  `removalPolicy: DESTROY`, passed as the function's `logGroup` prop; (ii)
  enabling `@aws-cdk/aws-lambda:useCdkManagedLogGroup` in `cdk.json` and setting
  retention. **(ii) must be verified at authoring time before it is accepted** —
  it is a legitimate agent move (the file is in the workspace and is not
  named as off-limits by the ownership note), and if the flag's managed group
  defaults to `RemovalPolicy.RETAIN` it satisfies half the ticket only. Decide
  and record; do not let the oracle silently reject a working solution.
- The deprecated `logRetention` prop is **rejected**: it provisions a
  `LogRetention` custom resource whose `removalPolicy` defaults to `RETAIN`, so
  it leaves both an orphaned group and an extra function behind.
- On the TF arms the only shape is an explicit `aws_cloudwatch_log_group` named
  `/aws/lambda/<function name>`; the oracle accepts the name built by
  interpolation or from a shared local/variable, and grades the *name*, not how
  it was composed.

### (c) Oracle tier plan — **static only**

Tier-0:

| name | check |
|---|---|
| `log-group-exists-with-30-day-retention` | `AWS::Logs::LogGroup.Properties.RetentionInDays` / `aws_cloudwatch_log_group.values.retention_in_days` → `eq` `30` |
| `log-group-name-matches-the-function` | name `regex` `^/aws/lambda/` (tier 1 on the TF arms where the name interpolates the function name — graph edge) |
| `log-group-is-deleted-with-the-stack` | **awscdk:** the `AWS::Logs::LogGroup`'s `DeletionPolicy`/`UpdateReplacePolicy` → `absent_or_eq` `"Delete"`; **TF arms:** no `lifecycle { prevent_destroy = true }` on the group (`not_exists`) |
| `no-log-retention-custom-resource` | awscdk: no `Custom::LogRetention` → `not_exists`; `applies_to: [awscdk]` |

`DeletionPolicy` is a template-level key, always static on the CFN side, so
this is a sound tier-0 check there (§4.2.1 does not bite).

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `log-group-left-implicit` | graph-dependency | declares no log group at all — **the plausible-wrong solution on every arm**: the function works, the logs appear, the group is created by the Lambda service outside the configuration, never expires, and survives teardown | 0 / 0 |
| `retention-via-deprecated-log-retention-prop` | anti-L2 | uses `logRetention: RetentionDays.ONE_MONTH` — typed, autocompleted, and it ships a custom-resource function whose default removal policy is `RETAIN` | 0 / — (`applies_to: [awscdk]`) |
| `log-group-retained-on-delete` | nested-attribute | creates the group correctly but leaves `RemovalPolicy.RETAIN` / adds `prevent_destroy` | 0 / 0 |

**Static vs live:** static — every fact above is a template/plan key.
**With §12's `verifier.teardown` in place this scenario gains a live tier for
free** (does the group actually disappear?), which is the honest end state; it
is not needed for the scenario to be gradeable.

### (d) Trap mechanics + evidence

AWS Lambda creates `/aws/lambda/<function>` implicitly on first invoke. Nothing
in CloudFormation or Terraform owns it unless you declare it, so by default it
(1) never expires, (2) survives stack deletion, and (3) collides on the next
deploy that tries to create it. Verified in `aws-cdk-lib` 2.263.0:

- `aws-lambda/lib/function.ts:597` — `logGroup?: logs.ILogGroupRef` exists;
  when it is unset (and `logRetention` unset, and the feature flag off) CDK
  synthesizes **no** `AWS::Logs::LogGroup` at all.
- `:471` — `logRetention` is `@deprecated use 'logGroup' instead`, implemented
  at `:1196-1200` as a `logs.LogRetention` custom resource;
  `aws-logs/lib/log-retention.ts:46-48` — `removalPolicy` `@default
  RemovalPolicy.RETAIN`.
- `cx-api/lib/features.ts:150` — `USE_CDK_MANAGED_LAMBDA_LOGGROUP =
  '@aws-cdk/aws-lambda:useCdkManagedLogGroup'`, consumed at `function.ts:1205`.
  **This arm's `arms/awscdk/environment/workspace/cdk.json` does not set it**
  (checked), so the default path is the implicit-group path — which is what the
  scenario measures, and which an agent may legitimately change (see (b)).

`terraconstructs` 0.2.13 is structurally different and better here, exactly as
the operator suspected: `lib/aws/compute/function.js:424-428` **always** creates
an `aws_cloudwatch_log_group` for the function, with
`retentionInDays: logRetentionInDays` defaulting to `RetentionDays.ONE_WEEK`
(`:349`), wires it through `loggingConfig` (`:478`) and adds `dependsOn`
(`:483`). There is no RETAIN/`prevent_destroy` anywhere in that path — so the
group is owned, expires by default, and is destroyed with the stack.

**Evidence status: all three graded URLs are wrong.** `aws-cdk#22307`, `#24656`
and `#37797` are every one of them about auto-created
`AWS::Logs::ResourcePolicy` objects (the account limit of 10, and drift
false-positives) — a different CDK footgun. Replacements, found and verified
2026-08-20:

| issue | state | signal | why it supports |
|---|---|---|---|
| `aws-cdk#11549` *"(logs): delete associated log group when stack is deleted"* | CLOSED/completed 2023-12-19 | **55 👍**, 19 comments | "those log groups linger after the stack has been deleted" — the orphan claim verbatim; closed by adding a `removalPolicy` to `LogRetention`, **not** by managing the group by default |
| `aws-cdk#24815` *"retention on S3 autoDeleteObjects lambda log group is Never expire"* | CLOSED/completed 2025-08-02 | 31 👍 | never-expire + accumulate-forever, for CDK's own internal lambda |
| `aws-cdk#21804` *"(lambda): Add property for log removal policy of Lambda function log groups"* | **OPEN** | 13 👍 | "we still cannot remove a log group for a Lambda function automatically when we delete a stack" |
| `aws-cdk#26553` *"CustomResourceProvider should destroy log group when stack deleted"* | **OPEN**, last comment 2026-01-13 | 7 👍, 9 comments | the gap is still live in 2026 for CDK-internal lambdas |
| `aws-cdk#33025` *"[aws-ec2] Accidental Log Group creation when creating a VPC"* | **OPEN** | — | "retention set to never expire… when the stack is deleted, the Log Group remains" |

Also relevant to the spec's framing: `aws-cdk#35003` (*"migrate from
logRetention to logGroup"*, closed 2026-05-29) documents the `logGroup` prop as
the recommended path — i.e. the modern fix exists and the *default* is still the
implicit group.

### (e) Arm prediction — **explicitly pre-registered, per the operator's note**

**terraconstructs is predicted to WIN this scenario outright**, and it is the
first entry in the corpus where the thesis's own control arm is predicted to
beat both primaries:

1. **terraconstructs** — the log group is created by the construct by default;
   the agent's only work is changing a retention value from the default week to
   30 days. No orphan risk (no RETAIN was ported; the resource is destroyed with
   the stack).
2. **hcl-raw** — must know that the group is implicit, must name it
   `/aws/lambda/<fn>` exactly, must set retention. More work than
   terraconstructs, but the language offers no misleading shortcut.
3. **awscdk** — the most work *and* the most attractive wrong answer: the
   deprecated-but-still-typed `logRetention` prop reads as the obvious API,
   passes `tsc`, and produces both an orphaned group and an extra function.

If a real run puts awscdk ahead of terraconstructs here, the "L2 defaults are
the product" story takes a real hit on this family — which is precisely why the
prediction is registered before authoring.

### (f) Effort / risk

- **S**. No new machinery; four tier-0 asserts and one graph edge.
- terraconstructs coverage: `compute.LambdaFunction` + `cloudwatch.LogGroup` ✅
  (both already exercised by `s3-lambda-log-retention`).
- Risk 1: **do not let this become the excluded candidate.**
  `lambda-log-group-cdk-json-fork` was graded **out**. Keeping the feature flag
  as an accepted-but-verified solution shape (b) is fine; making the flag *the
  subject* is not.
- Risk 2: overlap with `s3-lambda-log-retention` (both touch Lambda log
  retention). They are distinguishable — that one is a typed-enum value trap
  ("10 days is not a valid retention"), this one is resource *ownership* — but
  the spec must say so explicitly, and 30 is chosen precisely because it **is**
  a valid CloudWatch retention value, so the enum trap cannot fire here.

---

## 12. `ecr-repo-destroy-force-delete` — the batch's only harness-feature dependency

### (a) Identity

| field | value |
|---|---|
| `id` | `ecr-repo-destroy-force-delete` |
| `workspace_id` | `service-image-registry` |
| `title` (agent-visible) | `Container image registry for the service, rebuilt with each environment` |
| `difficulty` | 2 |
| `services` | `[ecr, iam]` |

**Leak test.** The `id` names the fix (*force delete*) — the single argument the
agent must find. `service-image-registry` and the title name the deliverable and
the environment's lifecycle expectation.
**Deny-list run:** `service-image-registry` clean; title — "rebuilt with each
environment" checked against `\bre[ _-]?creat(e|es|ed|ing|ion)\b` (no match:
"rebuilt" is not "recreate"), `\breplac…` (no), `iteration` (no). Clean.
Add `agent_deny_vocab: ["force_delete", "forceDelete", "emptyOnDelete",
"RepositoryNotEmpty"]`.

### (b) Prompt

```
The service needs its own ECR repository. Images are scanned on push, and
only the last 10 images are kept.

These environments are created and destroyed on a nightly cycle by the
platform pipeline, which has no manual steps: removing this configuration
has to leave the account clean, with the repository and its images gone.
```

Language lines: the standard trio.
**Seeded files:** none.

**Oracle must tolerate / defend.**
- "Images are scanned on push / only the last 10 kept" are ordinary registry
  requirements and give the scenario a real body beyond the one trap argument.
- The teardown sentence is an outcome requirement stated the way a platform
  ticket states it. It does not name `force_delete`, `emptyOnDelete`, or a
  removal policy.
- Shapes accepted: hcl-raw `force_delete = true`; awscdk `emptyOnDelete: true`
  **plus** `removalPolicy: DESTROY` (the construct throws without it);
  terraconstructs `emptyOnDelete: true` (which maps onto the provider's
  `forceDelete`). The deprecated awscdk `autoDeleteImages` is **rejected** — it
  goes through a custom-resource path rather than the native property.

### (c) Oracle tier plan — static asserts, **plus a new `verifier.teardown` tier**

Tier-0 (static, cheap, and *not* sufficient):

| name | check |
|---|---|
| `repository-exists-with-scan-on-push` | `image_scanning_configuration.scan_on_push` / `ImageScanningConfiguration.ScanOnPush` → `eq true` |
| `lifecycle-policy-keeps-ten` | a lifecycle policy whose rule count-number is 10 (`\|fromjson` on the TF arm's `policy` string) |
| `repository-is-emptied-on-delete` | `values.force_delete` → `eq true` (TF arms); `Properties.EmptyOnDelete` → `eq true` and `DeletionPolicy` → `eq "Delete"` (awscdk) |

The static tier *can* see the argument — so why the new tier? Because the
argument is only a **proxy** for the requirement, and grading the proxy is
exactly the mistake `s3-lambda-log-retention`'s header warns about. The
requirement is "teardown leaves the account clean", and the only honest oracle
for it is running the agent's own teardown. It also generalizes: §11's orphan
half and §7's residue half both become gradeable the moment it exists.

#### The minimal oracle extension: `verifier.teardown` (new `SCHEMA.md` §5.2)

Deliberately a near-clone of §5.1 `verifier.idempotence`, reusing its machinery
rather than inventing a second pattern:

```yaml
verifier:
  live_check: { enabled: true, hand_authored: true, gating: true, … }
  teardown:
    enabled: true      # default false
    gating: true       # default false; requires enabled
```

1. **`enabled: true` requires `live_check.enabled: true`** (a new
   `Spec._teardown_requires_live_check`, mirroring
   `_idempotence_requires_live_check`): with no apply there is nothing to
   destroy, and an offline "destroy" of an empty working directory is vacuous.
2. **Per-arm commands are injected unconditionally by the generator**
   (`gen.py::TEARDOWN_COMMAND`), never read from a spec key — the same
   cannot-be-forgotten discipline as `IDEMPOTENCE_COMMAND`:

   | arm | command | clean | failed |
   |---|---|---|---|
   | `hcl_raw` | `terraform destroy -input=false -auto-approve` | exit 0 | non-zero |
   | `terraconstructs` | `npx cdktn synth`, state re-probe, then the same destroy inside `cdktf.out/stacks/<workspace_id>/` | exit 0 | non-zero |
   | `awscdk` | `npx cdk destroy --force ScenarioStack` | exit 0 | non-zero |

3. **Three outcomes**, written to `/logs/verifier/teardown-result.json` plus raw
   output in `/logs/verifier/teardown.log` whether gating or not: `clean` /
   `destroy_failed` / `not_verifiable`.
4. **The never-deployed case is detected per arm by the existing mechanisms**:
   the TF arms reuse `IDEMPOTENCE_STATE_PROBE` (no local state ⇒
   `not_verifiable`, no destroy attempted) and the terraconstructs post-synth
   state re-probe with its reserved rc `9`; the awscdk arm reuses the
   completion-marker approach (`cdk destroy` printing its own completion line),
   because it keeps no local state. **Offline, the tier is skipped with a
   reason, never fake-passed** — the same guarantee, in the same words, as §5.1.
5. **Ordering is load-bearing:** the teardown block runs **after** `live_check`
   and **after** the idempotence block. Destroying first would invalidate both.
   On a multi-step spec it rides the **final** step only.
6. **`gating: true` is fail-closed and AND-composed**: reward is 1.0 iff static
   tiers say 1.0 AND `live_check.outcome == "pass"` AND (if enabled)
   idempotence is `converged` AND teardown is `clean`.
7. **Emission is generation-conditional** (like idempotence, unlike
   `live_check`'s dead runtime branch), so no existing task's `tests/test.sh`
   moves a byte.
8. **It does not replace the framework reset.** aws-bench's own
   post-mutating-trial reset is still what guarantees the account returns to
   baseline (Amendments 17/18, re-proven in
   `docs/teardown-experiment-results.md`). This tier *grades* the agent's
   teardown; a `destroy_failed` verdict leaks nothing, because reset sweeps
   afterwards regardless. Say this in the schema text — it is the sentence that
   keeps someone from later "improving" the tier into a cleanup mechanism.

**The fixture problem, solved without new harness surface.** The repository must
actually contain an image at destroy time, and there is no docker in the agent
image. The hand-authored `live_check.py` (already an allowed, hand-authored file
under §5) pushes one **inside its own verification**: `ecr:GetAuthorizationToken`
→ `InitiateLayerUpload` / `UploadLayerPart` / `CompleteLayerUpload` with a
~32-byte blob → `PutImage` with a minimal manifest — all plain AWS API calls, no
docker, no new fixture concept. It then asserts what the ticket asked for
(scan-on-push configured, lifecycle policy present, image accepted). The
teardown tier that runs next is therefore destroying a **non-empty** repository,
which is the entire point.

**Catches** (3):

| name | taxonomy | broken fixture | predicted tier |
|---|---|---|---|
| `repository-not-emptied-on-delete` | typed-value-trap | omits `force_delete` / `emptyOnDelete` — **the plausible-wrong solution**: everything applies green, the live check passes, and `terraform destroy` fails with *"The repository … cannot be deleted because it still contains images"*, wedging the nightly pipeline | **teardown** / — |
| `auto-delete-images-custom-resource` | anti-L2 | uses awscdk's deprecated `autoDeleteImages`, which satisfies teardown via an extra custom-resource function | 0 / — (`applies_to: [awscdk]`) |
| `lifecycle-policy-keeps-wrong-count` | nested-attribute | keeps 100 images instead of 10 | 0 / 0 |

The first catch is the reason the tier exists; like §5's live catch it must
carry the mechanically-earned marker discipline if it is ever run offline.

### (d) Trap mechanics + evidence

`aws_ecr_repository` refuses to delete a repository containing images unless
`force_delete = true` (`website/docs/r/ecr_repository.html.markdown`: *"If
`true`, will delete the repository even if it contains images. Defaults to
`false`."*). CloudFormation's `AWS::ECR::Repository` gained a native
`EmptyOnDelete` property, and `aws-cdk-lib` renders it directly:
`aws-ecr/lib/repository.ts:631` (`emptyOnDelete?: boolean`), rendered at `:861`
inside `new CfnRepository(...)`; `:624` marks `autoDeleteImages` deprecated and
`:875` routes it through a custom resource instead; `:871-872` throws *"Cannot
use 'emptyOnDelete' property on a repository without setting removal policy to
'DESTROY'"*; default removal policy is `Retain` (`:587-589`).
`terraconstructs` 0.2.13 maps the CDK-shaped prop onto the provider argument —
`lib/aws/storage/ecr-repository.js:391` `forceDelete: props.emptyOnDelete` —
with the same `autoDeleteImages` guard at `:406-412` (and an explicit
"deprecated and not implemented" warning).

Evidence, re-verified 2026-08-20 — **both SUPPORT**:
`tfp-aws#33523` (*"cannot delete non-empty aws_ecr_repository even using
force_delete"*, CLOSED/completed, 2023-09-19 → 2026-07-25, **61 👍**, 22
comments — confirms the base behaviour, and that `force_delete` itself was buggy
for a period) and `#9911` (CLOSED/completed — the original request that made the
force-delete behaviour explicit and opt-in rather than always-on).

### (e) Arm prediction

**Both typed arms green; hcl-raw is where the teardown fails.** The typed arms
surface one boolean prop with a name that reads like the requirement
(`emptyOnDelete`), and awscdk goes further by *throwing at synth* if the removal
policy contradicts it — the type system enforcing a cross-property invariant,
which is the strongest form of the thesis in this batch. hcl-raw's
`force_delete` is a bare, easily-unknown boolean that nothing prompts for.
Secondary prediction: this is the scenario most likely to produce a **reward-1.0
static / failed-teardown** split, i.e. the clearest demonstration that the
static tiers alone were mis-measuring the task.

### (f) Effort / risk

- **M-L**, dominated by the harness feature. The spec itself is small.
- **D3 is the blocker** (`verifier.teardown`). Estimated shape: one new schema
  section, one pydantic validator, one `TEARDOWN_COMMAND` map, one emitted block
  in `build_test_sh`, one result file — all closely modelled on the idempotence
  tier shipped 2026-08-20, and reusing its probe/marker maps rather than adding
  new ones.
- terraconstructs coverage: `storage.Repository` ✅
  (`lib/aws/storage/ecr-repository.js`) with `emptyOnDelete` present — verified.
- Risk 1: `cdk destroy --force` behaviour under the arm's exact pin has **not**
  been measured (the idempotence tier's own `cdk diff` measurement had to be
  done by hand for exactly this reason). Measure the exit code and the printed
  completion line before believing them, and record the transcript in the
  amendment.
- Risk 2: the live tier plus a teardown makes this the longest-running scenario
  in the batch. Budget it against `MAX_ITERS`/`MAX_TOKENS` deliberately; the
  agent's own work is small, but the harness phases are not.
- Risk 3: whichever amendment introduces `verifier.teardown` is **DRAFT until
  its first live run**, exactly as Amendments 26/27/28 are — no teardown-graded
  row may be published before that.

---

## Appendix — agent-visible identity sweep (all twelve)

Every proposed `workspace_id` and `title`, run against
`AGENT_MECHANISM_DENY_PATTERNS` + `AGENT_FORESHADOW_DENY_PATTERNS`. No entry
matches any pattern; the column records the one that came closest, because a
near-miss is what a future edit will turn into a hit.

| § | `workspace_id` | nearest pattern considered | verdict |
|---|---|---|---|
| 1 | `document-archive` | `\blifecycle\b` (rejected an earlier title mentioning lifecycle rules) | clean |
| 2 | `batch-service-roles` | — | clean |
| 3 | `worker-fleet` | — | clean |
| 4 | `release-artifact-store` | `\breplacements?\b` (does not match "release") | clean |
| 5 | `orders-http-api` | — | clean |
| 6 | `orders-table` | — | clean |
| 7 | `webhook-endpoint` | — | clean |
| 8 | `storefront-certificate` | `\bsubsequent\b` / `\bnext[ _-]?step\b` in the title's "next quarter" phrasing — no match | clean |
| 9 | `media-ingest` | — | clean |
| 10 | `claims-intake` | — | clean |
| 11 | `event-processor` | `\bstale\b`, `\bdrift` in the title's teardown clause — no match | clean |
| 12 | `service-image-registry` | `\bre[ _-]?creat` vs "rebuilt" — no match | clean |

Three specs additionally declare `agent_deny_vocab` (§4, §12, and §5 should
consider `429`/`burst limit of 0`): the scenario-local vocabulary that would
give the trap away, declared in the same file as the trap so both are reviewed
together.
