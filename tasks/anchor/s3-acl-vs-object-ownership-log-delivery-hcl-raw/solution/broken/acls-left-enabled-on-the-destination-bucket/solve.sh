#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `acls-left-enabled-on-the-destination-bucket`, predicted_tier_caught "0".
#
# THE MISTAKE: the half-measure. This fixture does the HARD part correctly --
# it writes the replacement bucket policy granting `s3:PutObject` to
# `logging.s3.amazonaws.com` on the log prefix -- and then leaves Object
# Ownership at `BucketOwnerPreferred`, which reads like "the bucket owner owns
# everything written to it" and is not the same claim: it only changes
# ownership of objects uploaded with the `bucket-owner-full-control` canned
# ACL, and ACLs stay ENABLED
# (docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html).
# The ticket's actual requirement -- stop relying on access control lists -- is
# not met.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `destination-bucket-ownership-is-bucket-owner-enforced`
# (`set_eq ["BucketOwnerEnforced"]` against a resolved `["BucketOwnerPreferred"]`)
# and, independently, at tier 1 by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego's
# `object_ownership` deny rule. Two evaluators, one claim -- which is why the
# spec declares both the tier-0 and the tier-1 form of it.
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
    object_ownership = "BucketOwnerPreferred"
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

resource "aws_s3_bucket_logging" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "app-data/"
}
TF

exec bash tests/static_tiers.sh
