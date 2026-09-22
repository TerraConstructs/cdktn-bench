#!/usr/bin/env bash
# BROKEN FIXTURE -- catch `subresource-omitted`.
#
# The `versioning` input is left out. The module's versioning sub-resource is
# gated on `length(keys(var.versioning)) > 0` (s3-bucket 5.16.1 main.tf:242)
# over a `{}` default (variables.tf:174), so omitting the input plans no
# versioning resource at all -- the same end state as dropping the
# `aws_s3_bucket_versioning` block on hcl_raw, reached by leaving an argument
# out rather than a block. Everything else is the reference.
#
# Expected: 0.0 at tier 0, `versioning-enabled` (0 nodes resolved).
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
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  attach_deny_insecure_transport_policy = true
}
HCL

bash tests/static_tiers.sh
