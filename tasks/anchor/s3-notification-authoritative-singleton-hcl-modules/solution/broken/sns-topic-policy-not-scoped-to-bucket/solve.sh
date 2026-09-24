#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED. Identical to ../../solve.sh except for the
# one defect described below; `make falsifiability` requires reward 0.0.
#
# THE DEFECT: the notification submodule authors the topic policy
# (`create_sns_policy` left on) and is handed `bucket_arn =
# module.decoy.s3_bucket_arn` beside a `bucket` that is the wired one, so the
# policy's `aws:SourceArn` condition scopes sns:Publish to a bucket that is not
# on the notification path -- any S3 bucket in any account may publish. The
# invoke permission is written correctly through `allowed_triggers`, so this
# fixture fails the SNS half alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "decoy" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-media-ingest-decoy"
}

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
  bucket_arn = module.decoy.s3_bucket_arn

  create_lambda_permission = false

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
