#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces subresource-omitted: `aws_s3_bucket_versioning` is
# dropped entirely -- the most-forgotten of the six decomposed resources
# (tfp-aws#23106 and siblings) -- while every other control (encryption,
# public-access block, TLS policy) is still correctly wired. Verified
# directly: with no aws_s3_bucket_versioning resource in the plan,
# versioning-enabled's `eq "Enabled"` tier-0 check resolves to 0 nodes
# and fails outright. Must score reward=0.0.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_kms_key" "archive" {
  description         = "KMS key for document-archive bucket encryption"
  enable_key_rotation = true
}

resource "aws_s3_bucket" "archive" {
  bucket = "cdktn-bench-document-archive"
}

# BUG: aws_s3_bucket_versioning is entirely absent (subresource-omitted).

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
