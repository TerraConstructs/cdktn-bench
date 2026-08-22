#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `retention-via-deprecated-log-retention-prop`:
# the attractive, typed, autocompleted `logRetention` prop. Verified
# directly against aws-cdk-lib 2.263.0 (see this scenario's own spec
# header comment): this provisions a `Custom::LogRetention` custom
# resource instead of a plain `AWS::Logs::LogGroup`, whose own default
# removal policy is RETAIN. Reward must be 0.0 via tier-0's
# `no-log-retention-custom-resource` (a `Custom::LogRetention` resource
# exists, which this scenario's oracle requires to be absent).
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

    new lambda.Function(this, "EventProcessor", {
      functionName: "event-processor",
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
      logRetention: logs.RetentionDays.ONE_MONTH,
    });
  }
}
TS

bash tests/static_tiers.sh
