#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-not-migrated`, whose predicted_tier_caught is "live" on
# this arm.
#
# THE MISTAKE: the plausible, competent-looking answer. It turns ACLs off on
# the access-logs bucket exactly as the ticket asks, it keeps the logging
# configuration exactly where it was, and it WRITES A BUCKET POLICY -- it just
# writes the wrong grant. `delivery.logs.amazonaws.com` is the delivery
# principal CloudWatch Logs / VPC flow logs / Firehose use; S3 server access
# logging uses `logging.s3.amazonaws.com`, and nothing anywhere in the
# workspace says so. Every static signal stays green: the plan is green, the
# apply is green, `GetBucketLogging` keeps returning the same answer it always
# did, and the log objects silently stop arriving.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no credentials
# and no account, this script:
#
#   1. plans the REFERENCE shape (Principal `logging.s3.amazonaws.com`) in a
#      scratch directory and captures the whole graded artifact --
#      `terraform show -json`'s plan JSON;
#   2. plans THIS shape (Principal `delivery.logs.amazonaws.com`) and captures
#      the same;
#   3. normalises away the two fields that are nondeterministic between any two
#      runs of the same configuration -- `.timestamp`, and the ORDER of
#      `.relevant_attributes`, which terraform emits unsorted -- and requires
#      the two documents to be otherwise IDENTICAL.
#
# If they are, no tier-0 assert, no jq path and no Rego rule over the graded
# artifact can tell the reference solution from this fixture, because the
# policy document itself never reaches the artifact: `aws_s3_bucket_policy
# .policy` is a `jsonencode(...)` interpolating `aws_s3_bucket.access_logs.arn`,
# which is provider-computed and therefore plan-time-UNKNOWN, so
# `.planned_values` carries no `policy` key at all and `.configuration` reduces
# the whole expression to its reference list. Measured directly, 2026-08-26,
# before this scenario was frozen; re-measured here on every
# `make falsifiability`. If a future terraform/provider release starts emitting
# the rendered document, step 3 fails, the marker is not printed, the gate
# turns red, and this catch gets re-tiered instead of quietly continuing to
# claim an invisibility it no longer has.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
#
# LIVE=1 additionally proves the catch is REAL rather than merely invisible:
# the two-phase rollout is run for real, the applies must SUCCEED (this
# fixture's whole point is that nothing complains), and only then is the live
# oracle consulted with `--expect stale`. That ordering matters -- see the
# comment at the LIVE block.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
LIVE="${LIVE:-0}"
WORK="$(pwd)"
PROBE_DIR="${TMPDIR:-/tmp}/s3-acl-ownership-live-only-probe.$$"

BUCKETS_AND_LOGGING='
resource "aws_s3_bucket" "app_data" {
  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  tags = {
    Name = "application-storage-app-data"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  tags = {
    Name = "application-storage-access-logs"
  }
}

resource "aws_s3_bucket_logging" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "app-data/"
}
'

REFERENCE_PRINCIPAL="logging.s3.amazonaws.com"
FIXTURE_PRINCIPAL="delivery.logs.amazonaws.com"

# $1 -- the service principal the bucket policy grants to.
write_shape() {
  cat > main.tf <<TF
${BUCKETS_AND_LOGGING}
resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "S3ServerAccessLogsPolicy"
        Effect    = "Allow"
        Principal = { Service = "${1}" }
        Action    = ["s3:PutObject"]
        Resource  = "\${aws_s3_bucket.access_logs.arn}/app-data/*"
        Condition = {
          ArnLike = { "aws:SourceArn" = aws_s3_bucket.app_data.arn }
        }
      },
    ]
  })
}
TF
}

# ROLLOUT STEP 1 ONLY -- never graded, identical to the reference solution's.
write_acl_reset() {
  cat > main.tf <<TF
${BUCKETS_AND_LOGGING}
resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [aws_s3_bucket_ownership_controls.access_logs]

  bucket = aws_s3_bucket.access_logs.id
  acl    = "private"
}
TF
}

# --- the mechanical static-indistinguishability proof -----------------------
# Run in a scratch copy so the probe's own plan files never pollute the graded
# working tree.
mkdir -p "$PROBE_DIR"
trap 'rm -rf "$PROBE_DIR"' EXIT
cp provider.tf "$PROBE_DIR/provider.tf"

artifact_for() {
  # $1 -- the service principal; echoes the NORMALISED graded artifact.
  (
    cd "$PROBE_DIR" \
      && write_shape "$1" \
      && terraform init -input=false >/dev/null \
      && terraform plan -input=false -refresh=false -out=probe.tfplan >/dev/null \
      && terraform show -json probe.tfplan \
      | jq -S 'del(.timestamp) | .relevant_attributes |= sort'
  )
}

REFERENCE_ARTIFACT="$(artifact_for "$REFERENCE_PRINCIPAL")"
FIXTURE_ARTIFACT="$(artifact_for "$FIXTURE_PRINCIPAL")"

echo "== static-indistinguishability probe: graded artifact, whole plan JSON =="
if [ "$REFERENCE_ARTIFACT" = "$FIXTURE_ARTIFACT" ]; then
  echo "$MARKER: 'terraform show -json' emits an IDENTICAL plan JSON document"
  echo "  (modulo .timestamp and the unsorted .relevant_attributes list) for a"
  echo "  bucket policy granting '$REFERENCE_PRINCIPAL' and one granting"
  echo "  '$FIXTURE_PRINCIPAL'. aws_s3_bucket_policy.policy interpolates the"
  echo "  bucket's provider-computed ARN, so it is plan-time-unknown: no"
  echo "  'policy' key reaches .planned_values, and .configuration reduces the"
  echo "  whole jsonencode() expression to a reference list. No tier-0 assert,"
  echo "  Rego rule or jq path over the graded artifact can distinguish the"
  echo "  reference solution from this fixture. The catch is live-only by"
  echo "  construction, not by oracle weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the graded artifact DOES" >&2
  echo "differ between a correct and an incorrect log-delivery grant on this" >&2
  echo "arm. This catch is no longer 'live'-tier -- re-tier it in the spec and" >&2
  echo "add a real static assert. Diff:" >&2
  diff <(echo "$REFERENCE_ARTIFACT") <(echo "$FIXTURE_ARTIFACT") >&2 || true
fi

# --- the fixture itself: the wrong grant, left in place for grading ---------
cd "$WORK"
write_shape "$FIXTURE_PRINCIPAL"

if [ "$LIVE" = "1" ]; then
  # FIXTURE SELF-PROOF. `--expect stale` requires only `outcome ==
  # "fail_stale"`, and live_check.observe() reports fail_stale for ANY
  # unsatisfied assertion -- INCLUDING "the rollout never ran", which is true
  # BY CONSTRUCTION here: workspace_seed.deploy has the harness put the
  # ACL-granted, ACLs-enabled system in the account before this script starts,
  # so the seed state alone already satisfies `fail_stale`. A bare
  # `apply || true; live_check --expect stale` would therefore be green even if
  # this fixture did nothing at all -- the exact free pass this repo keeps
  # finding.
  #
  # So the specific failure is proved first, and it is the OPPOSITE of the
  # sibling brownfield scenario's: there the apply had to FAIL loudly; here it
  # must SUCCEED, because "everything is green and the logs stop anyway" IS the
  # catch. Both applies must exit 0 before the live oracle is consulted.
  echo "== LIVE step 1/2: reset the destination bucket's ACL (identical to the reference) =="
  write_acl_reset
  terraform init -input=false
  terraform apply -input=false -auto-approve

  echo "== LIVE step 2/2: disable ACLs, write the WRONG grant -- expected to succeed =="
  write_shape "$FIXTURE_PRINCIPAL"
  terraform init -input=false
  if ! terraform apply -input=false -auto-approve; then
    echo "FIXTURE PROOF FAILED: the apply exited non-zero." >&2
    echo "This fixture exists to pin a change that DEPLOYS CLEANLY and breaks" >&2
    echo "log delivery anyway. A failed apply means the trial hit some other" >&2
    echo "problem -- credentials, a leftover ACL grant, a broken toolchain --" >&2
    echo "and any of those would ALSO reach live_check.py's 'fail_stale' and be" >&2
    echo "laundered into a green '--expect stale'." >&2
    exit 1
  fi
  echo "== both applies succeeded, as this fixture requires =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
