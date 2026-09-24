#!/usr/bin/env bash
# SECOND REFERENCE SOLUTION -- HAND-AUTHORED, scores reward 1.0. Like every
# `reference-alt-*` directory it is a manually re-runnable proof; no gate
# iterates `reference-alt-*`.
#
# WHAT IT PROVES. The MODULE-DEFAULT wiring is a correct solution and is graded
# as one: `create_lambda_permission` and `create_sns_policy` are both left on,
# so `s3-bucket//modules/notification` authors BOTH the invoke permission and
# the topic policy itself and scopes both from its own `local.bucket_arn`
# (modules/notification/main.tf:5,73), computed from the `bucket_arn`/`bucket`
# inputs this file passes. plan JSON carries no `locals` for a module body at
# all, so neither edge can be read at its own slot.
#
# The policy grades them ONE SCOPE UP instead -- every aws_s3_bucket ARN this
# call was handed has to be a bucket the notification wires -- and records what
# that reading cannot establish (WHICH argument of the call the local reads) in
# `not_verifiable`. `solution/broken/module-default-wiring-scoped-to-a-decoy-
# bucket-arn/` is the negative twin that proves the reading is gating.
#
# The `sns` module is still asked for the topic alone (`create_topic_policy =
# false`): its own default topic policy grants AWS `*` with a SourceAccount
# condition and no S3 service principal at all, which does not let S3 publish.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "media" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-media-ingest-media"
}

module "ingest" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-media-ingest-transcode"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package         = false
  local_existing_package = "function.zip"
}

module "audit" {
  source  = "terraform-aws-modules/sns/aws"
  version = "7.1.1"

  name                = "cdktn-bench-media-ingest-audit"
  create_topic_policy = false
}

module "media_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.media.s3_bucket_id
  bucket_arn = module.media.s3_bucket_arn

  lambda_notifications = {
    ingest = {
      function_arn  = module.ingest.lambda_function_arn
      function_name = module.ingest.lambda_function_name
      events        = ["s3:ObjectCreated:Put"]
    }
  }

  sns_notifications = {
    audit = {
      topic_arn = module.audit.topic_arn
      events    = ["s3:ObjectRemoved:*"]
    }
  }
}
HCL

bash tests/static_tiers.sh
