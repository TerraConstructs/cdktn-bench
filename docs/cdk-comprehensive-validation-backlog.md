# CDK comprehensive validation: scenario and task backlog

**Status:** deferred from the v1 scenario set. This is an evidence and promotion
backlog, not an enabled benchmark task.

## Why this is relevant

Pahud's [CDK comprehensive-validation article][article] describes two feedback
layers that can reduce an AI agent's late-failure loop:

1. the bundled, post-synthesis CloudFormation validator, and
2. CloudFormation pre-deployment validation, reached by creating a stack,
   updating a stack, or creating a change set.

The first is potentially useful as an inexpensive authoring-time signal. The
second catches account-state-dependent conditions such as name conflicts and
service quotas before provisioning. Both are valuable *product* capabilities,
but neither is automatically a valid `cdktn-bench` scenario: this benchmark
compares equivalent authoring tasks and equivalent oracles across AWS CDK,
raw Terraform HCL, and (where supported) terraconstructs.

## Current benchmark boundary

The v1 benchmark is deployment-free and its grading path is offline:

| Arm | Agent feedback/oracle path |
| --- | --- |
| `awscdk` | `tsc` + `cdk synth --no-lookups`, then static assertions and cfn-guard |
| `hcl-raw` | `terraform validate` + offline `terraform plan`, then static assertions and Rego |
| `terraconstructs` | `tsc` + `cdktn synth` + offline `terraform plan`, then static assertions and Rego |

The pinned AWS CDK workspace currently combines `aws-cdk-lib` **2.263.0** with
`aws-cdk` CLI **2.1135.0**. The article's local-validator discussion is based
on `aws-cdk-lib` 2.263.0, but a library pin alone does not establish the CLI
behavior, validator report behavior, or network/credential behavior that a
benchmark gate would rely on.

The online layer is explicitly out of scope for v1. AWS documents
pre-deployment validation as a CloudFormation operation that needs IAM
permissions, deployed-region access, and, for several checks, read access to
account state. It runs on CreateStack, UpdateStack, or CreateChangeSet; it is
therefore not a substitute for the current credentialless/offline oracle.

Sources:

- [Article: *Stop Waiting 10 Minutes to Fail*][article]
- [AWS CloudFormation: pre-deployment validation][cfn-validation]
- `README.md` (deployment-free oracle design)
- `arms/awscdk/environment/workspace/package.json` (exact CDK pins)

## Fairness rule

Do not turn on an AWS-CDK-only validator in a benchmark task merely because it
improves CDK feedback. That would compare unequal toolchains rather than
abstraction quality.

A validation capability may influence a benchmark scenario only when all of
the following hold:

1. **Equivalent intent:** the same natural-language task and planted catch
   apply to every enabled arm.
2. **Equivalent evidence:** cfn-guard over the CloudFormation artifact and
   Rego over Terraform plan JSON express the same intended invariant; neither
   arm gets a weaker policy merely to preserve a hoped-for difference.
3. **Pinned-toolchain proof:** the claimed early catch is reproduced inside
   each arm's pinned image, including the raw-HCL provider pin and the
   terraconstructs construct version.
4. **Oracle proof:** each declared catch has a green reference solution and a
   failing broken fixture at its predicted tier for every enabled arm.
5. **No hidden online dependency:** an enabled v1 path works with
   `--network none` and no AWS credentials, and makes no AWS API request,
   template upload, or change-set call.

A difference in *which existing offline tier* catches the same mistake is a
legitimate result. A difference caused only by giving one arm an extra
validator is not.

## Candidate investigation tasks

These are characterization tasks, not benchmark scenarios and must not modify
`specs/split.yaml` or generated `tasks/` until the promotion gates pass.

### Task A — characterize the bundled local validator

Run this in the pinned `awscdk` arm image, before changing a scenario or
`cdk.json`:

1. Record `npx cdk --version`, `aws-cdk-lib` version, and the bundled
   `@aws/cloudformation-validate` version.
2. Create a minimal known-valid app and establish its baseline result.
3. Create minimal L1/template-level probes for an invalid CloudFormation
   property, an invalid FIFO queue name, and an incompatible Lambda
   SnapStart/runtime pair. Do not use these probes as benchmark tasks yet.
4. Compare default context with the article's
   `@aws-cdk/core:validateAgainstDefaultRules` and
   `@aws-cdk/core:annotationsInValidationReport` context keys. Record whether
   the finding is emitted, its severity, and whether synthesis fails.
5. Repeat with `--network none` and blank AWS credentials. Capture a
   machine-readable transcript suitable for a future regression test.

This separates a real local, reproducible validation signal from an assumed
one, and makes the current CLI/library skew visible rather than implicit.

### Task B — characterize equivalent Terraform feedback

For each Task-A candidate that produces a stable CDK finding:

1. Author the same desired state in raw HCL and terraconstructs, using only
   ordinary public constructs for that arm.
2. Run each arm's exact offline `terraform validate`/`plan` path.
3. Record whether the corresponding mistake is rejected by TypeScript,
   Terraform provider validation, synthesis, plan, or only the benchmark
   artifact policy.
4. Reject candidates that require an AWS CDK L1/escape hatch but do not have a
   semantically comparable Terraform representation.

This is necessary because prior benchmark work has shown that a proposed
cross-arm early-catch difference can disappear when the actual pinned
Terraform provider rejects the same value.

### Task C — promote only a proven common scenario

If Tasks A and B produce an equivalent, deployment-free task, add the normal
complete scenario surface:

- `specs/<id>.yaml`, with parity-preserving instruction and per-arm predicted
  tiers;
- generated task directories under
  `tasks/anchor/<id>-{awscdk,hcl-raw,terraconstructs}/` for every enabled arm;
- equivalent `oracles/cfn-guard/<id>/policy.guard` and
  `oracles/rego/<id>/policy.rego` bundles;
- reference solutions and one or more isolated broken fixtures covering every
  declared catch;
- regenerated train/holdout assignment using `generator/split.py --write`;
- green `make ci`, including generation synchronization, path checks,
  falsifiability, and grading proof.

## Candidate scenarios to investigate after characterization

| Candidate | Article connection | Likely risk / decision criterion |
| --- | --- | --- |
| FIFO SQS queue name | The default validator flags a FIFO queue name without the `.fifo` suffix. | May already be caught by CDK L2 or a Terraform provider. It is eligible only if the same intended FIFO queue task and artifact policy can be expressed across all enabled arms. |
| Lambda SnapStart/runtime compatibility | The article names incompatible runtime combinations as an error. | May need an L1/escape-hatch representation and terraconstructs support must be verified. Reject if it becomes an L1-vs-L2 or version-pin comparison. |
| Deprecated Lambda runtime | The article shows `nodejs16.x` as a warning. | A warning is not a green/fail oracle by itself. Promote only if all arms have an equivalent, stable desired-state policy and the benchmark explicitly measures it rather than a CDK-only report. |
| Plain parameter reference used as a secret | The article calls out a security finding. | This is policy/compliance intent, not necessarily an authoring-time validity error. It needs strict, equivalent CFN/TF policies and an intentional decision about security-policy scope. |

The account-state scenarios from the article (resource-name conflicts, quotas,
S3 deletion readiness, Config recorder conflicts, and ECR deletion readiness)
remain explicitly **not candidates for v1**. They depend on live account state
and would make results sensitive to credentials, region, and concurrent
infrastructure.

[article]: https://dev.to/pahud/stop-waiting-10-minutes-to-fail-how-cdk-comprehensive-validation-catches-misconfigurations-before-1907
[cfn-validation]: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/validate-stack-deployments.html
