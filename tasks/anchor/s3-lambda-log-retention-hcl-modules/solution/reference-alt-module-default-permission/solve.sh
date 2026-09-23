#!/usr/bin/env bash
# A SECOND CORRECT SOLUTION, not a broken fixture: it scores 1.0 and is kept
# because it is the shape the notification submodule's own defaults produce.
#
# `create_lambda_permission` defaults true, so the submodule authors the
# invoke permission itself and scopes it from `local.bucket_arn`
# (modules/notification/main.tf:73) -- the agent never writes a source_arn.
# Two things the plan JSON cannot represent stand between that permission and
# the bucket: a module body's `local` has no representation at all, and the
# permission is `for_each`-expanded. The tier-1 policy therefore resolves the
# edge against this call's own arguments, which is why this shape is a
# reference rather than a documented gap.
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
}

module "uploads_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.uploads.s3_bucket_id
  bucket_arn = module.uploads.s3_bucket_arn

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
