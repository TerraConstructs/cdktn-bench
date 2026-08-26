#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `exports-rule-added-as-a-second-child-resource`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE. The new requirement arrives as its own ticket, so it is authored
# as its own resource: a second `aws_s3_bucket_lifecycle_configuration` against
# the same bucket. `terraform validate` says nothing, `terraform plan` says
# nothing (the provider schema carries no cross-resource uniqueness constraint
# on `bucket`), and a real apply exits 0. An S3 bucket nevertheless has exactly
# ONE lifecycle configuration document and PutBucketLifecycleConfiguration
# replaces it whole, so the two resources take turns overwriting each other:
# the account ends up holding whichever applied last, the other requirement is
# silently not in effect, and the next plan is never empty.
#
# WHAT THIS FIXTURE PROVES BEYOND "reward is 0.0"
# ===============================================
# `make falsifiability` grades on reward.txt alone, and a 0.0 here would be
# earned even if the artifact were rejected for some unrelated reason -- a typo
# in a prefix, a missing bucket, a broken toolchain. The claim this scenario
# actually makes is stronger and more specific:
#
#     EVERY other static assert in this oracle PASSES on this artifact.
#     Exactly one -- `exactly-one-storage-rule-document-for-the-bucket` --
#     fails, and it is the only thing standing between this shape and a 1.0.
#
# That is what makes the assert non-redundant with the rest of the tier, and it
# is checked mechanically below rather than asserted in prose: the tier-0 log
# must contain exactly one `FAIL [...]` line, it must name that assert, and the
# three value-level asserts about the two rules must all be PASS. If the check
# does not hold, this fixture DELETES /logs/verifier/reward.txt, so the
# falsifiability gate reports a missing reward rather than banking an accidental
# 0.0 as proof.
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
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
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

LOG=/tmp/singleton-child-resource-clobber-tier0.log
bash tests/static_tiers.sh 2>&1 | tee "$LOG"

# --- the self-proof --------------------------------------------------------
# Never treat a run-invalidating test-infrastructure condition as evidence
# (SCHEMA.md §2.7's own "TF-PLAN FAILED / MISSING ARTIFACT / mock-STS bail-out"
# rule). If terraform never planned, this fixture proved nothing at all.
proof_failed() {
  echo "FIXTURE SELF-PROOF FAILED: $1" >&2
  rm -f /logs/verifier/reward.txt
  exit 1
}

grep -q '== summary: tier0_pass=' "$LOG" \
  || proof_failed "static_tiers.sh never reached its summary line -- the plan or the artifact is broken, so nothing here is evidence about this artifact"

FAILS="$(grep -c '  FAIL \[' "$LOG" || true)"
[ "$FAILS" = "1" ] \
  || proof_failed "expected exactly ONE failing tier-0 assert, saw $FAILS -- this artifact is supposed to be indistinguishable from a correct one everywhere except cardinality"

grep -q '  FAIL \[exactly-one-storage-rule-document-for-the-bucket\]' "$LOG" \
  || proof_failed "the one failing assert is not exactly-one-storage-rule-document-for-the-bucket"

for a in exports-objects-transition-to-glacier-instant-retrieval \
         the-transition-happens-after-ninety-days \
         the-other-teams-rule-still-deletes-logs-after-thirty-days \
         the-two-rules-cover-exactly-the-two-prefixes \
         there-is-still-exactly-one-bucket-tf; do
  grep -q "  PASS \[$a\]" "$LOG" \
    || proof_failed "$a did not PASS -- both rules ARE present in this artifact (one per resource), so every value-level assert must still hold; if one of them fails, this fixture's 0.0 is not attributable to the cardinality catch"
done

grep -q 'tier1_status=PASS' "$LOG" \
  || proof_failed "tier 1 did not PASS -- both rules here are Enabled, so the un-enabled-rule policy must not fire; a tier-1 failure would mean this fixture is scoring 0.0 for the wrong catch"

echo "FIXTURE SELF-PROOF OK: the two-document shape is invisible to every static check in this oracle except exactly-one-storage-rule-document-for-the-bucket"
exit 0
