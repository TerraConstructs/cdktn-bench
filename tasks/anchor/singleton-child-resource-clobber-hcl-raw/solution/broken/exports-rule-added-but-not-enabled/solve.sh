#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `exports-rule-added-but-not-enabled`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE. The new rule is authored correctly in every value -- right
# prefix, right storage class, right day count -- and left switched off. The
# document is valid, the plan and the apply are green, and nothing ever moves
# to Glacier.
#
# THIS IS THE FIXTURE THAT FALSIFIES THE TIER-1 POLICY, so it must fail there
# and NOWHERE ELSE. Every tier-0 assert in this scenario reads a VALUE, and
# every value here is correct, so tier 0 must report tier0_pass=1 and the deny
# must come from oracles/rego/singleton-child-resource-clobber/policy.rego
# alone. That is checked mechanically below rather than asserted in prose: a
# 0.0 earned at tier 0 would leave the tier-1 policy unexercised the moment it
# was written, which is the exact gap generator/check_tier1_coverage.py exists
# to close. If the check does not hold, this fixture DELETES
# /logs/verifier/reward.txt so the falsifiability gate goes loud.
set -uo pipefail

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
    status = "Disabled"

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

LOG=/tmp/singleton-child-resource-clobber-tier1.log
bash tests/static_tiers.sh 2>&1 | tee "$LOG"

proof_failed() {
  echo "FIXTURE SELF-PROOF FAILED: $1" >&2
  rm -f /logs/verifier/reward.txt
  exit 1
}

grep -q '== summary: tier0_pass=' "$LOG" \
  || proof_failed "static_tiers.sh never reached its summary line -- the plan or the artifact is broken, so nothing here is evidence about this artifact"

grep -q '== summary: tier0_pass=1 ' "$LOG" \
  || proof_failed "tier 0 did not pass -- every value in this artifact is correct, so a tier-0 failure means this fixture is scoring 0.0 for some other reason and leaves the tier-1 policy unexercised"

grep -q 'tier1_status=FAIL' "$LOG" \
  || proof_failed "tier 1 did not FAIL -- the un-enabled-rule policy is what this fixture exists to falsify (a SKIPPED_STUB/TOOL_MISSING status is a run-invalidating condition, not proof)"

echo "FIXTURE SELF-PROOF OK: tier 0 passes on this artifact and only the tier-1 policy denies it"
exit 0
