#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the policy-attached-to-one-role-only catch: the
# team-defined metrics policy is attached to `batch-runner` only --
# `reportWriter.addManagedPolicy(teamMetricsPolicy)` is never called.
# Tier-0 still passes identically to the reference solution; reward must
# be 0.0 from tier-1 (policy.rego's `deny` rule) alone.
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

    const s3ReadOnly = iam.ManagedPolicy.fromAwsManagedPolicyName(
      this,
      "S3ReadOnly",
      "AmazonS3ReadOnlyAccess",
    );
    batchRunner.addManagedPolicy(s3ReadOnly);
    reportWriter.addManagedPolicy(s3ReadOnly);

    const teamMetricsPolicy = new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    // Deliberately missing: reportWriter never gets the team policy.
    batchRunner.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
