#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# Verified directly against a real `terraform init && terraform plan` run
# (hashicorp/aws 6.58.0, this arm's pin): 6 resources planned
# (aws_kms_key, aws_s3_bucket, aws_s3_bucket_versioning,
# aws_s3_bucket_server_side_encryption_configuration,
# aws_s3_bucket_public_access_block, aws_s3_bucket_policy).
# `aws_s3_bucket_policy.values.policy` is entirely ABSENT from
# `.planned_values` (SCHEMA.md §4.2.1 G2 contagion -- the `policy`
# jsonencode() call embeds a reference to the bucket's provider-computed
# `.arn`), so the Deny statement's two-ARN coverage is graded via the
# graph-edge path instead: `.configuration...aws_s3_bucket_policy.
# expressions.policy.references` resolves to `["aws_s3_bucket.archive.arn",
# "aws_s3_bucket.archive", "aws_s3_bucket.archive.arn",
# "aws_s3_bucket.archive"]` -- the `.arn`-suffixed entry appearing TWICE
# (once for the direct bucket-ARN element, once for the
# "${aws_s3_bucket.archive.arn}/*" object-ARN interpolation), which is
# exactly what oracles/rego/s3-bucket-hardening-decomposition/policy.rego's
# arn_ref_count()-based rule requires (>= 2).
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_kms_key" "archive" {
  description         = "KMS key for document-archive bucket encryption"
  enable_key_rotation = true
}

resource "aws_s3_bucket" "archive" {
  bucket = "cdktn-bench-document-archive"
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.archive.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Deny statement's Resource list carries BOTH the bucket ARN itself and the
# object-ARN pattern ("${...}/*") -- omitting the second element is this
# scenario's own headline catch (tls-policy-misses-object-arn): it reads
# correctly, passes every existence check, and leaves every object-level
# request over plain HTTP allowed (IAM policy evaluation for an S3
# object-level action is scoped by the OBJECT arn, not the bucket arn).
resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.archive.arn,
          "${aws_s3_bucket.archive.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
HCL

bash tests/static_tiers.sh
