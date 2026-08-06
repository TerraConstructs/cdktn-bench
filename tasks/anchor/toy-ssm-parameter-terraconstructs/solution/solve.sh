#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8; benchmark-
# integrity review finding F2, 2026-08-06). Writes an oracle-CORRECT
# lib/scenario-stack.ts (verified against generator/tests/fixtures/
# toy-ssm-parameter/terraconstructs/lib/scenario-stack.ts -- byte-identical
# to it), then runs the same tests/static_tiers.sh a real trial's verifier
# runs. Regenerating this scenario will NOT overwrite this file
# (destructive-safe rule).
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
