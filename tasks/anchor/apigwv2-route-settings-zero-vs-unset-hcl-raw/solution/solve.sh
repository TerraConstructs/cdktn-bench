#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# Shape: throttling on the prod stage's `default_route_settings`, one of
# the two locations the oracle accepts; the other is a `route_settings`
# block keyed "GET /orders", which no fixture here uses.
#
# function.zip, as in tasks/anchor/
# lambda-log-group-ownership-and-retention-hcl-raw/solution/solve.sh:
# `aws_lambda_function.filename` needs a local file to compute
# source_code_hash/size, this oracle is plan-only (never applies), and
# `terraform plan` succeeds offline against a placeholder with no zip
# structure. This arm's provider mirror carries only hashicorp/aws, so
# `data "archive_file"` is not available here.
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

# Both throttling limits are stated. The rate limit alone would be applied
# with a burst limit of 0, which rejects every request.
resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "prod"
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
