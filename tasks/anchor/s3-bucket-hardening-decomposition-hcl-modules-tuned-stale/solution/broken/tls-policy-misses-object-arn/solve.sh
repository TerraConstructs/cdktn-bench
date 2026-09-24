#!/usr/bin/env bash
# BROKEN FIXTURE -- catch `tls-policy-misses-object-arn`, this scenario's
# headline catch.
#
# The deny-on-non-TLS statement names only the bucket ARN, leaving every
# object-level request over plain HTTP allowed. The module's own
# `attach_deny_insecure_transport_policy` input cannot express this -- it
# emits both ARNs unconditionally (s3-bucket 5.16.1 main.tf:1110-1113) -- so
# the fixture reaches the mistake through the module's other policy input,
# `attach_policy` + a hand-written `policy` document (variables.tf:438), which
# is the raw passthrough an agent reaches for when it wants to write the
# statement itself.
#
# Expected: 0.0 at tier 1. The module funnels every policy input through a
# `local`, so neither the policy attribute's references nor its planned value
# carry the Resource list; the deny says exactly that, and the correct shape
# is distinguished by the deny-insecure-transport document it actually plans.
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
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  attach_policy = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "denyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = "arn:aws:s3:::cdktn-bench-document-archive"
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
HCL

bash tests/static_tiers.sh
