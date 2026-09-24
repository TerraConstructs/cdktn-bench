#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `acls-left-enabled-on-the-destination-bucket`, predicted_tier_caught "1".
#
# THE MISTAKE: the half-measure. The hard part is done -- the replacement grant
# is there, through the module input that authors it -- and Object Ownership is
# left at `BucketOwnerPreferred`, which SOUNDS like "the bucket owner owns
# everything written to it" and does not disable ACLs: it only changes ownership
# of objects uploaded with the `bucket-owner-full-control` canned ACL. The
# ticket is not done and the security baseline is still violated.
#
# THE SHAPE OF THIS MISTAKE MOVES ON THIS ARM AND THE MISTAKE DOES NOT: the
# module's `object_ownership` default is `BucketOwnerEnforced`, so the wrong
# value has to be typed out here rather than left implicit. Denied by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego over the
# module-authored `aws_s3_bucket_ownership_controls` the plan normaliser hoists
# into `root_module.resources`.
#
# Expected verdict: reward 0.0, caught at tier 1.
set -euo pipefail

cat > main.tf <<'HCL'
module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "BucketOwnerPreferred"

  attach_access_log_delivery_policy         = true
  access_log_delivery_policy_source_buckets = ["arn:aws:s3:::cdktn-bench-application-storage-app-data"]

  tags = {
    Name = "application-storage-access-logs"
  }
}

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
HCL

exec bash tests/static_tiers.sh
