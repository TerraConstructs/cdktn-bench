#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): the six resources
# hcl_raw assembles by hand are two calls here. `terraform-aws-modules/kms/aws`
# 4.2.2 authors the customer-managed key and publishes its ARN as the `key_arn`
# output; `terraform-aws-modules/s3-bucket/aws` 5.16.1 authors the bucket and
# all four decomposed sub-resources, each already wired to its own bucket. No
# resource is written raw: every resource this scenario grades has a module
# that authors it.
#
# The four public-access flags are passed EXPLICITLY even though the module
# already defaults them to `true` (variables.tf:565-587). They are the ticket's
# "not reachable by anyone outside this account under any circumstances" and
# the thing four tier-0 asserts read; a solution that states them does not
# change meaning if a future module version changes its defaults.
# `attach_public_policy` is what creates the public-access-block resource at
# all (main.tf:1278).
#
# `attach_deny_insecure_transport_policy` is how the TLS deny is authored here.
# The module emits `[bucket.arn, "${bucket.arn}/*"]` (main.tf:1110-1113), so
# the object-ARN half of the statement is not something this solution can get
# wrong -- which is exactly the arm difference this scenario measures.
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

  attach_deny_insecure_transport_policy = true
}
HCL

bash tests/static_tiers.sh
