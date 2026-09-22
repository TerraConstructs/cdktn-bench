#!/usr/bin/env bash
# BROKEN FIXTURE -- catch `kms-key-not-referenced`.
#
# `kms_master_key_id` names a key ARN literal instead of the key this
# configuration creates. Encryption is genuinely `aws:kms`, so tier 0 passes
# in full; what is missing is the graph edge to a key we control.
#
# The key module call goes with it: this configuration creates no KMS key at
# all, matching the hcl_raw fixture's own shape -- the ARN names a key that
# may not exist, may belong to another account, or may carry a policy nothing
# here controls.
#
# Expected: 0.0 at tier 1, `sse-kms-references-created-key-tf` -- the rule
# resolves the edge from the module call's own arguments on this arm, since
# the module writes its encryption block as a `dynamic` block that Terraform's
# configuration representation omits.
set -euo pipefail

cat > main.tf <<'HCL'
module "archive" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-document-archive"

  versioning = { enabled = true }

  server_side_encryption_configuration = {
    rule = {
      apply_server_side_encryption_by_default = {
        sse_algorithm     = "aws:kms"
        kms_master_key_id = "arn:aws:kms:us-east-1:111122223333:key/8a6bc1d2-0f3e-4b5a-9c7d-1e2f3a4b5c6d"
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
