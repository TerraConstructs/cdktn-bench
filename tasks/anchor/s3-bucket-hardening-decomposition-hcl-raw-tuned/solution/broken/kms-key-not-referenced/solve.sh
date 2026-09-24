#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces kms-key-not-referenced: `sse_algorithm = "aws:kms"`
# (passes sse-is-kms) but `kms_master_key_id` is a hand-typed, imported key
# ARN literal -- no matching `resource "aws_kms_key"` block anywhere.
# Every other control is wired correctly. Verified directly:
# `.configuration...kms_master_key_id` holds only a `.constant_value`,
# never a `.references` entry matching `^aws_kms_key\.` --
# sse-kms-references-created-key-tf denies it. Must score reward=0.0.
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

# BUG: hand-typed, imported key ARN literal -- no aws_kms_key resource
# this configuration actually creates.
resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
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
