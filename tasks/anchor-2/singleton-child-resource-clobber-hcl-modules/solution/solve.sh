#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `singleton-child-resource-clobber`, hcl_modules arm (BROWNFIELD, SCHEMA.md
# §2.7 / §2.7.1, DECISIONS.md Amendments 28 and 31; the arm is Amendment 46).
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already holds the deployed
# storage configuration for one archive bucket, composed from
# `terraform-aws-modules/s3-bucket/aws` 5.16.1 -- including another team's rule
# deleting `logs/` objects after 30 days, which lives in that call's
# `lifecycle_rule` list. The task is ONE change: also move `exports/` objects to
# Glacier Instant Retrieval after 90 days, and roll it out.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# An S3 bucket has exactly ONE lifecycle configuration document.
# PutBucketLifecycleConfiguration has no create/update distinction and no
# per-rule write: every call replaces the whole document. The module already
# owns that one document -- `aws_s3_bucket_lifecycle_configuration.this[0]`,
# created when `lifecycle_rule` is non-empty and rendered from it through a
# `dynamic "rule"` block (main.tf:352-366) -- so the new requirement is one more
# ELEMENT of that list, authored in a body the agent did not write, and never a
# second resource.
#
# THE PLAUSIBLE WRONG ANSWER on this arm is cheaper than on hcl_raw rather than
# dearer: a root `aws_s3_bucket_lifecycle_configuration "exports"` whose
# `bucket` is `module.reports.s3_bucket_id` needs one module OUTPUT and no
# reading of the module's inputs at all. It plans green, applies with exit 0,
# and leaves the two resources taking turns writing the one document. See
# `solution/broken/exports-rule-added-as-a-second-child-resource/solve.sh`.
#
# The module shape changes nothing about how that is graded: the plan normaliser
# hoists module resources into `planned_values.root_module.resources`, so the
# cardinality assert counts the module's document and a root one as two
# documents for the one bucket.
#
# `enabled = true` rather than `status = "Enabled"`: both are accepted inputs
# (variables.tf:252-253) and the module maps either onto the same planned
# `status` string (main.tf:366). The boolean is the shape the module's own
# examples use and the shape the seed already carries.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs.
# LIVE=1: additionally run a real `terraform apply` against the SEEDED,
# non-agent-owned ./provider.tf's ambient credentials, and then assert the live
# oracle. This script never writes or edits provider.tf -- exactly the
# constraint a real agent solving this scenario is under.
set -euo pipefail

LIVE="${LIVE:-0}"

cat > main.tf <<'TF'
module "reports" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-reports-archive"
  force_destroy = true

  tags = {
    Name = "reports-archive"
  }

  lifecycle_rule = [
    {
      id      = "expire-raw-logs"
      enabled = true

      filter = {
        prefix = "logs/"
      }

      expiration = {
        days = 30
      }
    },
    {
      id      = "archive-exports"
      enabled = true

      filter = {
        prefix = "exports/"
      }

      transition = [
        {
          days          = 90
          storage_class = "GLACIER_IR"
        },
      ]
    },
  ]
}
TF

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
