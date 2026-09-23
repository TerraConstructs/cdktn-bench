#!/usr/bin/env bash
# NEGATIVE FIXTURE, not a catch. The hcl_raw sibling of this fixture states the
# shape and why it is wrong; this one is the module-arm half, where the
# reference the rule reads arrives through the CALL's `policy` argument and
# `names_a_role`'s anchor has to tolerate the call path without also tolerating
# a `data` step. The plan succeeds (gates/aws_stub.py answers iam:GetRole for
# this one name), so the 0.0 is the oracle's verdict.
set -euo pipefail

cat > main.tf <<'TF'
locals {
  bucket_name = "cdktn-bench-release-artifact-store"
}

data "aws_iam_role" "pipeline" {
  name = "cdktn-bench-gate"
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
      identifiers = [data.aws_iam_role.pipeline.arn]
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
