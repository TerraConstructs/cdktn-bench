#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1):
# `terraform-aws-modules/apigateway-v2/aws` 6.1.1 authors the API, the route,
# the integration and the stage from one `routes` map; `terraform-aws-modules/
# lambda/aws` 8.8.2 authors the function and its execution role.
#
# `stage_default_route_settings` is the only location that works here. The
# module emits a `route_settings` block for EVERY route it creates, filling
# each unset limit from the stage default (main.tf:373-383), so per-route
# numbers alone would leave the stage default at the module's own 500/1000
# and the artifact would state two different burst limits.
#
# `aws_lambda_permission` stays raw: routing it through the lambda module's
# `allowed_triggers` would have that call read the API's execution ARN while
# the API call reads the function's ARN, which is a cycle between the two
# module calls. A leaf resource referencing both has no such edge.
#
# function.zip is a placeholder: `local_existing_package` needs a local file
# to hash, this oracle is plan-only, and `terraform plan` succeeds offline
# against a file with no zip structure.
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

  # Both limits are stated. A rate limit alone is applied with a burst limit
  # of 0, which rejects every request.
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

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = module.orders_fn.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.orders_api.api_execution_arn}/*/*"
}
HCL

bash tests/static_tiers.sh
