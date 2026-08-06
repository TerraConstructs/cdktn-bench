#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Implements
# all three routes from the seeded openapi/widgets-api.json (GET /widgets,
# POST /widgets, GET /widgets/{id}) via idiomatic L2
# RestApi/addResource/addMethod/LambdaIntegration, which wires the
# deployment's DependsOn AND every Lambda permission automatically (see
# specs/apigw-openapi.yaml's arms.terraconstructs.reason /
# deployment-missing-integration-dependency catch description for the
# aws-cdk-lib source citations backing this). Then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
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

    // GET /widgets, POST /widgets
    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new apigateway.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new apigateway.LambdaIntegration(createWidgetFn));

    // GET /widgets/{id}
    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new apigateway.LambdaIntegration(getWidgetFn));
  }
}
TS

bash tests/static_tiers.sh
