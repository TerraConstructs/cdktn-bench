#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the integration-targets-a-function-outside-this-plan
# catch: the route's integration URI is a hand-typed ARN naming a function
# nothing here creates, while the function this configuration does create is
# left unwired. The integration exists, is AWS_PROXY, and its URI is a
# syntactically valid Lambda ARN, so every value-shaped check passes; reward
# must be 0.0 at tier 1, where the route -> integration -> function walk
# finds the URI carries a constant and reaches nothing in this plan.
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
    throttling_rate_limit  = 100
    throttling_burst_limit = 200
  }

  routes = {
    "GET /orders" = {
      integration = {
        uri                    = "arn:aws:lambda:us-east-1:123456789012:function:orders-elsewhere"
        payload_format_version = "2.0"
      }
    }
  }
}
HCL

bash tests/static_tiers.sh
