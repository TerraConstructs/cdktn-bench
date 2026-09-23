#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and a placeholder Lambda package, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1). Every resource
# hcl_raw writes by hand has a module that authors it: `lambda` builds the
# function, its execution role, its log group and the invoke permission;
# `s3-bucket` the bucket; `s3-bucket//modules/notification` the notification.
# What stays the agent's job is the two edges between them -- which bucket ARN
# scopes the permission, which function the notification targets.
#
# The permission comes from the `lambda` module's `allowed_triggers` rather
# than from the notification submodule's own `create_lambda_permission`,
# because that is the input an agent can get WRONG: `source_arn` is written
# here, not derived. The submodule-authored alternative is equally correct and
# is kept as solution/reference-alt-module-default-permission/.
#
# `create_package = false` keeps the module off its `data "external"` packaging
# path, which shells out to a Python archiver; the plan-only oracle never reads
# the archive, so a placeholder file satisfies source_code_hash.
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

  # 14 is the CloudWatch-valid value nearest the requested 10 days; the
  # provider's own schema rejects 10 at `terraform validate`.
  cloudwatch_logs_retention_in_days = 14

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
