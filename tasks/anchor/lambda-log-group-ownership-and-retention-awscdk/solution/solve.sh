#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape: `logs.LogGroup` created explicitly (name = `/aws/lambda/<function
# name>`, retention = ONE_MONTH, removalPolicy = DESTROY -- overriding the
# L2's own default of RETAIN, see specs/lambda-log-group-ownership-and-
# retention.yaml's header comment for why that default matters), passed
# into `lambda.Function`'s own `logGroup` prop -- the modern, recommended
# path (aws-cdk#35003, "migrate from logRetention to logGroup"). The
# deprecated `logRetention` prop is never used.
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
      removalPolicy: cdk.RemovalPolicy.DESTROY,
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
