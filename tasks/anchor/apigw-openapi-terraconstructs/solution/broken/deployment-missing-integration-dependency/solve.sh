#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates deployment-missing-integration-dependency: RestApi is
# constructed with `deploy: false` (disabling its automatic
# Deployment/Stage), and a manual, low-level
# apiGatewayDeployment.ApiGatewayDeployment (from @cdktn/provider-aws) is
# created instead with no dependency on any method/integration at all.
# All three routes and every Lambda permission are otherwise wired
# correctly (via the normal LambdaIntegration path), isolating this
# fixture to ONLY the deployment-dependency catch. Hand-verified
# (2026-08-06, `cdktn synth` + `terraform init/plan` against this exact
# file): the synthesized aws_api_gateway_deployment resource's
# `depends_on` is null while 3 correctly-wired
# aws_api_gateway_integration resources exist elsewhere in the same plan.
# Tier-0 asserts still pass; reward must be 0.0 from tier-1 (policy.rego)
# alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { compute } from "terraconstructs/lib/aws";
import { apiGatewayDeployment } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const api = new compute.RestApi(this, "WidgetsApi", {
      restApiName: "widgets-api",
      deploy: false,
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

    const widgets = api.root.addResource("widgets");
    widgets.addMethod("GET", new compute.LambdaIntegration(listWidgetsFn));
    widgets.addMethod("POST", new compute.LambdaIntegration(createWidgetFn));

    const widget = widgets.addResource("{id}");
    widget.addMethod("GET", new compute.LambdaIntegration(getWidgetFn));

    // BUG: manual deployment, no dependency on any of the three methods.
    new apiGatewayDeployment.ApiGatewayDeployment(this, "ManualDeployment", {
      restApiId: api.restApiId,
    });
  }
}
TS

bash tests/static_tiers.sh
