#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is the deploying session's own ARN, straight off the
# caller-identity data source. Under the assume-role credentials every
# trial holds, that resolves to an `arn:aws:sts::…:assumed-role/…/…`
# session identity, which is not a policy principal. The module is
# untouched: the document it is handed is where the mistake lives, which is
# the whole point of the composition on this arm.
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
      identifiers = [data.aws_caller_identity.current.arn]
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
