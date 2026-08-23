#!/usr/bin/env bash
# ALTERNATE reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8),
# manually re-runnable; no gate iterates `reference-alt-*` (see
# reference-alt-cdk-roles/solve.sh's own header for that convention).
#
# THE MIXED ATTACHMENT SHAPE. aws-cdk-lib offers two equally documented
# ways to attach a ManagedPolicy this stack creates to a Role this stack
# creates -- `ManagedPolicyProps.roles` (policy side) and
# `role.addManagedPolicy()` (role side) -- and nothing stops a solution
# using one for each role, which is exactly what this file does:
# `roles: [batchRunner]` on the policy, `reportWriter.addManagedPolicy(
# teamMetricsPolicy)` on the other role. Both roles end up carrying the
# team policy; the synthesized template says so outright
# (`TeamMetricsPolicy....Properties.Roles == [{"Ref":"BatchRunnerRole..."}]`
# and `ReportWriterRole....Properties.ManagedPolicyArns` containing
# `{"Ref":"TeamMetricsPolicy..."}`).
#
# This fixture exists because that shape scored reward 0.0 on awscdk and
# 1.0 on terraconstructs for BYTE-IDENTICAL TypeScript until REPAIR PASS 9
# (2026-08-23) -- an arm-parity break in a scenario whose entire output is
# a cross-arm comparison. REPAIR PASS 9 fixed it inside cfn-guard with a
# cardinality equality (a proxy: identity abandoned to make the mixed
# shape pass); REPAIR PASS 10 (2026-08-23) replaced that proxy outright by
# porting this arm's tier-1 to the Rego engine, where the policy->role
# edge is a REAL logical-id join and the mixed shape is correct by
# construction rather than by a balanced count. See
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego's
# `metrics_covered_role_ids` and its header for the full evidence. Verified
# 2026-08-23 against real `cdk synth` output: deny == [], reward 1.0.
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
