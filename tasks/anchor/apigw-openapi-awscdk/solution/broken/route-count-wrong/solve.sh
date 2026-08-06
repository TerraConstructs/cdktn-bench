#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates route-count-wrong (2026-08-06, benchmark-integrity
# review finding "An asymmetric tier-1 oracle-strictness break passes
# `make ci` completely"): the reference solution's three routes, PLUS one
# extra, fully-and-correctly-wired DELETE /widgets/{id} method -- its own
# Lambda integration and permission, automatically covered by the
# deployment's dependency edge (idiomatic L2 addMethod, same wiring as the
# reference solution). Every other tier-0/tier-1 fact still holds (all
# three required routes present and correctly wired, deployment depends on
# every method) -- isolating this fixture to ONLY
# oracles/cfn-guard/apigw-openapi/policy.guard's `route_count_correct`
# rule (4 methods != 3). Tier-0 asserts still pass (none of them count
# nodes -- see specs/apigw-openapi.yaml's oracle.structural_asserts, all
# `exists`/`contains`); reward must be 0.0 from tier-1 alone. Then runs the
# same tests/static_tiers.sh a real trial's verifier runs.
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
    // BUG: not part of the seeded OpenAPI spec -- exists only to push the
    // total method count to 4, violating route-count-correct.
    const deleteWidgetFn = new lambda.Function(this, "DeleteWidgetFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 204, body: '' });",
      ),
    });

    // GET /widgets, POST /widgets
    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new apigateway.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new apigateway.LambdaIntegration(createWidgetFn));

    // GET /widgets/{id}, and the extra, unrequested DELETE /widgets/{id}
    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new apigateway.LambdaIntegration(getWidgetFn));
    widget.addMethod("DELETE", new apigateway.LambdaIntegration(deleteWidgetFn));
  }
}
TS

bash tests/static_tiers.sh
