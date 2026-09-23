#!/usr/bin/env bash
# NEGATIVE FIXTURE, not a catch: an EXTRA shape the tier-1 graph rule must
# refuse, kept because `names_a_role` is a regex over reference strings and a
# module-path-tolerant anchor is one character away from also admitting
# `data.aws_iam_role.…` -- a role the account already holds and this plan does
# NOT declare. The ticket asks for the identity that DEPLOYS; a role looked up
# by name tracks whoever was named, not whoever ran terraform.
#
# The looked-up name is the gate stub's own role (gates/aws_stub.py answers
# iam:GetRole for that one name), so the plan SUCCEEDS and the 0.0 is the
# oracle's verdict rather than a failed toolchain step.
set -euo pipefail

cat > main.tf <<'TF'
data "aws_iam_role" "pipeline" {
  name = "cdktn-bench-gate"
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
      identifiers = [data.aws_iam_role.pipeline.arn]
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
