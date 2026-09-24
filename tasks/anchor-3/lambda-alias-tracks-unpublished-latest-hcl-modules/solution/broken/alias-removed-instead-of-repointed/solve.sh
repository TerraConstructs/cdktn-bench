#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-removed-instead-of-repointed`, predicted_tier_caught "0" on every arm.
#
# THE MISTAKE: make the symptom go away by removing the thing that has it. The
# environment variable becomes `USD` and the whole `//modules/alias` call is
# deleted, so the new configuration IS reachable -- at the unqualified function
# ARN. It is not the ticket ("every caller reaches this function through its
# alias") and it breaks every one of those callers the moment it applies.
#
# Worth pinning as its own fixture rather than trusting the main catch to cover
# it: deleting the alias ALSO makes
# `alias-is-no-longer-pinned-to-the-seeds-version` pass -- that assert uses
# `not_regex`, which is true over zero resolved nodes. What refuses it is
# `the-alias-still-exists`, whose `eq` pins the node COUNT as well as the name,
# so a workspace with no alias cannot score 1.0 at tier 0 while having deleted
# the interface every caller uses.
#
# Expected verdict: reward 0.0, caught at tier 0 by `the-alias-still-exists`.
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

HCL

exec bash tests/static_tiers.sh
