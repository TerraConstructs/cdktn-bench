#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `singleton-child-resource-clobber` (BROWNFIELD, SCHEMA.md §2.7 / §2.7.1,
# DECISIONS.md Amendments 28 and 31). Regenerating this scenario will NOT
# overwrite this file (destructive-safe rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already holds the deployed
# storage configuration for one archive bucket, including another team's rule
# deleting `logs/` objects after 30 days. The task is ONE change: also move
# `exports/` objects to Glacier Instant Retrieval after 90 days, and roll it
# out.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# An S3 bucket has exactly ONE lifecycle configuration document.
# PutBucketLifecycleConfiguration has no create/update distinction and no
# per-rule write: every call replaces the whole document. So the new
# requirement is a second `rule` block INSIDE the existing
# `aws_s3_bucket_lifecycle_configuration`, never a second resource.
#
# THE PLAUSIBLE WRONG ANSWER -- a second
# `aws_s3_bucket_lifecycle_configuration "exports"` with the same
# `bucket = aws_s3_bucket.reports.id` -- passes `terraform validate`, passes
# `terraform plan`, and applies with exit 0. Both rules are then present in the
# graded artifact, one per resource, so every value-level assert in this
# oracle passes on it. What it does NOT do is leave both rules in effect: the
# two resources take turns writing the one document, so the account holds
# whichever applied last and the next plan is never empty. See
# `solution/broken/exports-rule-added-as-a-second-child-resource/solve.sh`,
# which demonstrates that mechanically and offline.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally export TF_VAR_cdktn_bench_live=1 so the SEEDED,
# non-agent-owned ./provider.tf switches from its offline dummy-credential
# fixture to real ambient credentials, run a real `terraform apply`, and then
# assert the live oracle. This script never writes or edits provider.tf --
# exactly the constraint a real agent solving this scenario is under.
set -euo pipefail

LIVE="${LIVE:-0}"

cat > main.tf <<'TF'
resource "aws_s3_bucket" "reports" {
  bucket        = "cdktn-bench-reports-archive"
  force_destroy = true

  tags = {
    Name = "reports-archive"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-raw-logs"
    status = "Enabled"

    filter {
      prefix = "logs/"
    }

    expiration {
      days = 30
    }
  }

  rule {
    id     = "archive-exports"
    status = "Enabled"

    filter {
      prefix = "exports/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }
}
TF

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  export TF_VAR_cdktn_bench_live=1
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
