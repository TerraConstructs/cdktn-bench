#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-readonly-missing-on-one-role catch: the AWS
# managed policy AmazonS3ReadOnlyAccess is attached to `batch-runner`
# only -- `reportWriter.addManagedPolicy(s3ReadOnly)` is never called, so
# report-writer has no read access to the reporting data in S3 at all,
# which the ticket's second paragraph asks for on BOTH roles. Everything
# else is byte-identical to solution/solve.sh: both roles exist with the
# right trust principals, the team-defined metrics policy is still
# attached to both, and no exclusive-ownership surface is used anywhere.
# Every tier-0 assert therefore passes exactly as it does for the
# reference solution; reward must be 0.0 from tier-1 alone
# (the awscdk-side bundle's per-role S3 rule -- `%roles { ... }` in
# policy.guard when REPAIR PASS 7 introduced the per-role form, and since
# REPAIR PASS 10 the set difference `iam_role_ids -
# s3_readonly_covered_role_ids` in oracles/rego-cfn/iam-managed-policy-
# exclusive-vs-attachment/policy.rego, which denies naming
# ReportWriterRole's own logical id. Before REPAIR PASS 7's tightening
# this fixture scored reward 1.0, which is the defect it exists to keep
# fixed; see specs/iam-managed-policy-exclusive-vs-attachment.yaml's
# header comment, defect 13).
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
    // THE MISTAKE: only batch-runner gets it. The matching
    // reportWriter.addManagedPolicy(s3ReadOnly) call the reference
    // solution makes is absent, so report-writer never gets the read
    // access the ticket asks for on both roles.
    batchRunner.addManagedPolicy(s3ReadOnly);

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
