#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-retained-on-delete`: the log group
# is otherwise identical to the reference solution (right name, right
# 30-day retention) but omits `removalPolicy` -- which is NOT a neutral
# omission: `logs.LogGroup`'s own L2 default is `RemovalPolicy.Retain`
# (verified directly, see this scenario's own spec header comment), so
# leaving it unset is exactly this mistake, not a no-op. Reward must be
# 0.0 via tier-0's `log-group-not-retained-on-stack-delete-cfn`
# (DeletionPolicy resolves to "Retain", not "Delete").
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const functionName = "event-processor";

    const logGroup = new logs.LogGroup(this, "EventProcessorLogGroup", {
      logGroupName: `/aws/lambda/${functionName}`,
      retention: logs.RetentionDays.ONE_MONTH,
      // removalPolicy deliberately omitted -- defaults to RemovalPolicy.Retain.
    });

    new lambda.Function(this, "EventProcessor", {
      functionName,
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
      logGroup,
    });
  }
}
TS

bash tests/static_tiers.sh
