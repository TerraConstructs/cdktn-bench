#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# ONE authoritative notification: a single `s3-bucket//modules/notification`
# call wires BOTH requirements (Product: upload -> lambda; Compliance: delete
# -> sns). The headline catch is declaring TWO calls, one per stakeholder ask,
# which plans two `aws_s3_bucket_notification` resources that fight over S3's
# single PutBucketNotificationConfiguration document.
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): `s3-bucket`
# 5.16.1 for the bucket, its `//modules/notification` submodule for the
# notification, `lambda` 8.8.2 for the function and its role, `sns` 7.1.1 for
# the topic.
#
# WHY THE TWO GRADED EDGES ARE WRITTEN AT THE ROOT HERE. Both are inputs the
# agent chooses, and both are the inputs an agent can get wrong:
#   * the invoke permission comes from `lambda`'s `allowed_triggers`, so
#     `source_arn` is written here rather than derived;
#   * the topic policy is a root `data "aws_iam_policy_document"` handed to
#     `sns`'s `topic_policy`, which the module sets on `aws_sns_topic.policy`
#     (main.tf:47) -- the provider's own inline shape.
# The module-DEFAULT shape (`create_lambda_permission` / `create_sns_policy`
# left on, both scoped from the submodule's own `local.bucket_arn`) is equally
# correct and is graded as the second reference under
# solution/reference-alt-module-default-wiring/.
#
# `resources = ["*"]` in the topic policy document, not the topic's own ARN:
# the topic reads this document and the document would read the topic, which
# terraform rejects as a cycle (measured). A topic policy applies to the topic
# it is attached to, so the statement is not widened by it.
#
# `create_package = false` keeps `lambda` off its `data "external"` packaging
# path, and function.zip is a placeholder -- this scenario's oracle is
# plan-only and never reads the archive.
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
      events    = ["s3:ObjectRemoved:*"]
    }
  }
}
HCL

bash tests/static_tiers.sh
