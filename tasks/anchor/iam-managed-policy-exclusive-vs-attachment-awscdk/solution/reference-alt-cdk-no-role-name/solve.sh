#!/usr/bin/env bash
# Reference-ALT solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). NOT a
# negative fixture and NOT a declared catch: like this arm's other
# `reference-alt-*` directories it is a manually re-runnable proof that a
# DIFFERENT, equally correct authoring decision also scores reward 1.0.
#
# WHAT IT PROVES (binding operator ruling 1, 2026-08-22: a physical
# resource NAME is never load-bearing in this oracle -- identity is
# existence + type + properties, keyed on the plan ADDRESS on the
# TF-shaped arms and the template LOGICAL ID here): this is
# solution/solve.sh with the two `roleName:` lines DELETED, so CDK
# computes both roles' physical names. It must score exactly what
# solve.sh scores, and it does.
#
# WHY IT IS SHIPPED (REPAIR PASS 10, 2026-08-23): this exact authoring
# decision is the shape an adversarial verifier used to demonstrate an
# arm-parity break -- it scored 1.0 here and 0.0 on terraconstructs and
# hcl_raw (whose oracle keyed role identity on `.planned_values...
# values.name`), with two deny messages the graded plan contradicted.
# REPAIR PASSES 7-9 fixed the TF side; the claim that "no rule reads a
# role name" had until now only ever been asserted for this arm, never
# shipped as a re-runnable proof. Its siblings are
# `reference-alt-tcons-no-role-name/` and `reference-alt-hcl-no-role-name/`
# on the other two arms -- the same authoring decision, three arms, so
# the parity claim is checkable by running three commands.
#
# Verified 2026-08-23, real toolchain (aws-cdk-lib 2.263.0, aws-cdk
# 2.1135.0, opa 1.19.0): tier0_pass=1, tier1_status=PASS, deny == [],
# reward 1.0 -- identical to solution/solve.sh, and identical to the two
# sibling proofs on the other arms.
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
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    const reportWriter = new iam.Role(this, "ReportWriterRole", {
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
