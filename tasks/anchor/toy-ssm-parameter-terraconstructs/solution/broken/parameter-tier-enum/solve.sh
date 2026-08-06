#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# ONLY the parameter-tier-enum catch (spec's oracle.structural_asserts
# "parameter-tier-standard", tier "0"): explicitly sets tier: "Advanced"
# where the instruction implies the default (Standard, i.e. unset).
# Everything else is identical to solution/solve.sh (still correct), so
# this isolates the one catch -- reward must be 0.0 from tier-0 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, iamRolePolicy, ssmParameter } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const param = new ssmParameter.SsmParameter(this, "Greeting", {
      name: "/cdktn-bench-toy/greeting",
      type: "String",
      value: "hello-from-cdktn-bench",
      tier: "Advanced",
      provider: this.provider,
    });

    const role = new iamRole.IamRole(this, "Reader", {
      provider: this.provider,
      name: "cdktn-bench-toy-ssm-reader",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "ec2.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    });

    new iamRolePolicy.IamRolePolicy(this, "ReaderPolicy", {
      provider: this.provider,
      name: "read-greeting-parameter",
      role: role.id,
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: ["ssm:GetParameter", "ssm:GetParameters"],
            Resource: `arn:*:ssm:*:*:parameter${param.name}`,
          },
        ],
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
