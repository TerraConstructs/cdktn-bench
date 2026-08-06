#!/usr/bin/env bash
# Deliberately-BAD reference solution -- extra negative fixture added by the
# "tier-1 oracle vacuity -- IAM shape coverage" fix (2026-08-06), alongside
# widening oracles/rego/toy-ssm-parameter/policy.rego (shared by hcl_raw and
# this arm -- both synthesize to plain Terraform, specs/SCHEMA.md §4.2/§8).
# Same shape and same rationale as the hcl_raw sibling fixture in this same
# directory name: a standalone `iamPolicy.IamPolicy` +
# `iamRolePolicyAttachment.IamRolePolicyAttachment` instead of
# `iamRolePolicy.IamRolePolicy` (inline) -- terraconstructs' own L1
# provider-aws bindings expose all three TF resource types directly, so
# this is an equally-idiomatic construct choice, not a contrived one. Tier-0
# still passes (parameter/trust are correct); reward must be 0.0 from
# tier-1 (policy.rego's now-widened policy_resources collection) alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, iamPolicy, iamRolePolicyAttachment, ssmParameter } from "@cdktn/provider-aws";

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

    const admin = new iamPolicy.IamPolicy(this, "AdminPolicy", {
      provider: this.provider,
      name: "admin-policy",
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: "*",
            Resource: "*",
          },
        ],
      }),
    });

    new iamRolePolicyAttachment.IamRolePolicyAttachment(this, "Attach", {
      provider: this.provider,
      role: role.name,
      policyArn: admin.arn,
    });
  }
}
TS

bash tests/static_tiers.sh
