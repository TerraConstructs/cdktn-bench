#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# the policy-scoped-to-parameter catch: hardcoded wildcard
# Action=["ssm:*","iam:*","s3:*"]/Resource="*", no reference to the
# created parameter at all -- the exact case named in the finding ("the
# prior verifier proved a wildcard IAM inline_policy... terraconstructs
# case is decidable from plan JSON today"). Tier-0 still passes
# (parameter/trust are correct); reward must be 0.0 from tier-1
# (policy.rego) alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, iamRolePolicy, ssmParameter } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new ssmParameter.SsmParameter(this, "Greeting", {
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
            Action: ["ssm:*", "iam:*", "s3:*"],
            Resource: "*",
          },
        ],
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
