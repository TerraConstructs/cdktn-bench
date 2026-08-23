#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against aws-cdk-lib 2.263.0 (the pinned version,
# local clone read at authoring time): `role.addManagedPolicy(policy)`
# (aws-iam/lib/role.ts) renders each attached policy's ARN into the
# role's own `ManagedPolicyArns` CFN property -- CloudFormation's ONE
# attachment surface, no separate attachment resource type exists to
# reach for. `iam.ManagedPolicy.fromAwsManagedPolicyName(...)` returns an
# IMPORTED reference (a literal ARN string, arn:aws:iam::aws:policy/
# AmazonS3ReadOnlyAccess) -- no new resource in the template. A real
# `new iam.ManagedPolicy(...)` DOES synthesize a standalone
# AWS::IAM::ManagedPolicy resource, GetAtt-referenced from both roles'
# ManagedPolicyArns.
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

    // AWS-managed policy: an IMPORTED reference (a literal ARN string),
    // never a resource this stack creates. addManagedPolicy() renders it
    // straight into each role's own ManagedPolicyArns list -- additive,
    // CloudFormation's only attachment surface.
    const s3ReadOnly = iam.ManagedPolicy.fromAwsManagedPolicyName(
      "AmazonS3ReadOnlyAccess",
    );
    batchRunner.addManagedPolicy(s3ReadOnly);
    reportWriter.addManagedPolicy(s3ReadOnly);

    // Team-defined policy: a REAL AWS::IAM::ManagedPolicy resource this
    // stack creates, attached to BOTH roles (each role's ManagedPolicyArns
    // gets a GetAtt entry pointing at it). cloudwatch:PutMetricData has no
    // resource-level ARN in IAM's policy grammar (a CloudWatch metrics
    // limitation, not a "scoped, not broader" mistake -- there is no
    // narrower Resource to write), so Resource: "*" is the correct,
    // necessary form for this specific action.
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
