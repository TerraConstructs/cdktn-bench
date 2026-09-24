#!/usr/bin/env bash
# BROKEN FIXTURE -- catch `sse-left-at-s3-managed`.
#
# `sse_algorithm` is S3's own default key instead of the KMS key this
# configuration creates. The module passes the algorithm straight through
# (s3-bucket 5.16.1 main.tf:280), so this is the identical typed-value trap
# hcl_raw carries, and the key module is left in place and unused -- the
# bucket is encrypted, just not with a key we control.
#
# Expected: 0.0 at tier 0, `sse-is-kms`.
set -euo pipefail

cat > main.tf <<'HCL'
module "archive_key" {
  source  = "terraform-aws-modules/kms/aws"
  version = "4.2.2"

  description         = "Customer-managed key for the document archive bucket"
  enable_key_rotation = true
}

module "archive" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-document-archive"

  versioning = { enabled = true }

  server_side_encryption_configuration = {
    rule = {
      apply_server_side_encryption_by_default = {
        sse_algorithm     = "AES256"
      }
    }
  }

  attach_public_policy    = true
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  attach_deny_insecure_transport_policy = true
}
HCL

bash tests/static_tiers.sh
