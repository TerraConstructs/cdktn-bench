#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point
# 8). Violates the log-retention-not-a-valid-enum-value catch: the
# instruction's literal "10 days" is passed straight through the module.
#
# `cloudwatch_logs_retention_in_days` is an unvalidated passthrough
# (variables.tf:455) onto `aws_cloudwatch_log_group.retention_in_days`
# (main.tf:280), so the module changes nothing: the provider's own schema
# rejects 10 with the same allowed-values message hcl_raw gets. It lands at
# `terraform plan` rather than `terraform validate` -- the value only reaches
# the resource once the module variable is resolved -- which is still a failed
# toolchain step, so the verifier writes reward=0.0 before any assert runs.
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

  cloudwatch_logs_retention_in_days = 10

  allowed_triggers = {
    S3Upload = {
      principal  = "s3.amazonaws.com"
      source_arn = module.uploads.s3_bucket_arn
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
