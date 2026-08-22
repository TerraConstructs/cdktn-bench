#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-retained-on-delete`. The L2
# (`compute.LambdaFunction`) has no `removalPolicy`/`skipDestroy`-shaped
# prop at all on its auto-created log group (verified directly, see this
# scenario's own spec header comment), so there is no way to reach this
# mistake through the L2's own public surface -- this fixture drops to the
# L1 `@cdktn/provider-aws` bindings directly (same escape-hatch convention
# as s3-lambda-log-retention-terraconstructs's own broken fixtures),
# building the log group correctly (right name, right 30-day retention)
# EXCEPT for `skipDestroy: true`. Reward must be 0.0 via tier-0's
# `log-group-not-retained-on-stack-delete-tf` (`skip_destroy` resolves to
# `true`, not `false`/absent).
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

    const fn = new lambdaFunction.LambdaFunction(this, "EventProcessor", {
      provider: this.provider,
      functionName: "event-processor",
      role: role.arn,
      handler: "index.handler",
      runtime: "nodejs22.x",
      filename: "function.zip",
    });

    new cloudwatchLogGroup.CloudwatchLogGroup(this, "EventProcessorLogGroup", {
      provider: this.provider,
      name: `/aws/lambda/${fn.functionName}`,
      retentionInDays: 30,
      skipDestroy: true,
    });
  }
}
TS

bash tests/static_tiers.sh
