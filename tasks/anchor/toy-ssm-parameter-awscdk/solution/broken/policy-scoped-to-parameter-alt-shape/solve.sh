#!/usr/bin/env bash
# Deliberately-BAD reference solution -- extra negative fixture added by the
# "tier-1 oracle vacuity -- IAM shape coverage" fix (2026-08-06), alongside
# widening oracles/cfn-guard/toy-ssm-parameter/policy.guard. NOT keyed to a
# spec.catches[] name (gates/oracle_falsifiability.py discovers any
# solution/broken/<dir>/ not matching a declared catch name and requires it
# to score 0.0 too, same as a catch-named one) -- this is a SECOND,
# equally-idiomatic way to violate policy-scoped-to-parameter, using
# `inlinePolicies` instead of `role.addToPolicy()`. PROVEN vacuous against
# the pre-fix policy.guard: `new iam.Role(..., { inlinePolicies: {...} })`
# synthesizes ZERO `AWS::IAM::Policy` resources (the wide-open statement
# lands at `AWS::IAM::Role.Properties.Policies[*].PolicyDocument` instead),
# so the old `let iam_policies = Resources.*[ Type == "AWS::IAM::Policy" ]`
# + `when %iam_policies !empty` guard on both rules skipped entirely and
# `cfn-guard validate` returned rc=0 (PASS) on a template granting
# Action=["ssm:*","iam:*","s3:*"]/Resource="*". Tier-0 still passes
# (parameter/trust are correct); reward must be 0.0 from tier-1
# (policy.guard's new inline_policy_* rules) alone.
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

    new iam.Role(this, "Reader", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
      inlinePolicies: {
        admin: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ["ssm:*", "iam:*", "s3:*"],
              resources: ["*"],
            }),
          ],
        }),
      },
    });
  }
}
TS

bash tests/static_tiers.sh
