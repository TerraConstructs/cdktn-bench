#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the throttle-set-to-zero catch: both limits are stated
# as 0, a literal reading of "no burst allowance". An explicit 0 is present
# where the module's `optional(number, 500)` default would have filled 500,
# so `0` survives into the stage's default and per-route settings alike and
# the deployed API rejects every request. Reward must be 0.0 at tier 0 via
# throttling-rate-is-100 and throttling-burst-is-200, both resolving {0}.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "orders_fn" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "orders"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package         = false
  local_existing_package = "function.zip"
}

module "orders_api" {
  source  = "terraform-aws-modules/apigateway-v2/aws"
  version = "6.1.1"

  name          = "orders-http-api"
  protocol_type = "HTTP"

  create_domain_name = false

  stage_name = "prod"

  stage_default_route_settings = {
    throttling_rate_limit  = 0
    throttling_burst_limit = 0
  }

  routes = {
    "GET /orders" = {
      integration = {
        uri                    = module.orders_fn.lambda_function_arn
        payload_format_version = "2.0"
      }
    }
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = module.orders_fn.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.orders_api.api_execution_arn}/*/*"
}
HCL

bash tests/static_tiers.sh
