#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is a hand-typed role ARN that nothing in this plan creates
# and nothing ties to the deploying identity. It is a syntactically valid
# role ARN, so only the graph edge separates it from a correct answer.
set -euo pipefail

cat > main.tf <<'TF'
locals {
  bucket_name = "cdktn-bench-release-artifact-store"
}

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
      identifiers = ["arn:aws:iam::210987654321:role/delivery-pipeline"]
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
