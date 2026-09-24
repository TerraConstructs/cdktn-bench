#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED. Identical to ../../solve.sh except for the
# one defect described below; `make falsifiability` requires reward 0.0.
#
# THE DEFECT: two `s3-bucket//modules/notification` calls against the SAME
# bucket -- one per stakeholder ask, which is the natural shape when two
# tickets arrive. Each plans its own `aws_s3_bucket_notification`, and S3's
# PutBucketNotificationConfiguration is one document per bucket with no
# create/update distinction, so the two silently overwrite each other on every
# apply. Caught at tier 0: exactly-one-notification-resource-per-bucket-tf
# resolves to 2 nodes, which `eq` fails outright.
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

# S3 cannot publish to a topic whose resource policy does not grant it
# sns:Publish, scoped by aws:SourceArn to this specific bucket.
data "aws_iam_policy_document" "audit" {
  statement {
    sid     = "AllowS3Publish"
    effect  = "Allow"
    actions = ["SNS:Publish"]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    resources = ["*"]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [module.media.s3_bucket_arn]
    }
  }
}

module "audit" {
  source  = "terraform-aws-modules/sns/aws"
  version = "7.1.1"

  name = "cdktn-bench-media-ingest-audit"

  create_topic_policy = false
  topic_policy        = data.aws_iam_policy_document.audit.json
}

module "media_upload_notification" {
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

}

module "media_delete_audit_notification" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/notification"
  version = "5.16.1"

  bucket     = module.media.s3_bucket_id
  bucket_arn = module.media.s3_bucket_arn

  create_sns_policy = false

  sns_notifications = {
    audit = {
      topic_arn = module.audit.topic_arn
      events    = ["s3:ObjectRemoved:*"]
    }
  }
}
HCL

bash tests/static_tiers.sh
