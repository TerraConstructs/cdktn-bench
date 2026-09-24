#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). THE PLAUSIBLE-WRONG SOLUTION (this scenario's headline catch,
# blueprint §1(c)): the Deny-on-non-TLS statement's Resource set names
# only the bucket ARN, never the object-ARN pattern
# ("${aws_s3_bucket.archive.arn}/*"). Every other control is wired
# identically to the reference solution. Verified directly: the plan's
# `aws_s3_bucket_policy.values.policy` is opaque (SCHEMA.md §4.2.1 G2
# contagion, same as the correct fixture), so the tier-1 grading is the
# graph-edge check -- `.configuration...aws_s3_bucket_policy.expressions.
# policy.references` for this fixture resolves to ["aws_s3_bucket.archive.
# arn", "aws_s3_bucket.archive"] (ONE `.arn`-suffixed reference, not two)
# -- oracles/rego/s3-bucket-hardening-decomposition/policy.rego's
# arn_ref_count() < 2 rule denies it. Must score reward=0.0.
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

# BUG: Resource names only the bucket ARN itself -- the object-ARN
# pattern ("${...}/*") is never added, so every object-level request over
# plain HTTP remains allowed.
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
        Resource  = [aws_s3_bucket.archive.arn]
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
