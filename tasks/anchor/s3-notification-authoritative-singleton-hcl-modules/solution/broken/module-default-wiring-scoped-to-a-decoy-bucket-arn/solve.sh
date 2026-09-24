#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED. Identical to ../../solve.sh except for the
# one defect described below; `make falsifiability` requires reward 0.0.
#
# EXTRA fixture (no catches[] entry of its own): the MIS-SCOPED spelling of
# the module-DEFAULT wiring that solution/reference-alt-module-default-wiring/
# scores 1.0 on. Both the invoke permission and the SNS policy are authored by
# the notification submodule from its own `local.bucket_arn`, which plan JSON
# does not represent -- so both are graded ONE SCOPE UP, and this fixture is
# what proves that reading is a GATING deny rather than a recorded
# `not_verifiable` note: the call is handed `bucket_arn =
# module.decoy.s3_bucket_arn`, and every aws_s3_bucket ARN a notification call
# is handed has to be a bucket it wires.
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
  bucket_arn = module.decoy.s3_bucket_arn

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
