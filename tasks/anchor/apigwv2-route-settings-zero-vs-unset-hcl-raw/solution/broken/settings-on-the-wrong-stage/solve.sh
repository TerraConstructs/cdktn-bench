#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `settings-on-the-wrong-stage`: the throttling
# settings carry the right numbers on a `$default` stage while the `prod`
# stage the ticket publishes on carries none.
#
# Reward must be 0.0 at TIER 1 ONLY. Every tier-0 assert passes: a stage
# named `prod` exists, the route exists, and the union throttling paths are
# stage-blind, so they resolve {100} and {200} from the OTHER stage. The
# tier-1 rule joins the settings to the name of the stage carrying them and
# denies the prod stage, which governs GET /orders with nothing.
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

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "prod"
  auto_deploy = true
}

# The throttling settings ride on the API's default stage instead of the
# one the API is published on.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 100
    throttling_burst_limit = 200
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
