#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates route-count-wrong (2026-08-06, benchmark-integrity
# review finding "An asymmetric tier-1 oracle-strictness break passes
# `make ci` completely"): the reference solution's three routes, PLUS one
# extra, fully-and-correctly-wired DELETE /widgets/{id} method -- its own
# lambda function, AWS_PROXY integration, and lambda permission, and
# INCLUDED in the deployment's `depends_on`/`triggers` (same shape as the
# other three). Every other tier-0/tier-1 fact still holds (all three
# required routes present and correctly wired, deployment depends on every
# method/integration) -- isolating this fixture to ONLY
# oracles/rego/apigw-openapi/policy.rego's `count(methods) != 3` denial.
# Tier-0 asserts still pass (none of them count nodes); reward must be 0.0
# from tier-1 alone. Then runs the same tests/static_tiers.sh a real
# trial's verifier runs.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_api_gateway_rest_api" "widgets" {
  name = "widgets-api"
}

resource "aws_api_gateway_resource" "widgets" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id
  parent_id   = aws_api_gateway_rest_api.widgets.root_resource_id
  path_part   = "widgets"
}

resource "aws_api_gateway_resource" "widget" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id
  parent_id   = aws_api_gateway_resource.widgets.id
  path_part   = "{id}"
}

resource "aws_iam_role" "lambda_exec" {
  name = "widgets-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "list_widgets" {
  function_name = "list-widgets"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_lambda_function" "create_widget" {
  function_name = "create-widget"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_lambda_function" "get_widget" {
  function_name = "get-widget"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

# BUG: not part of the seeded OpenAPI spec -- exists only to push the total
# aws_api_gateway_method count to 4, violating route-count-correct.
resource "aws_lambda_function" "delete_widget" {
  function_name = "delete-widget"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_api_gateway_method" "list_widgets" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "list_widgets" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widgets.id
  http_method              = aws_api_gateway_method.list_widgets.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.list_widgets.invoke_arn
}

resource "aws_api_gateway_method" "create_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "create_widget" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widgets.id
  http_method              = aws_api_gateway_method.create_widget.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.create_widget.invoke_arn
}

resource "aws_api_gateway_method" "get_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widget.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_widget" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widget.id
  http_method              = aws_api_gateway_method.get_widget.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.get_widget.invoke_arn
}

# BUG (continued): the extra, unrequested fourth method/integration.
resource "aws_api_gateway_method" "delete_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widget.id
  http_method   = "DELETE"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "delete_widget" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widget.id
  http_method              = aws_api_gateway_method.delete_widget.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.delete_widget.invoke_arn
}

resource "aws_lambda_permission" "list_widgets" {
  statement_id  = "AllowAPIGatewayInvokeListWidgets"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_widgets.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets"
}

resource "aws_lambda_permission" "create_widget" {
  statement_id  = "AllowAPIGatewayInvokeCreateWidget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_widget.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/POST/widgets"
}

resource "aws_lambda_permission" "get_widget" {
  statement_id  = "AllowAPIGatewayInvokeGetWidget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.get_widget.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets/*"
}

resource "aws_lambda_permission" "delete_widget" {
  statement_id  = "AllowAPIGatewayInvokeDeleteWidget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.delete_widget.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/DELETE/widgets/*"
}

resource "aws_api_gateway_deployment" "widgets" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_integration.list_widgets.id,
      aws_api_gateway_integration.create_widget.id,
      aws_api_gateway_integration.get_widget.id,
      aws_api_gateway_integration.delete_widget.id,
    ]))
  }

  depends_on = [
    aws_api_gateway_integration.list_widgets,
    aws_api_gateway_integration.create_widget,
    aws_api_gateway_integration.get_widget,
    aws_api_gateway_integration.delete_widget,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.widgets.id
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  stage_name    = "prod"
}
TF

bash tests/static_tiers.sh
