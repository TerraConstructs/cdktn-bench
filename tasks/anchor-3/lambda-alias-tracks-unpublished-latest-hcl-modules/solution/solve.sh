#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# BROWNFIELD: this is the SEED with exactly two values changed. Every module
# call, source and version is reproduced from
# workspace_seed.entry_file.hcl_modules, because a reference solution for a
# change request must be the existing configuration plus the change.
#
# THE TWO CHANGES:
#   1. QUOTE_CURRENCY  "EUR" -> "USD"          -- the ticket.
#   2. the alias call's `function_version` "1" -> the function module's
#      `lambda_function_version` output, which is `aws_lambda_function.this[0]
#      .version` -- the version `publish = true` cuts on this apply. Without it
#      the apply still succeeds, the function's own configuration is USD, and
#      every caller going through the alias keeps getting the euro snapshot.
#
# MODULES (docs/design/hcl-modules-spec-matrix.md §1, versions from
# arms/hcl-modules/environment/modules/manifest.json): lambda 8.8.2 and its
# //modules/alias submodule, s3-bucket 5.16.1 and its //modules/object
# submodule. Nothing is written raw.
#
# `function_version` is a required passthrough in the alias submodule, so the
# module hides neither the mistake nor the fix: what changes is which side of
# `=` the value comes from, exactly as on hcl_raw.
set -euo pipefail

cat > main.tf <<'HCL'
module "quote_service_packages" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket_prefix = "cdktn-bench-quote-service-"
  force_destroy = true
}

module "quote_service_package" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/object"
  version = "5.16.1"

  bucket         = module.quote_service_packages.s3_bucket_id
  key            = "quote-service.zip"
  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

module "quote_service" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-quote-service"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package = false

  s3_existing_package = {
    bucket = module.quote_service_packages.s3_bucket_id
    key    = module.quote_service_package.s3_object_id
  }

  publish = true

  environment_variables = {
    QUOTE_CURRENCY = "USD"
  }
}

module "quote_service_live" {
  source  = "terraform-aws-modules/lambda/aws//modules/alias"
  version = "8.8.2"

  name             = "quote-service-live"
  function_name    = module.quote_service.lambda_function_name
  function_version = module.quote_service.lambda_function_version
}
HCL

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  # The gating live oracle, invoked in its fixture shape. Exits 1 if the
  # account contradicts "the alias serves USD", 2 if the account could not be
  # read at all (which is never scored as a solution failure).
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
