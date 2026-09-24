#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces bpa-partially-set: only `block_public_acls` /
# `block_public_policy` are set true; `ignore_public_acls` /
# `restrict_public_buckets` are left at their explicit `false`. Every
# other control is wired correctly. Verified directly: the provider
# schema resolves the two false flags to a present, explicit `false` in
# `.planned_values` -- the bpa-ignore-public-acls /
# bpa-restrict-public-buckets tier-0 `eq true` checks fail (present, wrong
# value). Must score reward=0.0.
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

# BUG: only 2 of the 4 flags are true.
resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = false
  restrict_public_buckets = false
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
