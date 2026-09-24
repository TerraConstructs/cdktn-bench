#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces sse-left-at-s3-managed: `sse_algorithm = "AES256"`
# (S3-managed encryption, no KMS key of any kind) instead of "aws:kms".
# Every other control is wired correctly. Verified directly: the
# sse-is-kms tier-0 `eq "aws:kms"` check resolves to "AES256" and fails
# at the cheapest tier. Must score reward=0.0.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_s3_bucket" "archive" {
  bucket = "cdktn-bench-document-archive"
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

# BUG: AES256 (S3-managed), not aws:kms -- "a key we control" is
# silently violated. No aws_kms_key resource at all.
resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
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
