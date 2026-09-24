#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `s3-acl-vs-object-ownership-log-delivery` (BROWNFIELD, SCHEMA.md §2.7/§2.7.1).
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already composes two
# `terraform-aws-modules/s3-bucket/aws` 5.16.1 calls -- an application bucket
# shipping its server access logs to an access-logs bucket under `app-data/`,
# and that bucket's Object Ownership set to `ObjectWriter` -- plus the one raw
# resource on this arm, the canned `log-delivery-write` ACL. The ticket: turn
# ACLs off on the access-logs bucket, keep the logs flowing.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# `BucketOwnerEnforced` disables ACLs, and AWS is explicit that once it does,
# the log-delivery group grant "no longer affect[s] permissions" and "you must
# update the bucket policy for the destination bucket to grant access to the
# logging service principal"
# (docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html).
# The grant has to be REPLACED, not merely removed.
#
# THE MODULE ALREADY KNOWS THIS ONE. `attach_access_log_delivery_policy`
# (variables.tf:477) builds the replacement itself: `s3:PutObject` for
# `logging.s3.amazonaws.com` on `${bucket.arn}/*` plus the `GetBucketAcl`
# statement, and `access_log_delivery_policy_source_buckets` adds the
# documented `ForAnyValue:ArnLike aws:SourceArn` confused-deputy condition.
# That is the whole answer on this arm, and finding it is what this rung
# measures. `solution/policy-written-by-the-caller/` is the second accepted
# shape -- the same grant written out by hand -- and it is the shape
# `solution/broken/log-delivery-grant-not-migrated/` contrasts itself against.
#
# WHY THE LIVE PATH APPLIES TWICE, AND WHY THE GRADED FILE IS THE SECOND ONE.
# Two AWS rules meet on the way from the seed to the answer:
#   * `PutBucketOwnershipControls` REFUSES `BucketOwnerEnforced` while the
#     bucket ACL still grants anyone but the owner;
#   * deleting an `aws_s3_bucket_acl` resource from Terraform is a STATE-ONLY
#     delete -- the provider issues no API call, so the grant stays in the
#     account.
# Resetting the ACL to `private` first, in its own apply, is what AWS's own
# "Prerequisites for disabling ACLs" page prescribes. It is a property of the
# ROLLOUT, not of the answer: the graded artifact is the second file, and
# nothing in this scenario's oracle asserts how many applies it took.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the final file, run the same
# tests/static_tiers.sh a real trial's verifier runs.
# LIVE=1: additionally run the two real applies against the seeded,
# non-agent-owned ./provider.tf's ambient credentials, then assert the live
# oracle. This script never writes or edits provider.tf.
set -euo pipefail

LIVE="${LIVE:-0}"

APP_DATA='
module "app_data" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  depends_on = [module.access_logs]

  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  attach_public_policy = false

  logging = {
    target_bucket = module.access_logs.s3_bucket_id
    target_prefix = "app-data/"
  }

  tags = {
    Name = "application-storage-app-data"
  }
}
'

# ROLLOUT STEP 1 ONLY -- never graded. Ownership is still `ObjectWriter`, so
# `PutBucketAcl` is still legal here; this is the call that clears the
# log-delivery group grant out of the account so step 2's
# `PutBucketOwnershipControls` is allowed to succeed.
write_acl_reset() {
  cat > main.tf <<TF
module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "ObjectWriter"

  tags = {
    Name = "application-storage-access-logs"
  }
}

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [module.access_logs]

  bucket = module.access_logs.s3_bucket_id
  acl    = "private"
}
${APP_DATA}
TF
}

# THE GRADED ANSWER.
write_solution() {
  cat > main.tf <<TF
module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "BucketOwnerEnforced"

  attach_access_log_delivery_policy         = true
  access_log_delivery_policy_source_buckets = ["arn:aws:s3:::cdktn-bench-application-storage-app-data"]

  tags = {
    Name = "application-storage-access-logs"
  }
}
${APP_DATA}
TF
}

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 1/2: reset the destination bucket's ACL while ACLs are still enabled =="
  write_acl_reset
  terraform init -input=false
  terraform apply -input=false -auto-approve
fi

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 2/2: disable ACLs and carry the grant on the module's own bucket policy =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
