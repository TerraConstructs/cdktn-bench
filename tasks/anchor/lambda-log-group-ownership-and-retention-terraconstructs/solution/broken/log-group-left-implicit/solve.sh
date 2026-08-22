#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-left-implicit`. This L2
# (`compute.LambdaFunction`) always creates its own log group (verified
# directly, see this scenario's own spec header comment) -- there is no way
# to omit it through the L2's own public surface, so this fixture drops to
# the L1 `@cdktn/provider-aws` `lambdaFunction.LambdaFunction` +
# `iamRole.IamRole` directly (same escape-hatch convention as
# s3-lambda-log-retention-terraconstructs's own broken fixtures) and
# declares no log group resource at all. Reward must be 0.0 via tier-0's
# `log-group-exists` (0 resolved nodes).
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, lambdaFunction } from "@cdktn/provider-aws";

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
  }
}
TS

bash tests/static_tiers.sh
