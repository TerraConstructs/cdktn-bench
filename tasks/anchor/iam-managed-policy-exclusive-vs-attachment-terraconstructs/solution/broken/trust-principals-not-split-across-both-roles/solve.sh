#!/usr/bin/env bash
# BROKEN fixture for the `trust-principals-not-split-across-both-roles`
# catch -- HAND-AUTHORED (SCHEMA.md §8.2 point 8).
#
# Two roles still exist, both policies are still attached additively to
# both of them, and no exclusive-ownership surface is used anywhere -- so
# every tier-0 assert passes. What is wrong is the PAIRING the ticket
# states: the ticket asks for `batch-runner`, assumed by ECS tasks, AND
# `report-writer`, assumed by Lambda. Here the FIRST role is made
# assumable by both ECS tasks and Lambda, and the second by Step Functions
# instead -- so the role meant to be assumed by Lambda cannot be assumed by
# Lambda at all, while the flattened union of both roles' trust principals
# still contains both service names.
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
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        new iam.ServicePrincipal("lambda.amazonaws.com"),
      ),
    });

    const reportWriter = new iam.Role(this, "ReportWriterRole", {
      roleName: "report-writer",
      assumedBy: new iam.ServicePrincipal("states.amazonaws.com"),
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
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    batchRunner.addManagedPolicy(teamMetricsPolicy);
    reportWriter.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
