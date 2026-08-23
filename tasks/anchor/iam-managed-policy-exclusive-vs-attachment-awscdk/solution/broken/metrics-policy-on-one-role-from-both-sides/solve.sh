#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NOT a `catches` entry of its own: it is the SAME mistake the
# `policy-attached-to-one-role-only` catch already names (the team-defined
# policy reaches one of the two roles), written in a different authoring
# SHAPE -- and the catch taxonomy records distinct MISTAKES, not distinct
# spellings, exactly as hcl_raw's `foreach-roles-metrics-on-one-role-only`
# and `cartesian-metrics-on-one-role-only` fixtures already are.
#
# WHY IT EXISTS (REPAIR PASS 10, 2026-08-23): this is the shape that
# PROVES cfn-guard's count-equality proxy was unsound in the ACCEPTING
# direction, which is half of the finding that moved this arm's tier-1
# onto the Rego engine. REPAIR PASS 9's rule was
#   count(roles whose own ManagedPolicyArns carries NO Ref at all)
#     == count(every in-template ManagedPolicy's Roles entries)
# and this template balances it at 1 == 1: batch-runner's own
# ManagedPolicyArns DOES carry a Ref (so it is not counted on the left),
# report-writer's does not (so the left side is 1), and the policy's own
# Roles list names exactly one role (so the right side is 1). REPRODUCED
# DIRECTLY, 2026-08-23, real toolchain (aws-cdk-lib 2.263.0, cfn-guard
# 3.2.0): `cfn-guard validate` exit 0 -- reward 1.0 for a solution that
# leaves report-writer without the team-defined metrics policy the ticket
# asks for on both roles. A count cannot see WHICH role it counted; that
# is the whole reason specs/SCHEMA.md §4.5 exists.
#
# UNDER THE PORTED BUNDLE (oracles/rego-cfn/iam-managed-policy-exclusive-
# vs-attachment/policy.rego) the same template denies, because
# `metrics_covered_role_ids` resolves the edge by LOGICAL ID and unions
# the two attachment shapes onto the SAME role instead of counting them:
# covered == {BatchRunnerRole002E307A}, missing ==
# {ReportWriterRole4EB64C04}. Verified 2026-08-23: tier0_pass=1,
# tier1_status=FAIL, reward 0.0. The terraconstructs analog --
# solution/broken/metrics-policy-on-one-role-from-both-sides/ on that arm,
# byte-equivalent TypeScript -- scores 0.0 too, which is the cross-arm
# half of the proof.
#
# Everything else is byte-identical to solution/solve.sh: both roles exist
# with the right trust principals and both carry AmazonS3ReadOnlyAccess,
# so every tier-0 assert passes and reward must be 0.0 from tier 1 alone.
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
    // THE MISTAKE: the team-defined policy reaches batch-runner from BOTH
    // sides of aws-cdk-lib's API at once (`roles: [batchRunner]` on the
    // policy AND `batchRunner.addManagedPolicy(...)` on the role) and
    // never reaches report-writer at all. Belt-and-braces on one role,
    // nothing on the other.
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
