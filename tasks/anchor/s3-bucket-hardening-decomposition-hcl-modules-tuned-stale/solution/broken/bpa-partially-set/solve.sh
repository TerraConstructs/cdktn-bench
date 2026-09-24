#!/usr/bin/env bash
# BROKEN FIXTURE -- catch `bpa-partially-set`.
#
# Two of the four public-access flags are passed `false`. On hcl_raw the
# natural shape of this mistake is OMITTING them, because the provider
# resolves an omitted flag to `false`; the module defaults all four to `true`
# (s3-bucket 5.16.1 variables.tf:565-587), so on this arm the only way to
# half-satisfy "not reachable under any circumstances" is to say so. The
# omission shape is a CORRECT solution here and is kept as
# solution/reference-alt-module-default-public-access.
#
# Expected: 0.0 at tier 0, `bpa-block-public-policy` and
# `bpa-restrict-public-buckets`.
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
        sse_algorithm     = "aws:kms"
        kms_master_key_id = module.archive_key.key_arn
      }
    }
  }

  attach_public_policy    = true
  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false

  attach_deny_insecure_transport_policy = true
}
HCL

bash tests/static_tiers.sh
