#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `settings-on-the-wrong-stage`: the throttled
# stage construct is the one whose `stageName` was never set, and
# `HttpStage`'s `stageName` DEFAULTS to `$default`
# (aws-cdk-lib 2.263.0 aws-apigatewayv2/lib/http/stage.d.ts's own @default
# tag), so the numbers land on `$default` while `prod` carries none.
#
# Reward must be 0.0 at TIER 1 ONLY. Every tier-0 assert passes: a stage
# named `prod` exists, the route exists, and the union throttling paths are
# stage-blind, so they resolve {100} and {200} from the OTHER stage. The
# tier-1 rule joins the settings to the name of the stage carrying them and
# denies the prod stage, which governs GET /orders with nothing.
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

    new apigwv2.HttpStage(this, "Prod", {
      httpApi: api,
      stageName: "prod",
      autoDeploy: true,
    });

    // No `stageName`, so this throttles `$default` rather than the stage
    // the API is published on.
    new apigwv2.HttpStage(this, "Throttled", {
      httpApi: api,
      autoDeploy: true,
      throttle: { rateLimit: 100, burstLimit: 200 },
    });
  }
}
TS

bash tests/static_tiers.sh
