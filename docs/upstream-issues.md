# Upstream issues and gaps found while building cdktn-bench

Findings about **upstream projects** (terraconstructs, cdk-terrain, aws-bench,
aws-cdk-lib, terraform-provider-aws) that surfaced while authoring scenarios.
Kept here so they can be filed upstream rather than silently worked around.

Each entry: what we observed, how it was verified, what we did in the benchmark
meanwhile, and whether it looks like a **bug**, a **coverage gap**, or
**expected behaviour we merely had to learn**.

---

## terraconstructs

### T1 — no `blockPublicAccess` prop on the S3 bucket L2 (0.2.13) — *coverage gap*
**Observed while:** authoring `s3-bucket-hardening-decomposition`. The awscdk L2
takes `blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL` as a prop;
terraconstructs 0.2.13 has no equivalent, so the reference solution needs an
escape hatch to reach the underlying `aws_s3_bucket_public_access_block`.
**Benchmark impact:** recorded as a pre-registered escape-hatch tax on that arm —
a legitimate measured cost, not a defect to hide.
**Status:** unverified against a newer release. Re-check before filing.

### T2 — UserData renders through `hashicorp/cloudinit`, making the ASG L2 unusable offline — *design constraint, possibly worth an upstream discussion*
**Observed while:** authoring `asg-launch-template-tag-propagation`. Every
built-in UserData path renders via the `hashicorp/cloudinit` provider. In a
hermetic (offline mirror) environment that provider is absent, so no idiomatic
terraconstructs solution can synth.
**Benchmark impact:** blocked that arm offline. Either the provider joins the
mirror, or the arm is disabled for the scenario with a checkable reason.
**Worth raising upstream:** a pure-string UserData path with no provider
dependency would make the construct usable in air-gapped/hermetic pipelines —
a real-world constraint, not just ours.

### T3 — physical-name default is `namePrefix` — *expected behaviour, documented here because we initially graded it as a failure*
`src/aws/iam/role.ts:489-509`: omitting `roleName` emits `namePrefix` (a
provider-computed name) rather than `name`. Terraform then omits
`values.name` from the plan, because it is not known until apply.
**Our bug, not theirs:** our oracle keyed identity on `values.name`, so the
idiomatic terraconstructs solution scored 0.0 while the equivalent CDK solution
scored 1.0. Fixed by Amendment 29 §4 (grade by address, never by name).
**Evidence this is deliberate upstream:** `test/assertions.ts:179-184` ships a
helper documented as *"Get an Array of resources by type, discarding the
resource names"*; 154 of 253 test files use `toHaveResourceWithProperties`;
`bucketName` appears 0 times in bucket-test assertions.

### T4 — coverage claims in our own sourcing docs were wrong in terraconstructs' favour — *our error, recorded to stop it recurring*
`docs/scenario-candidates.md` claimed terraconstructs had no ACM/Route53 L2s.
It does (`PublicCertificate`), and it handles DNS validation record wiring
transparently. Verify coverage against the installed package, never against a
remembered claim.

---

## Filing checklist

Before filing any of the above upstream:
1. Re-verify against the **latest** release, not the pinned one.
2. Produce a minimal repro outside the benchmark.
3. Check the project's existing issues/PRs — several RDS L2s are already in
   stacked PRs, so related gaps may be in flight.
4. Link back to the scenario that surfaced it, so the upstream maintainer can
   see the real-world shape of the problem.
