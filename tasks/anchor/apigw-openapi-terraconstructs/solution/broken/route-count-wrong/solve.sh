#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates route-count-wrong (2026-08-06, benchmark-integrity
# review finding "An asymmetric tier-1 oracle-strictness break passes
# `make ci` completely"): the reference solution's three routes, PLUS one
# extra, fully-and-correctly-wired DELETE /widgets/{id} method -- its own
# Lambda integration, automatically covered by the deployment's dependency
# edge (idiomatic L2 addMethod, same wiring as the reference solution).
# Every other tier-0/tier-1 fact still holds -- isolating this fixture to
# ONLY oracles/rego/apigw-openapi/policy.rego's `count(methods) != 3`
# denial. Tier-0 asserts still pass; reward must be 0.0 from tier-1 alone.
# Then runs the same tests/static_tiers.sh a real trial's verifier runs.
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
    // BUG: not part of the seeded OpenAPI spec -- exists only to push the
    // total method count to 4, violating route-count-correct.
    const deleteWidgetFn = new compute.LambdaFunction(this, "DeleteWidgetFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 204, body: '' });",
      ),
    });

    // GET /widgets, POST /widgets
    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new compute.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new compute.LambdaIntegration(createWidgetFn));

    // GET /widgets/{id}, and the extra, unrequested DELETE /widgets/{id}
    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new compute.LambdaIntegration(getWidgetFn));
    widget.addMethod("DELETE", new compute.LambdaIntegration(deleteWidgetFn));
  }
}
TS

bash tests/static_tiers.sh
