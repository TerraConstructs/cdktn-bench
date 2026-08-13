#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), Slice G (apigw-redeploy). Adapted directly from
# tasks/anchor/apigw-openapi-hcl-raw/solution/broken/
# deployment-missing-integration-dependency/solve.sh (same catch): the
# aws_api_gateway_deployment resource has NO `depends_on` at all -- the
# single most commonly cited aws_api_gateway_deployment footgun in
# hand-written Terraform. `triggers` IS present and correct/complete
# (matching solution/solve.sh's own revision-2 hash inputs exactly),
# isolating this fixture to ONLY the depends_on-coverage catch (contrast
# with the sibling stale-deployment-no-triggers/triggers-incomplete-hash
# fixtures, which isolate to the triggers side instead). All three routes
# (/hello, /version, /status), integrations, and permissions are otherwise
# wired correctly. Tier-0 asserts still pass; reward must be 0.0 from
# tier-1 (policy.rego) alone.
#
# OFFLINE-only (gates/oracle_falsifiability.py never sets LIVE=1) -- this
# catch is fully static (structural depends_on coverage), no live proof
# needed to falsify it. Single revision (unlike the sibling fixtures,
# which need two revisions to exercise the triggers-hash side) -- the
# gate only ever grades the FINAL delivered file.
set -euo pipefail

mkdir -p lambda lambda-src

cat > lambda-src/hello.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: "hello" });
JS
cat > lambda-src/version.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: "1.0.0" }) });
JS
( cd lambda-src && cp hello.js index.js && zip -q -X ../lambda/hello.zip index.js && rm index.js )
( cd lambda-src && cp version.js index.js && zip -q -X ../lambda/version.zip index.js && rm index.js )

cat > provider.tf <<'TF'
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.58.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  access_key = "AKIAIOSFODNN7EXAMPLE"
  secret_key = "dummy-secret-key-not-real"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
  skip_metadata_api_check     = true
}
TF

cat > main.tf <<'TF'
resource "aws_iam_role" "lambda_exec" {
  name = "apigw-redeploy-lambda-exec"
  # Amendment 16's flagged gap -- see solution/solve.sh's identical comment.
  path = "/cdktn-bench-task/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "hello" {
  function_name    = "apigw-redeploy-hello"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/hello.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/hello.zip")
}

resource "aws_lambda_function" "version" {
  function_name    = "apigw-redeploy-version"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/version.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/version.zip")
}

resource "aws_api_gateway_rest_api" "api" {
  name = "apigw-redeploy-api"
}

resource "aws_api_gateway_resource" "hello" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "hello"
}

resource "aws_api_gateway_method" "hello_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.hello.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "hello_get" {
  rest_api_id              = aws_api_gateway_rest_api.api.id
  resource_id              = aws_api_gateway_resource.hello.id
  http_method              = aws_api_gateway_method.hello_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.hello.invoke_arn
}

resource "aws_lambda_permission" "hello" {
  statement_id  = "AllowAPIGatewayInvokeHello"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hello.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/hello"
}

resource "aws_api_gateway_resource" "version" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "version"
}

resource "aws_api_gateway_method" "version_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.version.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "version_get" {
  rest_api_id              = aws_api_gateway_rest_api.api.id
  resource_id              = aws_api_gateway_resource.version.id
  http_method              = aws_api_gateway_method.version_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.version.invoke_arn
}

resource "aws_lambda_permission" "version" {
  statement_id  = "AllowAPIGatewayInvokeVersion"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.version.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/version"
}

resource "aws_api_gateway_resource" "status" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "status"
}

resource "aws_api_gateway_method" "status_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.status.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_method_response" "status_get_200" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  status_code = "200"
  response_models = {
    "application/json" = "Empty"
  }
}

resource "aws_api_gateway_integration" "status_get" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  type        = "MOCK"
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_integration_response" "status_get_200" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  status_code = aws_api_gateway_method_response.status_get_200.status_code
  response_templates = {
    "application/json" = jsonencode({ status = "ok", routes = 3 })
  }
}

# BUG: `depends_on` is ENTIRELY OMITTED, and `triggers.redeployment` is a
# HARDCODED LITERAL with no reference to any route's resources at all (a
# real, realistic variant of this mistake: the operator adds a `triggers`
# block because they've heard it's needed, satisfying tier-0's mere
# existence check, but never actually wires it to reference anything --
# so it provides zero real dependency-ordering information, same as
# having none). Every one of the three routes' integrations is therefore
# uncovered by BOTH mechanisms -- the classic API Gateway deployment race
# -- isolating this fixture to ONLY the depends_on/triggers-REFERENCE
# coverage catch (contrast with the sibling stale-deployment-no-triggers,
# whose tier-0 existence check this fixture's literal is specifically
# designed to still pass, and triggers-incomplete-hash, whose depends_on
# IS complete).
resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = "static-placeholder-not-wired-to-any-route"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.this.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "prod"
}

output "api_url" {
  value = "${aws_api_gateway_stage.prod.invoke_url}/"
}
TF

bash tests/static_tiers.sh
