#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and a placeholder Lambda package, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): `lambda` authors
# the function and its role, `s3-bucket` the bucket, and
# `s3-bucket//modules/notification` the notification. The platform constraint
# costs this arm nothing -- Terraform's provider has a first-class
# notification resource, so no module here provisions a helper function.
#
# The invoke permission comes from `allowed_triggers` rather than from the
# notification submodule's own `create_lambda_permission`, because that is the
# input an agent can get wrong: `source_arn` is written here, not derived. The
# submodule-authored alternative is equally correct and is kept as
# solution/reference-alt-module-default-permission/.
#
# `create_package = false` keeps the module off its `data "external"` packaging
# path; the plan-only oracle never reads the archive.
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
      principal  = "s3.amazonaws.com"
      source_arn = module.claims.s3_bucket_arn
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
