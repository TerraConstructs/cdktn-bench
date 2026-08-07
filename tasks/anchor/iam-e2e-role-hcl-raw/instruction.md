Author two IAM roles for a real, live Terraform deployment in this AWS
account, then use them for real -- iterating against actual AWS denials --
until deployment and teardown both work under exactly the permissions you
granted.

This workspace has a fixed Terraform module at `module/` (read-only
reference input -- do not edit it) that provisions a small set of AWS
resources: a security group, an encrypted EBS volume, an S3 bucket, and an
EC2 instance profile. Read it to understand what it creates, but treat it
as given -- your job is authoring the IAM permissions around it, not the
module itself.

Author, in this file, using your target language/toolchain (see below):

1. A DEPLOYER role, named exactly `iam-e2e-role-deployer`, under IAM path
   `/cdktn-bench-task/`. Its trust policy must allow this AWS account's
   root principal to assume it, gated by a condition requiring a specific
   `sts:ExternalId` value that you choose yourself and record (see the JSON
   contract below). Grant this role exactly the permissions needed to run a
   real `terraform apply` and a real `terraform destroy` of `module/` in
   this account -- no more, no less.

2. A WORKLOAD role, named exactly `iam-e2e-role-workload`, under the same
   IAM path. Its trust policy must allow BOTH the `ec2.amazonaws.com`
   service principal (this is the role a real EC2 instance would use in
   production) AND this account's root principal, gated by the same kind of
   `sts:ExternalId` condition as the deployer role (a test harness needs to
   be able to assume this role directly, since this task's module never
   boots a real EC2 instance). Grant this role exactly the permissions a
   workload attached to `module/`'s resources genuinely needs to read and
   use them -- no more, no less.

Deploy your two roles for real, using your toolchain's real deploy command
against this account (not just synth/plan).

Then run the harness at `harness/validate.sh` (read-only reference input;
see its own header comment for exactly what it does and how to invoke it)
from your project root. It assumes your deployer role, applies `module/`
for real under that role, runs further checks, assumes your workload role,
runs further checks under that role, then destroys everything it created.
Every failure it reports is a real AWS denial in this account, not a
simulated one. Read the denied action name, decide which of your two
roles' policies is missing it, fix that role's policy, redeploy, and re-run
the harness. Repeat until it reports every phase passed.

Reading `module/`'s resource blocks is a starting point, not a complete
answer -- some of the permissions either role genuinely needs cannot be
determined by inspection alone, and are only found by actually running the
harness and reading what it denies.

Both roles must be least-privilege. Concretely: do not grant `Action: "*"`
on any statement; do not grant a full-service wildcard action (an action
string of the exact form `service:*`, e.g. `iam:*` or `ec2:*`); every
action you grant must be a real IAM action; and scope every `Resource` to a
specific ARN or ARN pattern rather than `"*"` wherever you can express one.
Do not grant any S3 permission a bucket-name pattern broader than what
`module/`'s own bucket needs -- a pattern that also happens to match some
OTHER bucket already in this account is a real security defect, not a
convenience, even if nothing in this task's own harness would ever notice.
A policy that only "works" because it grants far more than it needs is not
a correct solution to this task, regardless of what the harness reports.

Write `/logs/agent/agent-output.json` (see the JSON contract below)
recording both roles' real ARNs and the external-ID value you chose, so the
harness (and your own re-runs of it) can find and use them.

Do NOT delete the two roles or the module's resources when you are done --
leave them running. Cleanup of this account is handled automatically by the
benchmark itself once grading is complete; it is not part of your task.

Author this as hand-written Terraform HCL (no modules). Deploy for real with `terraform apply`.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write. `module/main.tf`, `harness/validate.sh`, and `harness/assertions.py` are also seeded read-only in this workspace as reference input -- read them as needed, but do not modify them.

Real deploy note: `provider.tf` (which you must not edit, see above) defaults to an offline fixture with dummy AWS credentials -- before running your REAL deploy command, export `TF_VAR_cdktn_bench_live=1` in your shell so `provider.tf` uses this environment's real ambient AWS credentials instead. This is a normal environment variable, not a change to `provider.tf` itself.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.

Additionally, write `/logs/agent/agent-output.json` containing exactly:

```json
{
  "deployer_role_arn": "<the real ARN of the deployer role you created, e.g. arn:aws:iam::123456789012:role/cdktn-bench-task/iam-e2e-role-deployer>",
  "workload_role_arn": "<the real ARN of the workload role you created, e.g. arn:aws:iam::123456789012:role/cdktn-bench-task/iam-e2e-role-workload>",
  "external_id": "<the sts:ExternalId value you chose and put in both roles' trust policy conditions>"
}
```
