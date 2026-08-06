#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8; benchmark-
# integrity review finding F2, 2026-08-06). Writes an oracle-CORRECT
# lib/scenario-stack.ts (verified against generator/tests/fixtures/
# toy-ssm-parameter/awscdk/lib/scenario-stack.ts -- byte-identical to it),
# then runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
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
