#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), Slice G (apigw-redeploy). Adapted directly from
# tasks/anchor/apigw-openapi-awscdk/solution/broken/
# deployment-missing-integration-dependency/solve.sh (same catch, same
# escape-hatch shape -- see that file's own header for the full
# rationale). Violates deployment-missing-integration-dependency: RestApi
# is constructed with `deploy: false` (disabling its automatic
# Deployment/Stage, which is what wires DependsOn on every method), and a
# manual, low-level CfnDeployment is created instead with NO DependsOn at
# all -- the classic API Gateway deployment race. All three routes
# (/hello, /version, /status) are otherwise wired correctly, isolating
# this fixture to ONLY the deployment-dependency catch. Tier-0 asserts
# still pass (methods, Lambda function, MOCK/AWS_PROXY integrations all
# exist); reward must be 0.0 from tier-1 (policy.guard) alone.
#
# OFFLINE-only (gates/oracle_falsifiability.py never sets LIVE=1) -- this
# catch is fully static (structural DependsOn coverage), no live proof
# needed to falsify it.
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

    const api = new apigateway.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deploy: false,
    });

    const helloFn = new lambda.Function(this, "HelloFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new lambda.Function(this, "VersionFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new apigateway.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new apigateway.LambdaIntegration(versionFn));

    const status = api.root.addResource("status");
    status.addMethod(
      "GET",
      new apigateway.MockIntegration({
        requestTemplates: { "application/json": '{"statusCode": 200}' },
        passthroughBehavior: apigateway.PassthroughBehavior.NEVER,
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

    // BUG: manual deployment, no DependsOn on any of the three methods.
    new apigateway.CfnDeployment(this, "ManualDeployment", {
      restApiId: api.restApiId,
    });
  }
}
TS

bash tests/static_tiers.sh
