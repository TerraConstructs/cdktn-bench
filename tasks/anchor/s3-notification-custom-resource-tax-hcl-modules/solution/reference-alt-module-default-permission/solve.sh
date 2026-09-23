#!/usr/bin/env bash
# A SECOND CORRECT SOLUTION, not a broken fixture: it scores 1.0 and is kept
# because it is the shape the notification submodule's own defaults produce.
#
# `create_lambda_permission` defaults true, so the submodule authors the
# invoke permission and scopes it from `local.bucket_arn`
# (modules/notification/main.tf:73) -- the agent never writes a source_arn. A
# module body's `local` has no plan-JSON representation and the permission is
# `for_each`-expanded, so the tier-1 policy resolves that edge against this
# call's own arguments; this fixture is what holds that resolution honest.
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
}

module "claims_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.claims.s3_bucket_id
  bucket_arn = module.claims.s3_bucket_arn

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
