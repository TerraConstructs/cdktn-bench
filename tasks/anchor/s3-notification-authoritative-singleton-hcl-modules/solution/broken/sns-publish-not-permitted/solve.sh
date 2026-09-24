#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED. Identical to ../../solve.sh except for the
# one defect described below; `make falsifiability` requires reward 0.0.
#
# THE DEFECT: the audit topic is wired, and NEITHER accepted policy shape
# exists -- `create_topic_policy = false` with no `topic_policy` passed to
# `sns`, and `create_sns_policy = false` on the notification submodule. S3
# silently drops every publish to the topic, with no error at plan, apply or
# any later time.
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

  allowed_triggers = {
    MediaUpload = {
      principal  = "s3.amazonaws.com"
      source_arn = module.media.s3_bucket_arn
    }
  }
}

module "audit" {
  source  = "terraform-aws-modules/sns/aws"
  version = "7.1.1"

  name = "cdktn-bench-media-ingest-audit"

  create_topic_policy = false
}

# ONE notification submodule call, both targets.
module "media_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.media.s3_bucket_id
  bucket_arn = module.media.s3_bucket_arn

  create_lambda_permission = false
  create_sns_policy        = false

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
