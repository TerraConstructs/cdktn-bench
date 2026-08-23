#!/usr/bin/env bash
# ALTERNATE reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8,
# mirroring the `reference-alt-cdk-roles` convention already used in this
# arm's own solution/ tree). NOT wired into any gate automatically
# (gates/oracle_falsifiability.py and gates/grading_proof.py only run
# `solution/solve.sh` and `solution/broken/<catch-name>/solve.sh`) --
# kept here as a manually re-runnable proof that importing the
# AWS-managed policy via a LITERAL ARN string, instead of by name, ALSO
# scores reward 1.0.
#
# ADDED IN REPAIR PASS 4 (2026-08-22, adversarial-verifier finding --
# see specs/iam-managed-policy-exclusive-vs-attachment.yaml's own header
# comment, defect 9; since REPAIR PASS 10 the rule lives in
# oracles/rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego
# as `entry_is_s3_readonly`, whose single suffix match accepts this
# render, the Fn::Join render and an Fn::Sub one alike -- see that file's
# own header comment for the full evidence trail): `iam.ManagedPolicy.
# fromManagedPolicyArn(this, id, "arn:aws:iam::aws:policy/
# AmazonS3ReadOnlyAccess")` is a first-class, equally-documented,
# equally-idiomatic aws-cdk-lib import spelling to
# `fromAwsManagedPolicyName("AmazonS3ReadOnlyAccess")` (this scenario's
# own solution/solve.sh) -- it synthesizes a BARE literal ARN string in
# ManagedPolicyArns instead of a partition-templated Fn::Join/Ref
# construction, since the caller already supplied the full ARN including
# partition. Before this repair pass, both the tier-0
# `s3-readonly-policy-attached-cfn` assert (since retired) and tier-1's
# `s3_readonly_attached_to_a_role` rule were keyed exclusively to the
# Fn::Join render, so this equally-correct shape scored reward 0.0 --
# an arm-parity break, since the same import choice is unremarkable on
# the TF-shaped arms (a literal ARN string is simply the ONLY way
# `policy_arn`/`policy_arns` is ever written there). Verified manually,
# 2026-08-22, via the same host-sandbox technique
# gates/oracle_falsifiability.py uses: real `cdk synth` (aws-cdk-lib
# 2.263.0) + this scenario's own tests/static_tiers.sh -> tier0_pass=1,
# tier1_status=PASS, reward=1.0.
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

    // AWS-managed policy: imported by its LITERAL ARN (a fully-qualified
    // string, partition included) rather than by name -- a different,
    // equally first-class aws-cdk-lib import method. Still an IMPORTED
    // reference, never a resource this stack creates; addManagedPolicy()
    // renders it straight into each role's own ManagedPolicyArns list --
    // additive, CloudFormation's only attachment surface.
    const s3ReadOnly = iam.ManagedPolicy.fromManagedPolicyArn(
      this,
      "S3ReadOnlyImport",
      "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    );
    batchRunner.addManagedPolicy(s3ReadOnly);
    reportWriter.addManagedPolicy(s3ReadOnly);

    // Team-defined policy: a REAL AWS::IAM::ManagedPolicy resource this
    // stack creates, attached to BOTH roles (each role's ManagedPolicyArns
    // gets a Ref entry pointing at it). cloudwatch:PutMetricData has no
    // resource-level ARN in IAM's policy grammar, so Resource = "*" is the
    // correct, necessary form for this specific action.
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
