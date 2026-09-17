#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `burst-limit-left-unset`, THE PLAUSIBLE-WRONG
# SOLUTION: only the sustained rate is configured and the burst half is
# left out. Plans clean, applies clean, and the API then applies the
# omitted burst limit as 0 and 429s every request (tfp-aws#30373).
#
# Reward must be 0.0 at TIER 0, via `throttling-burst-is-200`: the omitted
# attribute is a KNOWN JSON `null` in `planned_values`, not absent, and
# tests/_assert_lib.sh drops nulls, so the union path resolves to [] and
# `set_eq [200]` is contradicted.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
resource "aws_iam_role" "orders" {
  name = "cdktn-bench-orders-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "orders_logs" {
  role       = aws_iam_role.orders.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "orders" {
  function_name = "orders"
  role          = aws_iam_role.orders.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_apigatewayv2_api" "orders" {
  name          = "orders-http-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "orders" {
  api_id                 = aws_apigatewayv2_api.orders.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.orders.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_orders" {
  api_id    = aws_apigatewayv2_api.orders.id
  route_key = "GET /orders"
  target    = "integrations/${aws_apigatewayv2_integration.orders.id}"
}

# The burst half is left out: 100 rps sustained is what the ticket asks
# for, and the spikes clause is not implemented.
resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "prod"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit = 100
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orders.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.orders.execution_arn}/*/*"
}
HCL

bash tests/static_tiers.sh
