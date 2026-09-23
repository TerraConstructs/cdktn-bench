#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point
# 8). Violates the s3-lambda-invoke-permission-scoped catch: the
# `allowed_triggers` entry names the principal and omits `source_arn`, so the
# module plans a permission that grants s3.amazonaws.com account-wide instead
# of this bucket (lambda 8.8.2 main.tf:347,369 -- `try(each.value.source_arn,
# null)`). Everything at tier 0 still passes; reward must be 0.0 from tier 1
# (policy.rego) alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "uploads" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-s3-lambda-log-retention-upload"
}

module "handler" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-s3-lambda-log-retention-handler"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package         = false
  local_existing_package = "function.zip"

  cloudwatch_logs_retention_in_days = 14

  allowed_triggers = {
    S3Upload = {
      principal = "s3.amazonaws.com"
    }
  }
}

module "uploads_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.uploads.s3_bucket_id
  bucket_arn = module.uploads.s3_bucket_arn

  create_lambda_permission = false

  lambda_notifications = {
    handler = {
      function_arn  = module.handler.lambda_function_arn
      function_name = module.handler.lambda_function_name
      events        = ["s3:ObjectCreated:Put"]
    }
  }
}
HCL

bash tests/static_tiers.sh
