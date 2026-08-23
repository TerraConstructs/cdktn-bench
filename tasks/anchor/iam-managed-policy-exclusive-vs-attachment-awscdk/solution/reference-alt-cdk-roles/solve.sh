#!/usr/bin/env bash
# ALTERNATE reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8,
# mirroring the hcl_raw arm's `reference-alt-exclusive` convention). NOT
# wired into any gate automatically (gates/oracle_falsifiability.py and
# gates/grading_proof.py only run `solution/solve.sh` and
# `solution/broken/<catch-name>/solve.sh`) -- kept here as a manually
# re-runnable proof that declaring the team-defined policy's roles ON THE
# POLICY (`ManagedPolicyProps.roles`) ALSO scores reward 1.0, per the
# REPAIR PASS 3 fix to the awscdk-side tier-1 bundle's
# `customer_policy_attached_to_both_roles` rule -- which lived in
# oracles/cfn-guard/.../policy.guard until REPAIR PASS 10 (2026-08-23)
# ported this arm's tier-1 onto the Rego engine, where the same fact is
# `metrics_covered_role_ids`'s policy-side half in
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego
# (see that file's header for the full before/after evidence:
# this exact shape scored reward 0.0 before the fix, an adversarial-
# verifier-caught arm-parity break against terraconstructs, which was
# always immune -- ManagedPolicy.attachToRole() on that arm always emits
# the additive per-role attachment resource regardless of which side of
# the API a solution author calls).
#
# Uses `new iam.ManagedPolicy(this, "TeamMetricsPolicy", { roles: [...],
# statements: [...] })` -- aws-cdk-lib's own `ManagedPolicyProps.roles`
# prop -- instead of `role.addManagedPolicy(teamMetricsPolicy)` on each
# role. Both synthesize a real, standalone AWS::IAM::ManagedPolicy
# resource; this shape's `Properties.Roles` list carries both role Refs
# directly, rather than each role's own `ManagedPolicyArns` list carrying
# a Ref back to the policy. Verified manually, 2026-08-21, via the same
# host-sandbox technique gates/oracle_falsifiability.py uses: real
# `cdk synth` (aws-cdk-lib 2.263.0) + this scenario's own
# tests/static_tiers.sh -> tier0_pass=1, tier1_status=PASS, reward=1.0.
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

    // Team-defined policy: same real AWS::IAM::ManagedPolicy resource as
    // solution/solve.sh's reference shape, but with both roles declared
    // ON THE POLICY itself (ManagedPolicyProps.roles) instead of via
    // role.addManagedPolicy() on each role -- an equally idiomatic,
    // equally documented aws-cdk-lib API for the exact same outcome.
    new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      roles: [batchRunner, reportWriter],
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
  }
}
TS

bash tests/static_tiers.sh
