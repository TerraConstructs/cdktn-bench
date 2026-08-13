# Scenario proposal: `iam-deploy-role` — author and validate a least-privilege deployment role

> **NOT PURSUED (2026-08-13).** The `iam-e2e-role` scenario was dropped — spec, tasks, oracles, and fixtures removed — per operator decision. Reason: it centered on the *deployer/CI* principal's policy, which the evidence below shows **no construct library derives** (grantXxx only derives the *workload* principal). The scenario therefore measured the one place abstractions don't help. This document is retained as research record: the ordered defect list and the workload-vs-deployer finding feed the replacement direction — a **cross-service workload-grant** scenario (e.g. `bucket.grantRead(fn)` deriving the exact IAM identity policy + resource policy, vs hand-written `aws_iam_role_policy` + bucket policy in HCL), where the L2 advantage genuinely holds. See DECISIONS.md Amendment 21.

---


Status: **proposal**. Nothing here is generated, deployed, or wired in. No spec file, task dir, oracle, or `QARolesStack` change accompanies it. Adoption requires the full `docs/adding-scenarios.md` procedure (spec → `make gen` → oracles → reference solution + negative fixtures → `make falsifiability` / `make grading-proof`) plus a `DECISIONS.md` authorization for the account fixtures in §5.3.

§1–§4 are **evidence** mined from real Claude Code transcripts of the TerraConstructs/atlantis episode; §5–§7 are the design derived from it. Citations are `ATL L<jsonl-line>` into
`~/.claude/projects/-Users-vincentsmet-tcons-atlantis/612bf6a5-6928-4811-9b63-5f6d907a4565.jsonl` (8.0 MB, 2026-07-25 → 07-28), which contains **both** halves of the episode.

Negative check: `-Users-vincentsmet-tcons/a80d12fa*.jsonl` has 17 `AccessDenied`-family hits, but they are an unrelated `BatchSubmitJob` port (`batch:TagResource`, 2026-07-30→08-06); `grep -l atlantis` and `grep -l GetParametersByPath` return zero there. Source also read read-only: `/Users/vincentsmet/tcons/atlantis/{module,packages/atlantis/src/atlantis.ts}`, `/Users/vincentsmet/tcons/base/src/aws/**`, and the **pinned** packages `terraconstructs@0.2.13` / `aws-cdk-lib@2.263.0`.

---

## 1. Ordered defect list — the hand-authored HCL path

Subject: `atlantis-gha-e2e`, assumed from GitHub Actions via OIDC, which had to build a Packer AMI then `apply`+`destroy` the Atlantis module (`/Users/vincentsmet/tcons/atlantis/module`: ASG + launch template, EIP, two encrypted EBS volumes, security group, four SSM parameters, a Route53 record, IAM role + instance profile, and an S3 bucket behind `var.tfmigrate_enabled`). The policy was written by reading that HCL and enumerating what it "obviously" needs.

**A1 — `sts:AssumeRoleWithWebIdentity` (cycle 1, 2026-07-25 13:38).**
`Not authorized to perform sts:AssumeRoleWithWebIdentity` (ATL L1227; CloudTrail `errorCode:"AccessDenied"` ATL L1244).
*Not a permission at all — a trust-policy claim mismatch.* GitHub presented the **immutable** subject `repo:TerraConstructs@177097108/atlantis@1311914979:pull_request`, not the documented `repo:OWNER/REPO:pull_request` (ATL L1247, L1287). Nothing in the module or the docs said so; only CloudTrail's recorded claim did. → OIDC is out of scope, but the class "*the trust side fails before a single permission is evaluated*" is kept, with a local mechanism (§5.4).

**A2 — `ec2:ModifyImageAttribute` (cycle 2, 14:53).**
`UnauthorizedOperation: ...assumed-role/atlantis-gha-e2e/GitHubActions is not authorized to perform: ec2:ModifyImageAttribute on resource: .../image/ami-08b476bda1f43d491` (ATL L1306).
*A tool makes a post-create call the HCL never mentions*: "packer calls [it] to set `ami_description` on **every** build — not only when sharing an image" (ATL L1353). No amount of module-reading surfaces a Packer call.

**A3 — S3 entirely, plus four reads a `GetBucket*` wildcard misses (found by simulator, 15:06).**
"S3 was missing entirely. The e2e stack sets `tfmigrate_enabled = true`, so the module creates a `<name_prefix>-tfmigrate` bucket — and Terraform refreshes a long tail of bucket sub-resources, several of which (`GetAccelerateConfiguration`, `GetLifecycleConfiguration`, `GetReplicationConfiguration`, `GetEncryptionConfiguration`) don't match an `s3:GetBucket*` wildcard" (ATL L1358).
*Two traps compounded*: (a) the resource exists only when a module **variable** is true — it lives in `tfmigrate.tf` behind `count = var.tfmigrate_enabled ? 1 : 0`, not in `main.tf`; (b) IAM action names diverge from API/resource names, so a wildcard that *looks* covering silently is not.

**A4 — `iam:ListRoleTags` (simulator, 15:06).** "read during refresh of the instance role" (ATL L1353). *A refresh-time read* — absent from any create plan; appears only on the second apply and on destroy.

**A5 — `iam:CreateServiceLinkedRole` (simulator, 15:06).** "for autoscaling, needed on a first run in a fresh account" (ATL L1353). *Account-state-dependent* — invisible in every account where the SLR already exists, including the developer's own.

**A6 — `route53:ListTagsForResource` (cycle 3, 15:42).**
`Error: listing Route 53 Hosted Zone (Z000441110FP43NILLF2D) tags: ... AccessDenied: ... route53:ListTagsForResource on arn:aws:route53:::hostedzone/Z000441110FP43NILLF2D` (ATL L1375).
*A data source reading tags.* The HCL says `data "aws_route53_zone"` — "look up a zone". The provider also reads its tags.

**A7 — `iam:TagInstanceProfile` (cycle 4, 16:03).**
`Error: creating IAM Instance Profile (e2e-gjbjs5): operation error IAM: CreateInstanceProfile, ... AccessDenied: ... not authorized to perform: iam:TagInstanceProfile` (ATL L1422).
*Tag-on-create.* `default_tags` make `CreateInstanceProfile` **also** authorize `TagInstanceProfile` — the error is raised on one API call but names a different action. The comment eventually written into the policy: "Tag-on-create: the provider's `default_tags` mean `CreateRole` and `CreateInstanceProfile` carry tags, which authorizes the `Tag*` action as well. **These never appear as separate CloudTrail events**, so they have to be reasoned about rather than replayed" (ATL L1456). **Invisible to source-reading AND to CloudTrail replay** (§3).

**A8 — KMS entirely: `Encrypt`, `Decrypt`, `GenerateDataKey`, `GenerateDataKeyWithoutPlaintext` (CloudTrail replay, 07-26 00:47).**
"**Missing entirely: KMS.** Four calls … from SSM `SecureString` parameters and encrypted EBS volumes. Also `ec2:GetSecurityGroupsForVpc` (`Describe*` doesn't cover `Get*`), `s3:DeleteBucketOwnershipControls`, and `s3:ListTagsForResource`" (ATL L1455).
*The word "kms" appears nowhere in the resource blocks that need it.* It is implied by `type = "SecureString"` and `encrypted = true` — a **semantic consequence of two attribute values**, not a lexical feature of the source. Highest-value class for this benchmark.

**A9 — `ec2:GetSecurityGroupsForVpc` (same replay).** *`Describe*` does not cover `Get*`* — a naming-convention trap; every other EC2 read in the module is a `Describe`.

**A10 — `ssm:GetInventory` (cycle 5, 07-26 01:19).**
`Waiting for i-0acf0fc72b2a82343 to appear in the SSM inventory returned an error: ... AccessDeniedException: ... ssm:GetInventory on arn:aws:ssm:us-east-1:694710432912:*` (ATL L1522).
*A test-harness call, not a provider call* — terratest polls SSM inventory to know the instance is up; nothing in the module needs it. Worse, it had already been seen and discarded: "I filtered it out of verification as assumed noise **despite it being in the ground truth**. My error" (ATL L1838 item 12).

**A11 — a wildcard matching a shared resource (post-green, 01:45).**
"my S3 scope `arn:aws:s3:::e2e-*` **matches** `e2e-tfstate-backend-694710432912-us-east-1`. The PR-assumable CI role can currently delete the Terraform state bucket for e2e-infra itself" (ATL L1567).
*Not a denial — a silent over-grant.* Derived correctly from the module's naming convention, with no awareness of what else in the account shares the prefix. **No failing run would ever surface it**; it was found by an unrelated leftover sweep. Tightened to `e2e-*-tfmigrate`.

**A12 — an IAM action that does not exist (00:49).**
"CloudTrail event names are not IAM action names. For S3, `GetBucketEncryption` → `s3:GetEncryptionConfiguration`, `GetBucketLifecycle` → `s3:GetLifecycleConfiguration`, and deleting ownership controls is authorized by `s3:PutBucketOwnershipControls`. **`s3:DeleteBucketOwnershipControls` is not a real action; IAM silently accepts it and it never matches**" (ATL L1498).
*A policy can be syntactically valid, deploy cleanly, and contain dead statements.*

---

## 2. Cost per iteration, as recorded

A cycle = push → Actions job → Packer AMI build → `terraform apply` → terratest validation (real HTTPS healthz against a Let's Encrypt staging cert, git-sync clone) → `destroy` → AMI deregister.

| Evidence | Value |
|---|---|
| Distinct CI job durations recorded | `17m22s`, `18m23s`, `18m58s`, `19m14s`, `19m38s`, `20m40s`, `21m53s`, `24m8s`, `30m12s`, `40m29s` |
| First green CI e2e | run `30182797333`, **20m40s**, "25 applied, 25 destroyed under the restricted CI role" (ATL L1577) |
| Second green CI e2e | `--- PASS: TestTerraformPackerAtlantis (939.70s)` (ATL L1557) |
| Local full run (incl. AMI build) | `(996.43s)` — "~16.6 min, all five stages" (ATL L1062) |
| Local run reusing a cached AMI | `(294.86s)`; "reuses the AMI so it should reach validate in ~2 minutes rather than 15" (ATL L3367) |
| Failing construct-path local runs | `1751.981s` (ATL L3127), `1242.476s` (ATL L3309) |

**Cycles to green on the HCL path: 6 CI runs** (13:38 → 01:44, across two calendar days), **plus two out-of-band tooling passes** (§3) each of which replaced several would-be cycles: "Rather than discover the rest one 17-minute run at a time, the remaining gaps were found with `iam simulate-principal-policy`" (ATL L1353).

**Not in the logs:** no token counts, no cost figures, no dollar amounts — wall-clock and cycle counts only. Token accounting for path (A) must come from the operator.

---

## 3. Fallback tooling — what each method failed to catch

Two methods were used out-of-band. Both helped materially; neither sufficed. The three traps, verbatim (ATL L1498):

> 1. **CloudTrail does not log tag-on-create authorizations.** `iam:TagInstanceProfile` never appears as an event, but `default_tags` make `CreateInstanceProfile` require it. Tag verbs must be reasoned about, not replayed.
> 2. **The simulator does not populate condition keys.** Anything guarded by `iam:PassedToService` or `kms:ViaService` reads as `implicitDeny` unless you pass `--context-entries`. Likewise, omitting `--resource-arns` evaluates against `*` and every resource-scoped statement looks denied.
> 3. **CloudTrail event names are not IAM action names.** […] `s3:DeleteBucketOwnershipControls` is not a real action; IAM silently accepts it and it never matches.

**`aws iam simulate-principal-policy`** (ATL L1321, L1342, L1346, L1351, L1391, L3817) found A3/A4/A5 "in seconds". Limits: it only answers a list **you supply**, so every defect it found was one already guessed; it reports `implicitDeny` for correctly-guarded statements absent `--context-entries` ("`iam:PassRole` reported `implicitDeny` until I supplied `iam:PassedToService=ec2.amazonaws.com`", ATL L1358); and it silently "allows" invented action names against a wildcard while silently never-matching them against a scoped one (A12).

**CloudTrail event replay** (ATL L1442–L1485; 555 events) found A8/A9 and `s3:ListTagsForResource`. Limits: **structurally blind to tag-on-create (A7)** — no event is ever emitted; event names ≠ action names (A12), so the derived list contained a non-existent action and three mis-named S3 reads; it requires a **prior successful run under a broad principal** (410 of the 555 events were made by the admin user `vincent_tyme`, not the CI role — ATL L1444), so it cannot bootstrap a policy for something never run; and it contains genuine noise indistinguishable from signal by inspection — exactly how A10 was filtered out and then cost a full cycle.

**Access Analyzer policy generation: not used.** The only trace is a single unrelated `access-analyzer:ListAnalyzers` in the aggregate (ATL L1444). **No evidence exists in these logs about its effectiveness — do not claim any.**

**Net:** together the two methods still left A7 and A10 to failing runs, and left A11 (silent over-grant) and A12 (dead statement) undiscoverable by either.

---

## 4. The construct path — what it fixed, and what it did not

The port lives in the same session (07-26 16:35–18:55). The L3 is `packages/atlantis/src/atlantis.ts` — `class Atlantis extends aws.AwsConstructBase implements aws.iam.IGrantable` (:314-317), `grantPrincipal = this.role` (the ASG instance role, :491).

| Grant site | Line | Library-derived? |
|---|---|---|
| `parameter.grantRead(this)` ×4 | :610 | yes |
| `dataVolume.grantAttachVolumeByResourceTag(this,[asg])` / `grantDetachVolume…` | :617-622 | yes |
| `bucket.grantReadWrite(this)` (tfmigrate) | :836 | yes |
| `datadog.apiKeySecret.grantRead(this)`, `githubPackagesSecret.grantRead(this)` | :627-628 | yes |
| `grantGetParametersByPath()` | :700-716 | **hand-written gap-filler** |
| `grantReadAmiManagedParameters()` | — | **hand-written gap-filler** |
| `grantSelfDiscovery()` (`ec2:DescribeVolumes`, `DescribeInstances`) | — | **hand-written gap-filler** |
| `grantAssociateElasticIp()` (`ec2:AssociateAddress`, `DescribeAddresses`) | — | **hand-written; no EIP L2 exists** |

**Four of eight grant sites are hand-written.** That ratio is what keeps this scenario's claims defensible.

### 4.1 What the library derives — verified against the pinned packages

`terraconstructs@0.2.13`, `lib/aws/storage/parameter.js:66-80`:

```js
grantRead(grantee) {
  if (this.encryptionKey) { this.encryptionKey.grantDecrypt(grantee); }
  return iam.Grant.addToPrincipal({ grantee,
    actions: ["ssm:DescribeParameters","ssm:GetParameters",
              "ssm:GetParameter","ssm:GetParameterHistory"],
    resourceArns: [this.parameterArn] });
}
```

`aws-cdk-lib@2.263.0` `aws-ssm/lib/parameter.js` (`ParameterBase.grantRead`) is **behaviourally byte-equivalent**: same four actions, same `this.encryptionKey && this.encryptionKey.grantDecrypt(grantee)`.

Other surfaces (`base` HEAD): `Instance` (`src/aws/compute/instance.ts:567-588`) auto-creates `iam.Role` + `IamInstanceProfile` and sets `grantPrincipal = this.role`, with **no `grantXxx()` of its own** — grants flow *into* the instance role, never out. `src/aws/storage/bucket-perms.ts:2-37`: `BUCKET_READ_ACTIONS=["s3:GetObject*","s3:GetBucket*","s3:List*"]`, `KEY_READ_ACTIONS=["kms:Decrypt","kms:DescribeKey"]`, `KEY_WRITE_ACTIONS=["kms:Encrypt","kms:ReEncrypt*","kms:GenerateDataKey*","kms:Decrypt"]`; `Bucket.grant()` (`bucket.ts:1071-1092`) plumbs `encryptionKey.grant(...)`. `src/aws/compute/volume.ts:570-587`: `grantAttachVolume` also grants `kms:CreateGrant` when encrypted. Route53 L2s exist (`src/aws/edge/dns-record.ts`, `dns-zone.ts`) with **no `grant*` methods at all**. **No EIP L2 exists anywhere** (`TerraConstructs/base#130`); the L3 drops to the raw `eip.Eip` (atlantis.ts:445).

### 4.2 Eliminated **by construction** (workload principal only)

- **A8 (KMS), three ways** — SSM (`grantRead` → `grantDecrypt`), EBS (`grantAttachVolume` → `kms:CreateGrant`), S3 (`Bucket.grant*` → `KEY_*_ACTIONS`). Verified in source in both libraries. That KMS is derived on **three independent resource types** is why A8 is the right catch to build the scenario around.
- Resource-ARN scoping of every derived read (`resourceArns:[this.parameterArn]`, never a wildcard).

### 4.3 Not eliminated — with evidence

**The deployer principal is entirely outside the library's reach.** A repo-wide search of `/Users/vincentsmet/tcons/base/src/` for "deployment polic\*", "provisioner polic\*", "deployer polic\*", "required permission", "least privilege", `RunInstances`, `ChangeResourceRecordSets`, `iam:CreateRole` returns **only incidental prose** — there is **no feature, helper, or concept anywhere in the library for deriving the deploying principal's policy.** Every `grantXxx()` inspected derives permissions for the **workload** principal. **Every one of A2–A7 and A9–A12 is untouched by the construct path.** Corroborated by the port's own three deployer-role denials (`iam:TagInstanceProfile` ATL L1423, `iam:CreateInstanceProfile` ATL L3741, `route53:ListHostedZonesByName` ATL L3638) — all diagnosed and fixed **by hand, outside the library**.

**C-1: `grantRead()` is itself incomplete** (local run 2, FAIL after `1242.476s`).
`AccessDeniedException: User: ...assumed-role/e2e-cobvrl-atlantistlantisInstanceRole.../i-0da8ca22b804061ad is not authorized to perform: ssm:GetParametersByPath on .../parameter/e2e-cobvrl/atlantis-yaml/contents` (ATL L3285-3286; repeated for `caddy/data`, `policies-conftest-env/contents`, `atlantis-repos-yaml/contents` — all four construct-created params).
"confd uses **`ssm:GetParametersByPath`**. The L2 `parameter.grantRead()` grants `GetParameter`/`GetParameters`/`GetParameterHistory`/`DescribeParameters` — but *not* `GetParametersByPath`. Tellingly, the three files that *did* render are the AMI-managed ones where I **hand-wrote** the statement with `GetParametersByPath`" (ATL L3287-3288). "This matches aws-cdk exactly, so **this is a parity issue rather than a regression** — but it cost me a full e2e cycle to find" (ATL L3406).
The failure was **silent**: "The instance booted, passed health checks, and registered with SSM Session Manager. But no config file was ever rendered" (ATL L3406). Filed as **`TerraConstructs/base#133`** ("an enhancement, not a bug… this is aws-cdk parity"), **not** filed upstream against `aws/aws-cdk`, and **still open** at the end of the transcript, listed under "Upstream L2 gaps still worked around here" beside #130 and #131. A checked-out aws-cdk confirms `ssm:GetParametersByPath` appears **nowhere** in its `aws-ssm` module and that aws-cdk has **no** hierarchy/path-prefix grant method, with no documented rationale (ATL L3419-3430). **Unfixed in both libraries.**

**C-1b: `grantAttachVolumeByResourceTag` is also incomplete** — it grants `ec2:AttachVolume` but not the `ec2:DescribeVolumes`/`DescribeInstances` the workload needs to *find* the volume, hence the hand-written `grantSelfDiscovery()`. Symptom: "cloud-init hangs; instance looks healthy" (ATL L3841). A **second independent** instance of "the derived grant is a subset of what the workload actually calls".

**C-2: the port introduced a NEW harness defect** — `route53:ListHostedZonesByName` (18:04, ATL L3637). The port replaced a `data "aws_route53_zone"` (which calls `ListHostedZones`) with a Go SDK call to the purpose-built `ListHostedZonesByName`. Same class as A10.

**C-3: the port introduced a NEW naming defect** — `Error: creating IAM Instance Profile (terraform-6d89aa04506d7de99496a2edbe): ... iam:CreateInstanceProfile` (ATL L3740). "Letting LaunchTemplate create the instance profile unnamed makes the AWS provider generate `terraform-<hash>`. e2e-infra scopes IAM to `instance-profile/e2e-*`, so the generated name fell outside it. `module/iam.tf` named the profile `var.name_prefix`, which is why the module never hit this" (ATL L3784). **Auto-generated names are actively hostile to name-prefix-scoped policies** — independently confirmed by `docs/slice-g-iam-proposal.md`'s own "Open gaps" §1 for the awscdk arm's unprefixed Lambda names.

**The construct path did not converge first time.** Local runs 1 and 2 failed (`1751.981s`, `1242.476s`), then two CI failures. The port's closing tally (ATL L3841, 18:54) is headed **"Six bugs, none of which unit tests could have caught"**:

| Found in | Bug | Why invisible statically |
|---|---|---|
| local e2e | missing `ec2:DescribeVolumes`/`DescribeInstances` | cloud-init hangs; instance looks healthy |
| local e2e | missing `ssm:GetParametersByPath` | confd renders nothing; `apply` reports success |
| local e2e | `record.domainName` vs `record.fqdn` | cert requested for the bare hostname |
| CI | `route53:ListHostedZonesByName` denied | local IAM user had it; the OIDC CI role did not |
| CI | auto-generated `terraform-<hash>` instance profile | fell outside `instance-profile/e2e-*` |
| build | jsii compiled into `src/`; Jest resolved `.js` first | suite reported green against stale code |

> "Six bugs found and fixed, **five of which only surfaced in real execution**." — ATL L4121

**This is the strongest justification in the record for making the scenario live-graded rather than synth-graded.**

### 4.4 Bottom line

The construct path eliminates **one** defect class (A8, across three resource types) plus resource-ARN scoping. It leaves **A2–A7 and A9–A12 entirely**, adds C-2 and C-3, carries C-1/C-1b, and needs hand-written policy at half its grant sites. A scenario claiming more is easy to discredit.

---

## 5. Scenario design

### 5.1 Shape

`id: iam-deploy-role`, `difficulty: 3`, `services: [iam, ssm, kms, s3, ec2, route53]`.

The workspace ships a **fixed, seeded Terraform module** (`module/`, byte-identical across arms, never edited by the agent — enforced by a checksum in the trajectory-audit gate). The agent's deliverable is **two IAM roles authored in its own substrate**:

1. a **deployer role** — assumed by the harness to `apply` and `destroy` the seeded module;
2. a **workload role** + instance profile — passed *into* the module as an input variable.

The agent must then **run the harness, observe denials, amend, and repeat**.

Holding the deploy *target* constant while varying only the *policy-authoring substrate* is what makes the loop comparable, and lets `hcl_raw` be a genuine peer rather than "the arm that also has to port the module".

### 5.2 What the seeded module keeps, and what to drop

**KEEP** — each row is the minimum that makes a §1 class reachable:

| Resource | Class reached | ≈cost |
|---|---|---|
| `aws_iam_role` + `_role_policy` + `_instance_profile`, provider `default_tags` | **A7** tag-on-create (`iam:TagRole`, `iam:TagInstanceProfile`) | <5s |
| `aws_ssm_parameter` ×2 (one `SecureString` under a pre-provisioned CMK) | **A8**; **C-1** `GetParametersByPath` | <5s |
| `aws_security_group` in the default VPC | **A9** `ec2:GetSecurityGroupsForVpc` (`Describe*` ≠ `Get*`) | ~5s |
| `aws_s3_bucket` + `_ownership_controls` + `_policy`, behind `count = var.extra_bucket_enabled ? 1 : 0`, flag **ON** in the seeded tfvars | **A3** module-flag resource + the four non-`GetBucket*` refresh reads | ~10s |
| `aws_route53_record` in a pre-provisioned zone | **A6** `route53:ListTagsForResource`; `route53:GetChange` (no resource-level ARN → must be `Resource:"*"`) | ~30–60s |
| `aws_ebs_volume` `encrypted = true` + `kms_key_id` | **A8** on the EC2 side (different KMS grant shape); **C-1b** | ~10s |
| a **second no-op `plan`/`apply`** in the harness | **A4** refresh-time reads | ~15s |

**DROP** — cost or flakiness exceeds marginal value:

- **Packer / AMI build** (15 min/cycle). A2's class is preserved instead via the provider's own post-create calls on `aws_ebs_volume` and the bucket's `PutBucketOwnershipControls`-authorized delete (A12's real mechanism).
- **ASG + launch template + instance refresh** — minutes, and **A5** (`iam:CreateServiceLinkedRole`) is account-state-dependent, hence *unreproducible* in a shared account where the SLR already exists. Dropping A5 is deliberate and must be stated in `oracle.intent`.
- **The EC2 instance, EIP, cloud-init, Caddy/ACME, healthz, Datadog, git-sync, Atlantis itself** — all boot-time; none add a policy class. The EIP drop is also load-bearing for arm parity (§5.9).

**Target ≈120–180 s per assume→apply→assert→destroy cycle.** Must be measured in a pilot; if it exceeds 240 s, drop the Route53 record (the most expensive row) and lose A6.

### 5.3 Pre-provisioned account fixtures (need a `DECISIONS.md` authorization)

Must exist in `886312446417` before any trial:

- **A customer-managed KMS key** + alias `alias/cdktn-bench-scenario`. A per-trial `aws_kms_key` has a **mandatory ≥7-day deletion window** — it does not clean up, and trials would accumulate keys at ~$1/mo each.
- **A public Route53 hosted zone** (~$0.50/mo) — not economically creatable per trial.
- **A decoy protected bucket**, e.g. `cdktn-bench-tfstate-886312446417-us-east-1`, existing and never to be touched. This mechanizes **A11**.

### 5.4 Trust: local and testable, no OIDC

```
Principal: { AWS: "arn:aws:iam::886312446417:root" }
Condition: { StringEquals: { "sts:ExternalId": "<TRIAL_ID>" } }
```

`TRIAL_ID` is injected as an env var; the harness runs `aws sts assume-role --role-arn <authored> --external-id "$TRIAL_ID"`. A wrong trust policy fails at step 1 with a clean `AccessDenied` — reproducing **A1**'s failure mode with zero GitHub involvement. Negative fixture: `Principal:"*"` with no condition must **fail** the least-privilege oracle.

### 5.5 The harness — and the terratest recommendation

**Recommendation: do NOT add Go + terratest. Ship a thin, arm-neutral `tests/harness/validate.sh` plus a stdlib-`python3` assertion module, built on the `terraform`/`cdk` CLI already in each arm image and the AWS CLI v2 already baked into all three.**

| Option | Image delta | Runtime/iter | Fidelity | Cross-arm fairness |
|---|---|---|---|---|
| (a) Go + terratest | **+0.8–1.3 GB per arm** (Go ~500 MB; terratest's graph pulls AWS SDK v2 + testify, several hundred MB more, and must be **vendored at build time** because the images have no network at trial time) | +2–5 s warm, +20–60 s cold compile | Highest — what the real episode used | **Fails.** terratest drives `terraform`; the `awscdk` arm emits CloudFormation. There is no equal-strictness terratest path for CFN, so awscdk needs a *differently implemented* harness — breaking "authored once, implemented at equal strictness per arm" at the layer that matters most: the loop the agent iterates against |
| **(b) `terraform`/`cdk` + AWS CLI + stdlib `python3`** ✅ | **zero** — all three Dockerfiles already install `awscli v2`, `jq`, `git`, `python3` (stdlib) and the arm's deploy CLI | apply/destroy only | High. **A10** and **C-2** reproduce exactly: the harness makes its *own* `aws ssm get-parameters-by-path` and `aws route53 list-hosted-zones-by-name` calls, which the deployer policy must also cover | **Passes.** One assertion module, one `--expect` contract; only the deploy verb differs per arm — the same split `specs/apigw-redeploy.yaml` already uses (`npx cdk deploy` vs `terraform apply`) |
| (c) Python + boto3 | +~50 MB per arm, and it **breaks an explicit stated invariant**: all three Dockerfiles say *"python3 (stdlib only, no pip package ever installed)"* | as (b) | as (b) | Passes, but buys nothing over (b) — the AWS CLI is boto3 underneath and is already present |

(b) also reuses proven machinery: `tests/test.sh` already invokes `python3 "$DIR/live_check.py"` and folds its `.outcome` (`pass`/`fail_*`/`not_verifiable`/`run_invalid`) into `reward.txt` under `SPEC_LIVE_CHECK_GATING=true`. Emit that same JSON contract unchanged.

Harness phases (fixed; agent-readable, agent-**un**editable, checksum-enforced):
1. `aws sts assume-role --external-id "$TRIAL_ID"` → export creds.
2. Under those creds: the arm's deploy verb against the seeded module.
3. A no-op second `plan`/`apply` (forces refresh-time reads, **A4**).
4. Assertions via `aws` CLI under the **workload** role, assumed in turn: `aws ssm get-parameters-by-path --with-decryption` (**A8** + **C-1**) and `aws route53 list-hosted-zones-by-name` (**C-2** class).
5. `destroy` under the deployer creds.
6. Emit `/logs/verifier/live_check-result.json`.

### 5.6 Per-arm output contracts

Shared `instruction.shared_body`; only `language_line` + `output_contract` differ (generator-enforced parity).

| Arm | `entry_file` | `artifact_path` | build/synth | deploy verb |
|---|---|---|---|---|
| `awscdk` | `lib/scenario-stack.ts` | `cdk.out/ScenarioStack.template.json` | `npm run build`; `npx cdk synth --no-lookups --quiet -o cdk.out` | `npx cdk deploy` |
| `hcl_raw` | `main.tf` | `plan.json` | `terraform init && validate && plan -refresh=false -out=… && show -json` | `terraform apply` |
| `terraconstructs` | `lib/scenario-stack.ts` | `cdktf.out/stacks/iam-deploy-role/plan.json` | `npx cdktn synth` | `terraform apply` on the synthesized stack |

`agent-output.json` fields: `deployer_role_arn`, `workload_role_arn`, `instance_profile_name`, `external_id`.

**Carry over the `-refresh=false` precedent** (`specs/apigw-redeploy.yaml` L112-129): this working tree will also have real prior state when the offline static tier runs.

### 5.7 What the oracle asserts

Two independent properties; either alone is gameable.

**(i) "The role works"** — LIVE, gating. `outcome == "pass"` requires: assume succeeded, apply exited 0, the second plan was clean, every phase-4 assertion returned the expected value, and destroy exited 0 with no orphans.

**(ii) "The role is least-privilege"** — STATIC, tier 1, on the delivered artifact. Without it the scenario is won in one iteration by `{"Effect":"Allow","Action":"*","Resource":"*"}`.

1. **No admin wildcard** — no statement whose `Action` includes `"*"`, `"iam:*"`, `"ec2:*"`, `"s3:*"`, `"ssm:*"`, `"kms:*"`, `"route53:*"`. Sub-service wildcards (`s3:GetBucket*`) are permitted; the real reference policy uses them (ATL L1464).
2. **Action-count ceiling** — ≤ N distinct actions, N = reference count + 20%. Bounds "paste the whole IAM catalogue" gaming.
3. **Every action string is a real IAM action**, validated against an action catalogue pinned into the oracle bundle. Makes **A12** gradeable.
4. **No wildcard matches the decoy bucket** — `fnmatch` every S3 resource pattern against `cdktn-bench-tfstate-886312446417-us-east-1`. Makes **A11** gradeable. Live cross-check: `aws iam simulate-principal-policy … s3:DeleteBucket` on the decoy → must be `implicitDeny`.
5. **Trust policy bounded** — principal ≠ `"*"`; a `Condition` block exists.
6. **`iam:PassRole` guarded** by `iam:PassedToService` (the mitigation the real policy adopted, ATL L1838).

### 5.8 Catches and predicted tiers

| Catch | `applies_to` | Predicted tier | Note |
|---|---|---|---|
| `admin-wildcard-policy` | all | `"1"` | static |
| `invalid-action-name` | all | `"1"` | static catalogue check (**A12**) |
| `wildcard-matches-protected-bucket` | all | `"1"` | static fnmatch (**A11**) |
| `trust-policy-unconditional` | all | `"1"` | static (**A1** class) |
| `missing-tag-on-create` | all | `"live"` | **A7** — no static tier can see it |
| `missing-refresh-time-reads` | all | `"live"` | **A4** |
| `missing-kms-for-securestring` | **`[hcl_raw]`** | `"live"` | **A8** — unreachable by construction on the L2 arms (§4.2). The discriminating catch |
| `getparametersbypath-not-granted` | **all** | `"live"` | **C-1** — the anti-overclaim catch; `grantRead()` misses it on **both** libraries (`base#133`, open, unfixed upstream too) |
| `volume-self-discovery-not-granted` | **all** | `"live"` | **C-1b**, optional second anti-overclaim catch if the EBS row is kept |

`missing-kms-for-securestring` is the scenario's discriminating hypothesis; the two `grantXxx`-gap catches are its deliberate counterweight. **Shipping both is what makes the scenario credible.**

### 5.9 Budget, cost, cleanup, arms

- **`verifier.budget.max_iters: 8`** (schema default; do not raise without a `DECISIONS.md` amendment). 8 × ~180 s ≈ 24 min in-trial wall clock. Whether a naive first attempt converges in ≤8 is **the** open pilot question — the real episode needed 6 cycles *plus* two tooling passes over a larger module; this reduced module has ~7 reachable classes.
- **`concurrency_mode: "mutating"`, `gating: true`** — required: four catches are `predicted_tier_caught: "live"`, so non-gating would make them cost nothing.
- **AWS cost per trial < $0.05.** IAM/SSM/S3/SG/Route53-record are free or sub-cent; CMK + hosted zone are amortized fixtures (~$1.50/mo total). No EC2 instance-hours if the DROP list is honoured.
- **Cleanup.** The harness destroys the module every iteration, so a green trial leaves only the two authored roles. Still required: a fixed-name sweep in the `scenarios/anchor/reset/reset.sh` pattern for both roles, the instance profile, the SSM parameters under the fixed path, the bucket, the SG, the Route53 record and the EBS volume; **inline policies deleted and managed policies detached before `DeleteRole`** (the generic sweep will not do this); and idempotent `|| true` guards throughout, because a trial that dies mid-`apply` leaves partial resources.
- **Arms: all three enabled**, verified against the pinned packages, not assumed. `terraconstructs@0.2.13` has `iam.Role`/`PolicyStatement`, `storage.StringParameter` with `fromSecureStringParameterAttributes` + `encryptionKey` (`parameter.d.ts:414,426,457`), `encryption.Key`/`Alias.grantDecrypt`, and `compute.Instance` with `role`/`grantPrincipal`/`addToRolePolicy`.

  **Blocking constraint:** CloudFormation **cannot create** SecureString parameters — terraconstructs' own source says so: *"Parameters of type SecureString cannot be created directly from a CDK application due to CFN limitations"* (`parameter.d.ts:268`). The SecureString parameters must therefore be **pre-provisioned fixtures all three arms IMPORT** — `fromSecureStringParameterAttributes(...).grantRead(role)` on the L2 arms, `data "aws_ssm_parameter"` on `hcl_raw`. Not a workaround: the only symmetric design, and it removes create/destroy cost.

  **Two coverage facts constraining §5.2:** terraconstructs has **no EIP L2 at all** (`base#130`) and its Route53 L2s expose **no `grant*` methods**. Both are on the DROP list or need no grant, so the scenario is unaffected — but neither may be added later without re-checking.

---

## 6. How this could be unfair, or gamed

1. **The deployer role is not arm-discriminating, by design.** No library derives provisioning permissions (§4.3). If most of tokens-to-green is spent on the deployer loop, the scenario will show little arm separation. That is a *real, preregisterable prediction*, not a flaw — but it must be written into `oracle.intent` **before** any run, or it will look like a post-hoc excuse.
2. **The KMS catch may be too easy on `hcl_raw`.** A capable agent may simply know SecureString implies `kms:Decrypt`. Mitigation: grade on the `kms:ViaService` **condition key** (which the real policy used and the L2s emit), not only the action.
3. **`hcl_raw` writes more lines for the same policy.** `grantRead()` is one call; HCL needs an `aws_iam_policy_document`. Tokens-to-green partly measures verbosity. Unavoidable, and it applies benchmark-wide — but it is sharper here because the artifact *is* a policy document.
4. **The action-count ceiling is blunt.** Too low it punishes a correct-but-differently-factored policy; too high it lets shotgunning through. Calibrate from the reference solution and record the calibration.
5. **The agent can read the seeded module and the harness and enumerate perfectly on attempt 1.** That is the intended skill, but it means the scenario partly measures "did you read the harness" — which the real episode's agent could not do. Accept it, and note the highest-value defects (**A7**, **A8**, **A4**) are *not* readable off either file: they are provider behaviour.
6. **Live-gating means infrastructure flakiness scores as agent failure.** Route53 propagation and IAM's own eventual consistency (a freshly created role is not immediately assumable) will produce false negatives. The harness **must** poll with real margin — exactly the fix `tasks/anchor/apigw-redeploy-hcl-raw/tests/live_check.py` documents as its Finding 1. Reuse that code; do not re-invent it.
7. **Two roles in one task may be too much.** If pilots show `max_iters: 8` unreachable, split into two scenarios (deployer-only, workload-only) rather than raising the cap.

---

## 7. What the logs do not contain

- **No token counts and no cost figures anywhere**, on either path — wall-clock and cycle counts only (§2).
- **No Access Analyzer policy-generation evidence.** It was not tried (§3).
- **No single final "correct" policy** — it evolved across many diffs. `/Users/vincentsmet/tcons/atlantis/e2e-infra/policies.tf` is the authority; read it directly when authoring the reference solution.
- **No measurement of a reduced-module cycle time.** §5.2's 120–180 s is an estimate from component costs, not an observation.
- **`base#133` status must be re-verified.** The `GetParametersByPath` catch's correctness depends on the gap remaining open in `terraconstructs@0.2.13`; pin the version in `arms.terraconstructs.reason`.
- **The scenario account's fixture state is unverified.** Whether `886312446417` already has a usable hosted zone, CMK or default VPC was **not** checked — this proposal made no AWS calls.
