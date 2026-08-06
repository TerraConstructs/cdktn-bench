#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# ONLY the parameter-tier-enum catch (spec's oracle.structural_asserts
# "parameter-tier-standard", tier "0"): explicitly sets
# tier: ssm.ParameterTier.ADVANCED where the instruction implies the
# default (Standard, i.e. unset). Everything else is identical to
# solution/solve.sh (still correct), so this isolates the one catch --
# reward must be 0.0 from tier-0 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as ssm from "aws-cdk-lib/aws-ssm";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const param = new ssm.StringParameter(this, "Greeting", {
      parameterName: "/cdktn-bench-toy/greeting",
      stringValue: "hello-from-cdktn-bench",
      tier: ssm.ParameterTier.ADVANCED,
    });

    const role = new iam.Role(this, "Reader", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
    });

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [param.parameterArn],
      }),
    );
  }
}
TS

bash tests/static_tiers.sh
