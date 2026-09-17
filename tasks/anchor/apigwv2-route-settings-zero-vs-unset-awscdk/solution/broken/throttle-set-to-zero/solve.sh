#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `throttle-set-to-zero`: both limits are set to
# `0`, a literal reading of "no burst allowance". The L2 preserves an
# explicit 0 (its branch tests the `throttle` OBJECT, not the numbers), so
# this arm is exposed to the mistake exactly as hcl_raw is.
#
# Reward must be 0.0 at TIER 0, via `throttling-rate-is-100` (resolves {0},
# not {100}) and `throttling-burst-is-200` (resolves {0}, not {200}).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as lambda from "aws-cdk-lib/aws-lambda";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const orders = new lambda.Function(this, "Orders", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ orders: [] }) });",
      ),
    });

    const api = new apigwv2.HttpApi(this, "OrdersApi", { createDefaultStage: false });

    api.addRoutes({
      path: "/orders",
      methods: [apigwv2.HttpMethod.GET],
      integration: new HttpLambdaIntegration("OrdersIntegration", orders),
    });

    // Both limits are 0. Read as "no allowance to exceed", it is read by
    // the service as "allow nothing".
    new apigwv2.HttpStage(this, "Prod", {
      httpApi: api,
      stageName: "prod",
      autoDeploy: true,
      throttle: { rateLimit: 0, burstLimit: 0 },
    });
  }
}
TS

bash tests/static_tiers.sh
