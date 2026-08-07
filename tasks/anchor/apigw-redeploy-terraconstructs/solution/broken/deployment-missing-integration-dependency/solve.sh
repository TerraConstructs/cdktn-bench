#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), Slice G (apigw-redeploy). Adapted directly from
# tasks/anchor/apigw-openapi-terraconstructs/solution/broken/
# deployment-missing-integration-dependency/solve.sh (same catch, same
# escape-hatch shape). Violates deployment-missing-integration-dependency:
# RestApi is constructed with `deploy: false`, and a manual, low-level
# apiGatewayDeployment.ApiGatewayDeployment (from @cdktn/provider-aws) is
# created instead with no dependency on any method/integration at all.
# All three routes (/hello, /version, /status) are otherwise wired
# correctly, isolating this fixture to ONLY the deployment-dependency
# catch. Tier-0 asserts still pass; reward must be 0.0 from tier-1
# (policy.rego) alone.
#
# OFFLINE-only (gates/oracle_falsifiability.py never sets LIVE=1) -- see
# the awscdk sibling fixture's identical note.
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

    const api = new compute.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deploy: false,
    });

    const helloFn = new compute.LambdaFunction(this, "HelloFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new compute.LambdaFunction(this, "VersionFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new compute.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new compute.LambdaIntegration(versionFn));

    const status = api.root.addResource("status");
    status.addMethod(
      "GET",
      new compute.MockIntegration({
        requestTemplates: { "application/json": '{"statusCode": 200}' },
        passthroughBehavior: compute.PassthroughBehavior.NEVER,
        integrationResponses: [
          {
            statusCode: "200",
            responseTemplates: {
              "application/json": JSON.stringify({ status: "ok", routes: 3 }),
            },
          },
        ],
      }),
      { methodResponses: [{ statusCode: "200" }] },
    );

    // BUG: manual deployment, no dependency on any of the three methods.
    // `triggers` IS set (to a plain literal, no resource reference) --
    // isolates this fixture to ONLY the depends_on-coverage catch: this
    // scenario's deployment-triggers-present tier-0 assert only checks
    // that SOME triggers.redeployment value exists (specs/
    // apigw-redeploy.yaml), so leaving it unset here would make this
    // fixture ALSO fail tier-0, for an unrelated reason, and lose the
    // clean tier-1 attribution this catch (predicted_tier_caught: "1")
    // needs.
    new apiGatewayDeployment.ApiGatewayDeployment(this, "ManualDeployment", {
      restApiId: api.restApiId,
      triggers: { redeployment: "manual-deployment-no-dependency-tracking" },
    });
  }
}
TS

bash tests/static_tiers.sh
