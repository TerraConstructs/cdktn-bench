#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NOT a declared `catches` entry: it is the covering negative
# for a tier-1 RULE the shipped fixture set never exercised, added by
# REPAIR PASS 10 (2026-08-23) with the awscdk Rego port.
#
# The rule it falsifies: the fail-closed existence rule in
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego
# ("the template creates no AWS::IAM::ManagedPolicy resource at all") --
# the port's preservation of the retired policy.guard rule
# `customer_policy_exists_when_roles_present`, which no fixture on any arm
# had ever exercised.
#
# THE MISTAKE: the CloudWatch-metrics permission is granted as an INLINE
# policy on each role (`role.addToPolicy(...)`, an AWS::IAM::Policy
# resource) instead of as the single shared team-defined MANAGED policy
# the ticket asks for. Functionally both roles can publish metrics, so
# every tier-0 assert passes and nothing about trust or S3 access is
# wrong; reward must be 0.0 from tier 1 alone. This is also the shape
# oracle.intent records as a deliberate, documented scope limit on every
# arm ("a single shared INLINE policy is not accepted as the same
# team-defined managed policy"), so this fixture doubles as that limit's
# executable proof.
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

    // THE MISTAKE: an inline policy per role instead of ONE team-defined
    // AWS::IAM::ManagedPolicy shared by both. No AWS::IAM::ManagedPolicy
    // resource exists in the synthesized template at all.
    const metricsStatement = new iam.PolicyStatement({
      actions: ["cloudwatch:PutMetricData"],
      resources: ["*"],
    });
    batchRunner.addToPolicy(metricsStatement);
    reportWriter.addToPolicy(metricsStatement);
  }
}
TS

bash tests/static_tiers.sh
