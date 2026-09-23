#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is the account root, which grants the bucket to every
# principal in the account instead of to the pipeline role alone. The
# document shape is the reference's, so the over-granting identifier is a
# resolved string in plan JSON rather than a plan-time-unknown one.
set -euo pipefail

cat > main.tf <<'TF'
locals {
  bucket_name = "cdktn-bench-release-artifact-store"
}

data "aws_caller_identity" "current" {}

module "artifacts" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = local.bucket_name

  attach_policy = true
  policy        = data.aws_iam_policy_document.artifacts.json
}

data "aws_iam_policy_document" "artifacts" {
  statement {
    sid    = "PipelineOnly"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]

    resources = [
      "arn:aws:s3:::${local.bucket_name}",
      "arn:aws:s3:::${local.bucket_name}/*",
    ]
  }
}
TF

bash tests/static_tiers.sh
