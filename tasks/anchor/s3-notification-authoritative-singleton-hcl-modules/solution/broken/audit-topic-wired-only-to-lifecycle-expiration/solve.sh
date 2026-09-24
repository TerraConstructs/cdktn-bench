#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED. Identical to ../../solve.sh except for the
# one defect described below; `make falsifiability` requires reward 0.0.
#
# THE DEFECT: the topic is wired to `s3:LifecycleExpiration:*` alone, which
# only fires for a delete S3's own Lifecycle engine performs -- never for an
# ordinary user-initiated delete on this unversioned bucket. It passes the
# tier-0 event whitelist (its one event IS an allowed member) and fails
# audit-topic-events-cover-a-real-delete at tier 1.
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
      events    = ["s3:LifecycleExpiration:*"]
    }
  }
}
HCL

bash tests/static_tiers.sh
