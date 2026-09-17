#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape: `HttpStage` with an explicit `stageName`, carrying both halves of
# `throttle`. `HttpLambdaIntegration` wires the route to the function
# created here and adds the AWS::Lambda::Permission itself, so the
# synthesized IntegrationUri is an `Fn::GetAtt` on that function -- the
# graph edge the tier-1 rule joins on.
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
