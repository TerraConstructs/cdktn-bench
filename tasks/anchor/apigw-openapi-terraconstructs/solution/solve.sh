#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Implements
# all three routes from the seeded openapi/widgets-api.json (GET /widgets,
# POST /widgets, GET /widgets/{id}) via terraconstructs' L2
# compute.RestApi/addResource/addMethod/LambdaIntegration -- verified
# directly (2026-08-06) to reproduce aws-cdk-lib's own automatic dependency
# wiring byte-for-byte in behavior: `compute.Deployment._addMethodDependency`
# -> `this.node.addDependency(...)` (deployment.js:146-152), invoked from
# `RestApi`'s own addMethod path (restapi.js:614/624) -- same mechanism as
# the awscdk reference solution. Hand-run against this exact file (`cdktn
# synth` + `terraform init/plan`): the synthesized
# aws_api_gateway_deployment's `depends_on` directly lists all three
# aws_api_gateway_integration addresses. Then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const api = new compute.RestApi(this, "WidgetsApi", {
      restApiName: "widgets-api",
    });

    const listWidgetsFn = new compute.LambdaFunction(this, "ListWidgetsFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'list' });",
      ),
    });
    const createWidgetFn = new compute.LambdaFunction(this, "CreateWidgetFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 201, body: 'created' });",
      ),
    });
    const getWidgetFn = new compute.LambdaFunction(this, "GetWidgetFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'get' });",
      ),
    });

    // GET /widgets, POST /widgets
    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new compute.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new compute.LambdaIntegration(createWidgetFn));

    // GET /widgets/{id}
    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new compute.LambdaIntegration(getWidgetFn));
  }
}
TS

bash tests/static_tiers.sh
