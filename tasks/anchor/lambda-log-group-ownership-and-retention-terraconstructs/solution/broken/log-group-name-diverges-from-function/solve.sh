#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-name-diverges-from-function`. The
# L2 (`compute.LambdaFunction`) has no way to rename its own auto-created
# log group at all (verified directly, see this scenario's own spec header
# comment -- `logRetentionInDays` is the ONLY log-group-shaped prop it
# exposes), so this fixture drops to the L1 `@cdktn/provider-aws` bindings
# directly (same escape-hatch convention as
# s3-lambda-log-retention-terraconstructs's own broken fixtures), building
# the log group correctly (matches the `/aws/lambda/...` pattern, 30-day
# retention, not skip_destroy'd) EXCEPT for a hardcoded, mismatched name.
# Reward must be 0.0, caught ONLY at tier 1
# (log-group-governs-the-function-tf /
# oracles/rego/lambda-log-group-ownership-and-retention/policy.rego) --
# every tier-0 assert this scenario declares passes for this exact
# fixture.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, lambdaFunction, cloudwatchLogGroup } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const role = new iamRole.IamRole(this, "EventProcessorRole", {
      provider: this.provider,
      name: "cdktn-bench-event-processor-role",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "lambda.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    });

    new lambdaFunction.LambdaFunction(this, "EventProcessor", {
      provider: this.provider,
      functionName: "event-processor",
      role: role.arn,
      handler: "index.handler",
      runtime: "nodejs22.x",
      filename: "function.zip",
    });

    // Deliberately mismatched: a hardcoded literal, not built from
    // fn.functionName -- passes the tier-0 `^/aws/lambda/` pattern check,
    // fails the tier-1 exact-match check.
    new cloudwatchLogGroup.CloudwatchLogGroup(this, "EventProcessorLogGroup", {
      provider: this.provider,
      name: "/aws/lambda/processor",
      retentionInDays: 30,
    });
  }
}
TS

bash tests/static_tiers.sh
