#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1):
# `terraform-aws-modules/s3-bucket/aws` 5.16.1 authors both graded resources
# -- the bucket, and the `aws_s3_bucket_policy` attached to it, which
# `attach_policy = true` is what creates (main.tf:713). The two data sources
# have no module counterpart and stay raw; resolving the deploying session
# back to its issuer role is the wiring this scenario measures, and it is
# the part no module does for you.
#
# The principal is the ISSUER ROLE of the deploying session, not the session
# itself: `data.aws_caller_identity.current.arn` under assume-role
# credentials is an `arn:aws:sts::…:assumed-role/…/…` session ARN, which IAM
# refuses as a policy principal.
#
# The document is a `data "aws_iam_policy_document"` rather than a
# `jsonencode(...)`: only that shape renders its principal identifiers into
# plan JSON, so "and nothing broader" is checked here rather than logged as
# not-verifiable. The module folds it into its own `combined` document
# (main.tf:730-746) and attaches the result.
#
# The bucket is named rather than prefixed, and the policy names the bucket
# ARN literally, because the module authors the bucket AND its policy: a
# document built from `module.artifacts.s3_bucket_arn` and then handed back
# to that same call is a dependency cycle Terraform refuses. Naming the
# bucket is how a module user breaks it, and nothing in this scenario grades
# the bucket's name.
set -euo pipefail

cat > main.tf <<'TF'
locals {
  bucket_name = "cdktn-bench-release-artifact-store"
}

data "aws_caller_identity" "current" {}

# The deploying credentials are an STS session, not an identity IAM can name
# in a policy; this maps that session back to the role that issued it.
data "aws_iam_session_context" "deployer" {
  arn = data.aws_caller_identity.current.arn
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
      identifiers = [data.aws_iam_session_context.deployer.issuer_arn]
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
