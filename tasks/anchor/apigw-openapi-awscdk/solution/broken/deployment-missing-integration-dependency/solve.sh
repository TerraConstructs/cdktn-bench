#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates deployment-missing-integration-dependency: RestApi is
# constructed with `deploy: false` (disabling its automatic
# Deployment/Stage, which is what wires DependsOn on every method), and a
# manual, low-level CfnDeployment is created instead with NO DependsOn at
# all -- the classic API Gateway deployment race. All three routes and
# every Lambda permission are otherwise wired correctly (via the normal
# LambdaIntegration path), isolating this fixture to ONLY the
# deployment-dependency catch. Tier-0 asserts still pass (methods, Lambda
# functions, and permissions all exist); reward must be 0.0 from tier-1
# (policy.guard) alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const api = new apigateway.RestApi(this, "WidgetsApi", {
      restApiName: "widgets-api",
      deploy: false,
    });

    const listWidgetsFn = new lambda.Function(this, "ListWidgetsFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'list' });",
      ),
    });
    const createWidgetFn = new lambda.Function(this, "CreateWidgetFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 201, body: 'created' });",
      ),
    });
    const getWidgetFn = new lambda.Function(this, "GetWidgetFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'get' });",
      ),
    });

    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new apigateway.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new apigateway.LambdaIntegration(createWidgetFn));

    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new apigateway.LambdaIntegration(getWidgetFn));

    // BUG: manual deployment, no DependsOn on any of the three methods.
    new apigateway.CfnDeployment(this, "ManualDeployment", {
      restApiId: api.restApiId,
    });
  }
}
TS

bash tests/static_tiers.sh
