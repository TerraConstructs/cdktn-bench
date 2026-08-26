#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `access-logging-turned-off-instead-of-migrated`, predicted_tier_caught "0".
#
# THE MISTAKE: the other way to make the ACL dependency go away -- remove the
# thing that depended on it. ACLs are switched off on the access-logs bucket
# exactly as the ticket's first sentence asks, and the application bucket's
# `aws_s3_bucket_logging` is deleted, which is what the ticket's second
# sentence exists to forbid. The bucket policy is still written, so this
# fixture differs from the reference solution in exactly one thing.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `application-bucket-still-ships-access-logs-under-the-same-prefix` (`eq
# "app-data/"` resolves to zero nodes with no logging resource in the plan, and
# `eq` requires exactly one) and by
# `access-logs-still-target-a-bucket-this-workspace-creates`.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_s3_bucket" "app_data" {
  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  tags = {
    Name = "application-storage-app-data"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  tags = {
    Name = "application-storage-access-logs"
  }
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "S3ServerAccessLogsPolicy"
        Effect    = "Allow"
        Principal = { Service = "logging.s3.amazonaws.com" }
        Action    = ["s3:PutObject"]
        Resource  = "${aws_s3_bucket.access_logs.arn}/app-data/*"
        Condition = {
          ArnLike = { "aws:SourceArn" = aws_s3_bucket.app_data.arn }
        }
      },
    ]
  })
}
TF

exec bash tests/static_tiers.sh
