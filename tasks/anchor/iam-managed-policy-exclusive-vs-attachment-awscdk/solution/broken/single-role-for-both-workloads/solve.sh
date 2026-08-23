#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NOT a declared `catches` entry: it is the covering negative
# for a tier-1 RULE the shipped fixture set never exercised, added by
# REPAIR PASS 10 (2026-08-23) when the awscdk tier-1 was ported to the
# Rego engine and every rule in the new bundle was audited for a
# falsifying fixture.
#
# The rule it falsifies: `count(iam_role_ids) != 2` in
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego
# (the CFN-side twin of the TF oracle's `count(iam_role_addresses) != 2`).
# ONE iam.Role assumed by an iam.CompositePrincipal of BOTH service
# principals, with both policies attached to it -- so every tier-0 assert
# still PASSES (they are `contains` checks over the flattened union of all
# roles' trust principals, which a single composite-trust role satisfies
# twice over), and reward must be 0.0 from tier 1 alone. This is exactly
# the shape REPAIR PASS 6 hand-built to prove the role-count rule was
# needed but never shipped as a fixture, which is why the rule sat
# unfalsified through three further passes.
#
# It also fires the `roles_trusting_both_ids` rule (one role carrying both
# principals), so the two denies together state the whole defect: the
# ticket asks for two roles with the two trust principals split across
# them, and this template has one role carrying both.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // THE MISTAKE: one shared role for both workloads instead of the two
    // the ticket asks for. Its trust policy names both service
    // principals, which is enough to satisfy both tier-0 `contains`
    // asserts -- the flattening tier-1's per-role rules exist to catch.
    const sharedRole = new iam.Role(this, "SharedRole", {
      roleName: "batch-shared",
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        new iam.ServicePrincipal("lambda.amazonaws.com"),
      ),
    });

    const s3ReadOnly = iam.ManagedPolicy.fromAwsManagedPolicyName(
      "AmazonS3ReadOnlyAccess",
    );
    sharedRole.addManagedPolicy(s3ReadOnly);

    const teamMetricsPolicy = new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    sharedRole.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
