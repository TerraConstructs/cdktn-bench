#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NOT a `catches` entry of its own: it is the SAME mistake the
# `policy-attached-to-one-role-only` catch already names, written in a
# different authoring SHAPE (the catch taxonomy records distinct
# MISTAKES, not distinct spellings).
#
# WHY IT EXISTS (REPAIR PASS 10, 2026-08-23): it is the CROSS-ARM CONTROL
# for the awscdk fixture of the same name. That template balanced
# cfn-guard's count-equality proxy at 1 == 1 and scored reward 1.0 while
# leaving report-writer without the team-defined metrics policy -- the
# unsound-in-the-accepting-direction half of the finding that moved the
# awscdk tier-1 onto the Rego engine (specs/SCHEMA.md §4.5). This arm was
# never fooled: its oracle resolves the attachment->role edge for real, so
# BYTE-EQUIVALENT TypeScript has always scored 0.0 here. Shipping both
# halves is what makes "the two arms now agree" a re-runnable fact rather
# than a claim: awscdk 0.0 (since the port) and terraconstructs 0.0.
#
# Verified 2026-08-23, real toolchain (terraconstructs 0.2.13, cdktn
# 0.23.0, terraform 1.15.8 / hashicorp-aws 6.58.0, opa 1.19.0):
# tier0_pass=1, tier1_status=FAIL, reward 0.0, deny naming report-writer's
# own plan address.
#
# Everything else is byte-identical to solution/solve.sh: both roles exist
# with the right trust principals and both carry AmazonS3ReadOnlyAccess,
# so every tier-0 assert passes and reward must be 0.0 from tier 1 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const batchRunner = new iam.Role(this, "BatchRunnerRole", {
      roleName: "batch-runner",
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    const reportWriter = new iam.Role(this, "ReportWriterRole", {
      roleName: "report-writer",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
    });

    // AWS-managed policy: an imported reference (a literal ARN string,
    // never a resource this stack creates). This arm's own
    // fromAwsManagedPolicyName is a 3-arg static (scope, id, name),
    // unlike aws-cdk-lib's newer 1-arg form -- verified against the
    // installed package's own .js, see this file's own header comment.
    const s3ReadOnly = iam.ManagedPolicy.fromAwsManagedPolicyName(
      this,
      "S3ReadOnly",
      "AmazonS3ReadOnlyAccess",
    );
    batchRunner.addManagedPolicy(s3ReadOnly);
    reportWriter.addManagedPolicy(s3ReadOnly);

    // Team-defined policy: a real aws_iam_policy resource, attached
    // additively (aws_iam_role_policy_attachment) to BOTH roles.
    // cloudwatch:PutMetricData has no resource-level ARN in IAM's policy
    // grammar, so resources: ["*"] is the correct, necessary form for
    // this specific action, not a "scoped, not broader" mistake.
    // THE MISTAKE: the team-defined policy reaches batch-runner from BOTH
    // sides of the L2 API at once (`roles: [batchRunner]` on the policy
    // AND `batchRunner.addManagedPolicy(...)` on the role) and never
    // reaches report-writer at all. Belt-and-braces on one role, nothing
    // on the other.
    const teamMetricsPolicy = new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      roles: [batchRunner],
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    batchRunner.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
