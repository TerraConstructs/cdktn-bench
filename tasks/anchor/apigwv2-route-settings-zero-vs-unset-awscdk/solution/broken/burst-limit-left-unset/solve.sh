#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `burst-limit-left-unset`, THE PLAUSIBLE-WRONG
# SOLUTION: only the sustained rate is configured and the burst half is
# left out. `ThrottleSettings` declares BOTH halves optional
# (aws-cdk-lib 2.263.0 aws-apigatewayv2/lib/common/stage.d.ts:119/124), so
# this type-checks, and the synthesized DefaultRouteSettings carries no
# ThrottlingBurstLimit key at all -- the same production bug the hcl_raw
# fixture reproduces, which is why this catch applies to both arms.
#
# Reward must be 0.0 at TIER 0, via `throttling-burst-is-200`: the absent
# key resolves to zero nodes under the union path and `set_eq [200]` is
# contradicted.
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

    // The burst half is left out: 100 rps sustained is what the ticket
    // asks for, and the spikes clause is not implemented.
    new apigwv2.HttpStage(this, "Prod", {
      httpApi: api,
      stageName: "prod",
      autoDeploy: true,
      throttle: { rateLimit: 100 },
    });
  }
}
TS

bash tests/static_tiers.sh
