#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces subresource-targets-wrong-bucket:
# `aws_s3_bucket_public_access_block.archive`'s `bucket` argument is a
# hardcoded literal bucket name, never a reference to
# `aws_s3_bucket.archive`. The subresource still exists (every tier-0
# existence check for it still passes -- its own literal flags are all
# `true`) but it silently controls a bucket this configuration does not
# create, leaving the real `document-archive` bucket unprotected by this
# specific control. Every other control is wired correctly. Verified
# directly: `.configuration...aws_s3_bucket_public_access_block.
# expressions.bucket` has only a `.constant_value`, no `.references` entry
# matching `^aws_s3_bucket\.` -- every-subresource-targets-this-bucket-tf
# denies it. Must score reward=0.0.
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

# BUG: hardcoded literal bucket name -- never a reference to
# aws_s3_bucket.archive. Copy-pasted from another example and never
# repointed.
resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = "some-other-bucket-entirely"
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
