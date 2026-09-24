#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `access-logging-turned-off-instead-of-migrated`, predicted_tier_caught "0".
#
# THE MISTAKE: satisfy the first sentence of the ticket by destroying what the
# second sentence protects. ACLs go off, the replacement grant is written
# correctly -- and the `logging` input is dropped from the application bucket's
# call, so the module creates no `aws_s3_bucket_logging` at all and the logs
# nobody is watching simply stop.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `application-bucket-still-ships-access-logs-under-the-same-prefix`, whose `eq`
# resolves to zero nodes here and therefore fails. That assert reads
# `.planned_values`, where the plan normaliser has hoisted the module-authored
# logging resource into `root_module.resources` -- so its absence is absence,
# not a hoist that did not happen.
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

  tags = {
    Name = "application-storage-app-data"
  }
}
HCL

exec bash tests/static_tiers.sh
