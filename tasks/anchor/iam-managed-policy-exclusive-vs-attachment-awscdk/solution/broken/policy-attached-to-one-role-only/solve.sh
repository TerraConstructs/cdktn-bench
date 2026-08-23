#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the policy-attached-to-one-role-only catch: the
# team-defined metrics policy is attached to `batch-runner` only --
# `reportWriter.addManagedPolicy(teamMetricsPolicy)` is never called.
# Tier-0 still passes identically to the reference solution (both roles
# exist with the right trust principals; the S3-readonly policy's own
# attachment is unaffected -- this fixture still attaches it to BOTH
# roles, which the per-role S3 rule has required since REPAIR PASS 7);
# reward must be 0.0 from tier-1 alone -- since REPAIR PASS 10 that is
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego's
# `iam_role_addresses`-shaped set difference `iam_role_ids -
# metrics_covered_role_ids`, which denies naming ReportWriterRole's own
# logical id (verified 2026-08-23 against real `cdk synth` output).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
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
