#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NOT a declared `catches` entry: it is the covering negative
# for a tier-1 RULE the shipped fixture set never exercised, added by
# REPAIR PASS 10 (2026-08-23) with the awscdk Rego port.
#
# The rule it falsifies: `count(ecs_trusting_role_ids) == 0` in
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego.
# Both roles trust lambda.amazonaws.com, so the role the ticket
# describes as assumed by ECS tasks cannot be assumed by ECS tasks at all.
# (The tier-0 `role-trusts-ecs-tasks-service` assert fails here too -- this
# fixture is not claiming a tier-1-only catch; it exists so the tier-1
# rule itself has an executable falsification instead of only a prose
# claim that it would fire.)
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // THE MISTAKE: batch-runner is assumed by Lambda too, so no role in
    // this template can be assumed by ECS tasks.
    const batchRunner = new iam.Role(this, "BatchRunnerRole", {
      roleName: "batch-runner",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
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
    batchRunner.addManagedPolicy(teamMetricsPolicy);
    reportWriter.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
