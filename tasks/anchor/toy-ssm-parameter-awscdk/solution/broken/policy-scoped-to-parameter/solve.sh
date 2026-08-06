#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# the policy-scoped-to-parameter catch: hardcoded wildcard
# Action=["ssm:*","iam:*","s3:*"]/Resource="*", no reference to the
# created parameter's ARN at all. Tier-0 still passes (parameter/trust are
# correct); reward must be 0.0 from tier-1 (policy.guard) alone.
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

    new ssm.StringParameter(this, "Greeting", {
      parameterName: "/cdktn-bench-toy/greeting",
      stringValue: "hello-from-cdktn-bench",
    });

    const role = new iam.Role(this, "Reader", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
    });

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:*", "iam:*", "s3:*"],
        resources: ["*"],
      }),
    );
  }
}
TS

bash tests/static_tiers.sh
