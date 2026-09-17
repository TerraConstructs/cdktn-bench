#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is the deploying session's own ARN, straight off the
# caller-identity data source. Under the assume-role credentials every
# trial holds, that resolves to an `arn:aws:sts::…:assumed-role/…/…`
# session identity, which is not a policy principal.
set -euo pipefail

cat > main.tf <<'SRC'
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "release-artifact-store-"
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
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.artifacts.json
}
SRC

bash tests/static_tiers.sh
