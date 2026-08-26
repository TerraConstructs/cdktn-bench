#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `s3-acl-vs-object-ownership-log-delivery` (BROWNFIELD, SCHEMA.md §2.7/§2.7.1).
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already holds a deployed
# application bucket, a deployed access-logs bucket whose Object Ownership is
# `ObjectWriter` and whose ACL is the canned `log-delivery-write` grant, and an
# `aws_s3_bucket_logging` shipping the first bucket's server access logs to the
# second under `app-data/`. The ticket: turn ACLs off on the access-logs
# bucket, keep the logs flowing.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# `BucketOwnerEnforced` disables ACLs, and AWS is explicit that once it does,
# the log-delivery group grant "no longer affect[s] permissions" and "you must
# update the bucket policy for the destination bucket to grant access to the
# logging service principal"
# (docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html).
# So the ACL grant has to be REPLACED, not merely removed: an
# `aws_s3_bucket_policy` on the destination bucket allowing `s3:PutObject` to
# `logging.s3.amazonaws.com` on `<destination-arn>/app-data/*`, scoped with the
# documented `ArnLike aws:SourceArn` confused-deputy condition.
#
# WHY THE LIVE PATH BELOW APPLIES TWICE, AND WHY THE GRADED FILE IS THE SECOND
# ONE. Two AWS rules meet on the way from the seed to the answer:
#   * `PutBucketOwnershipControls` REFUSES `BucketOwnerEnforced` while the
#     bucket ACL still grants anyone but the owner --
#     `InvalidBucketAclWithObjectOwnership`, "Bucket cannot have ACLs set with
#     ObjectOwnership's BucketOwnerEnforced setting"
#     (docs.aws.amazon.com/AmazonS3/latest/userguide/object-ownership-error-responses.html);
#   * deleting an `aws_s3_bucket_acl` resource from Terraform is a STATE-ONLY
#     delete -- the provider issues no API call, so the grant stays in the
#     account (hashicorp/aws issue #26164 is this exact collision).
# Resetting the ACL to `private` first, in its own apply, is therefore the
# order-independent way to get there, and it is what AWS's own
# "Prerequisites for disabling ACLs" page prescribes ("migrate these
# permissions to your bucket policy ... next, reset your bucket ACL to the
# default private ACL"). It is a property of the ROLLOUT, not of the answer:
# the graded artifact is the second file, and nothing in this scenario's oracle
# asserts on how many applies it took or whether an `aws_s3_bucket_acl`
# resource survives in the final configuration.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the final file, run the same
# tests/static_tiers.sh a real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally export TF_VAR_cdktn_bench_live=1 so the SEEDED,
# non-agent-owned ./provider.tf switches from its offline dummy-credential
# fixture to real ambient credentials, run the two real applies described
# above, and then assert the live oracle. This script never writes or edits
# provider.tf -- exactly the constraint a real agent is under.
set -euo pipefail

LIVE="${LIVE:-0}"

BUCKETS_AND_LOGGING='
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

resource "aws_s3_bucket_logging" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "app-data/"
}
'

# ROLLOUT STEP 1 ONLY -- never graded. Ownership is still `ObjectWriter`, so
# `PutBucketAcl` is still legal here; this is the call that clears the
# log-delivery group grant out of the account so step 2's
# `PutBucketOwnershipControls` is allowed to succeed.
write_acl_reset() {
  cat > main.tf <<TF
${BUCKETS_AND_LOGGING}
resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [aws_s3_bucket_ownership_controls.access_logs]

  bucket = aws_s3_bucket.access_logs.id
  acl    = "private"
}
TF
}

# THE GRADED ANSWER.
write_solution() {
  cat > main.tf <<TF
${BUCKETS_AND_LOGGING}
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
        Resource  = "\${aws_s3_bucket.access_logs.arn}/app-data/*"
        Condition = {
          ArnLike = { "aws:SourceArn" = aws_s3_bucket.app_data.arn }
        }
      },
    ]
  })
}
TF
}

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 1/2: reset the destination bucket's ACL while ACLs are still enabled =="
  export TF_VAR_cdktn_bench_live=1
  write_acl_reset
  terraform init -input=false
  terraform apply -input=false -auto-approve
fi

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 2/2: disable ACLs and carry the grant on a bucket policy =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
