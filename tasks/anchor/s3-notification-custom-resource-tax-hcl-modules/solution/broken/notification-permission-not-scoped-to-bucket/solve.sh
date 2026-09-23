#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point
# 8). Violates the notification-permission-not-scoped-to-bucket catch: the
# `allowed_triggers` entry names the principal and omits `source_arn`, so the
# module plans a permission granting s3.amazonaws.com account-wide rather than
# this bucket (lambda 8.8.2 main.tf:347,369 -- `try(each.value.source_arn,
# null)`). Every tier-0 check still passes; reward must be 0.0 from tier 1
# (policy.rego) alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "claims" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-s3-notification-custom-resource-tax-claims"
}

module "processor" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-s3-notification-custom-resource-tax-processor"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package         = false
  local_existing_package = "function.zip"

  allowed_triggers = {
    ClaimsUpload = {
      principal = "s3.amazonaws.com"
    }
  }
}

module "claims_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.claims.s3_bucket_id
  bucket_arn = module.claims.s3_bucket_arn

  create_lambda_permission = false

  lambda_notifications = {
    processor = {
      function_arn  = module.processor.lambda_function_arn
      function_name = module.processor.lambda_function_name
      events        = ["s3:ObjectCreated:Put"]
    }
  }
}
HCL

bash tests/static_tiers.sh
