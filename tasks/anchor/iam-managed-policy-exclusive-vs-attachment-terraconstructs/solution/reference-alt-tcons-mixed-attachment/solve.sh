#!/usr/bin/env bash
# ALTERNATE reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8),
# manually re-runnable; no gate iterates `reference-alt-*`.
#
# The terraconstructs half of the MIXED ATTACHMENT SHAPE cross-arm control
# (see the awscdk arm's reference-alt-cdk-mixed-attachment/solve.sh, which
# is the byte-equivalent TypeScript): the team-defined ManagedPolicy names
# ONE role through its `roles:` prop while the OTHER role attaches itself
# with `addManagedPolicy()`. This arm was always immune -- its L2 emits an
# additive per-role IamRolePolicyAttachment whichever side of the API the
# author calls -- which is exactly why it is the control that made the
# awscdk-side parity break (fixed in REPAIR PASS 9, 2026-08-23) visible.
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
    const teamMetricsPolicy = new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      roles: [batchRunner],
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    reportWriter.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
