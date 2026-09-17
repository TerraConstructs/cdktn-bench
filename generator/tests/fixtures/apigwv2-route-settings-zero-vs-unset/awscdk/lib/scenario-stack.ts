// Oracle-CORRECT reference fixture for `make check-paths`
// (generator/check_reference_paths.py): the same shape as
// tasks/anchor/apigwv2-route-settings-zero-vs-unset-awscdk/solution/solve.sh
// writes, so every declared cfn_jsonpath -- tier 0 and tier 1 -- is
// resolved against a real synthesized template.

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
