#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-missing-entirely`, predicted_tier_caught "1" on this arm.
#
# THE MISTAKE, and the likeliest one an agent actually makes: do exactly what
# the ticket says and nothing else. Object Ownership on the access-logs bucket
# becomes the bucket-owner-enforced setting, the now-inert `aws_s3_bucket_acl`
# resource is deleted, the logging configuration is left untouched, and NO
# bucket policy replaces the grant that was just switched off. Nothing
# complains: `PutBucketLogging` is never re-issued because the logging
# configuration did not change, the plan is green, the apply is green, and the
# log objects stop arriving hours later into a bucket nobody is watching.
#
# Expected verdict: reward 0.0, caught at TIER 1 by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego's "declares
# no aws_s3_bucket_policy" rule -- verified directly at authoring time against
# this exact artifact shape with `opa eval`. NOT caught at tier 0, on purpose
# and by measurement: every tier-0 assert this arm declares (the log prefix
# literal, and the logging resource's `target_bucket` reference) is still
# satisfied by this file, which is what makes "a bucket policy must exist at
# all" a claim about the resource COLLECTION rather than a value at a path.
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

resource "aws_s3_bucket_logging" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "app-data/"
}
TF

exec bash tests/static_tiers.sh
