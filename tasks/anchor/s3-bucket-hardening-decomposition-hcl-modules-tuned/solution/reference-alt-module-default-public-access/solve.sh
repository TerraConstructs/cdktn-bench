#!/usr/bin/env bash
# A SECOND CORRECT SOLUTION, not a broken fixture: it scores 1.0 and is kept
# because it is the shape the module's own defaults produce.
#
# The four public-access flags are omitted entirely. On hcl_raw that is the
# `bpa-partially-set` mistake -- the provider resolves every omitted flag to
# `false`. Here the module defaults all four to `true` (s3-bucket 5.16.1
# variables.tf:565-587), so the omission plans a fully blocked bucket and the
# four tier-0 asserts pass. Kept under solution/ rather than solution/broken/
# because a fixture that scores 1.0 is not a broken fixture; what it holds is
# that the oracle does not demand the flags be RESTATED when the module
# already sets them.
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

  attach_deny_insecure_transport_policy = true
}
HCL

bash tests/static_tiers.sh
