#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `existing-log-expiry-rule-dropped`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE. Asked for one rule, the agent re-authors the whole rule set as
# the one rule it was asked for. The other team's 30-day expiry of `logs/` --
# deployed, in effect, and not the agent's own work -- leaves the document.
# Nothing errors: a document with one rule is legal, the plan is green, the
# apply is green, and objects under `logs/` simply stop being deleted.
#
# Caught at tier 0 twice over, which is the honest tier for it: the expiration
# path resolves to ZERO nodes, and the prefix set collapses to {"exports/"}.
set -euo pipefail

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

exec bash tests/static_tiers.sh
