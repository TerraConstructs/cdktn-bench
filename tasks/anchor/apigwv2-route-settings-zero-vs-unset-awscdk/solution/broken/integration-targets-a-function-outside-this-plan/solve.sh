#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch
# `integration-targets-a-function-outside-this-plan`: the integration is
# built from `lambda.Function.fromFunctionArn(...)`, an IMPORTED function,
# so IntegrationUri synthesizes as a plain ARN string rather than an
# `Fn::GetAtt` on the function this stack creates -- which is left unwired.
# Every value-shaped check passes; the deployed endpoint answers 500.
#
# Reward must be 0.0 at TIER 1 ONLY. Every tier-0 assert passes: the
# integration exists and is AWS_PROXY, the route and prod stage exist, and
# the throttling values are correct. The tier-1 rule walks route ->
# integration -> function over the artifact's own reference graph and finds
# the integration reaching no function this artifact creates.
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
      integration: new HttpLambdaIntegration(
        "OrdersIntegration",
        lambda.Function.fromFunctionArn(
          this,
          "OrdersImported",
          "arn:aws:lambda:us-east-1:123456789012:function:orders",
        ),
      ),
    });

    // Both halves of `throttle` are optional in the type, and a rate limit
    // supplied alone is deployed with a burst limit of 0, which rejects
    // every request.
    new apigwv2.HttpStage(this, "Prod", {
      httpApi: api,
      stageName: "prod",
      autoDeploy: true,
      throttle: { rateLimit: 100, burstLimit: 200 },
    });
  }
}
TS

bash tests/static_tiers.sh
