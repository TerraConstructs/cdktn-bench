#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the settings-on-the-wrong-stage catch: the module call
# leaves `stage_name` at its own `$default` and throttles that stage
# correctly, while the `prod` stage the ticket publishes on is a separate
# resource carrying no settings at all. Every value-shaped check passes --
# the numbers are in the artifact and a stage named prod exists -- so reward
# must be 0.0 at tier 1, where the settings are joined to the name of the
# stage carrying them.
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

  stage_default_route_settings = {
    throttling_rate_limit  = 100
    throttling_burst_limit = 200
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

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = module.orders_api.api_id
  name        = "prod"
  auto_deploy = true
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
