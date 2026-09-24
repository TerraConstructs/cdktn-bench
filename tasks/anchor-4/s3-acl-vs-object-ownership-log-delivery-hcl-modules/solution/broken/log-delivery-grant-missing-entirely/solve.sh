#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-missing-entirely`, predicted_tier_caught "1" on the
# Terraform-shaped arms.
#
# THE MISTAKE, AND THE LIKELIEST ONE: make exactly the change the ticket names
# -- ACLs off on the access-logs bucket -- and add nothing. With ACLs disabled
# the log-delivery group grant it just neutralised was the ONLY thing
# authorizing delivery. Because the logging configuration itself is untouched,
# `PutBucketLogging` is never re-issued and no API call anywhere complains.
#
# ON THIS ARM "add nothing" IS AN OMISSION AGAIN, which is worth stating because
# the sibling catch's shape moved: none of the module's `attach_*` inputs is set,
# so `local.attach_policy` stays false and the module creates no
# `aws_s3_bucket_policy` at all. The Rego's unconditional half reads every
# CONFIGURATION SCOPE rather than the root module alone, so "declared nowhere"
# is what it measures here -- and the reference, whose policy is declared inside
# a module body, is not denied by it.
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
  object_ownership         = "BucketOwnerEnforced"

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
