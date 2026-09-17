#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# The principal is the ISSUER ROLE of the deploying session, not the session
# itself: `data.aws_caller_identity.current.arn` under assume-role
# credentials is an `arn:aws:sts::…:assumed-role/…/…` session ARN, which IAM
# refuses as a policy principal.
#
# The document is a `data "aws_iam_policy_document"` rather than a
# `jsonencode(...)`: only that shape renders its principal identifiers into
# plan JSON, so "and nothing broader" is checked here rather than logged as
# not-verifiable.
set -euo pipefail

cat > main.tf <<'TF'
data "aws_caller_identity" "current" {}

# The deploying credentials are an STS session, not an identity IAM can name
# in a policy; this maps that session back to the role that issued it.
data "aws_iam_session_context" "deployer" {
  arn = data.aws_caller_identity.current.arn
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "release-artifact-store-"
}

data "aws_iam_policy_document" "artifacts" {
  statement {
    sid    = "PipelineOnly"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [data.aws_iam_session_context.deployer.issuer_arn]
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
TF

bash tests/static_tiers.sh
