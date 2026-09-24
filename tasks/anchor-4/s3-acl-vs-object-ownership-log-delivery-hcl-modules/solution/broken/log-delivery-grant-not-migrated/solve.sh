#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-not-migrated`, whose predicted_tier_caught is "live" on
# this arm.
#
# THE MISTAKE: the plausible, competent-looking answer. ACLs go off on the
# access-logs bucket exactly as the ticket asks, the logging configuration stays
# where it was, and a bucket policy IS written -- with the wrong grant.
# `delivery.logs.amazonaws.com` is the delivery principal CloudWatch Logs / VPC
# flow logs / Firehose use; S3 server access logging uses
# `logging.s3.amazonaws.com`, and nothing in the workspace says so. Plan green,
# apply green, `GetBucketLogging` unchanged, log objects silently gone.
#
# WHY THIS FIXTURE USES THE CALLER-WRITTEN POLICY SHAPE
# =====================================================
# `s3-bucket` 5.16.1's `attach_access_log_delivery_policy` builds the grant
# itself, so the mistake cannot be made THROUGH that input at all -- which is
# the module removing a mistake, not hiding one. What keeps the catch on this arm
# is the caller-written shape, a root-level `aws_s3_bucket_policy` whose
# `jsonencode(...)` names the principal: this file is
# `solution/policy-written-by-the-caller/` with one word changed.
# The third conceivable shape -- handing the module its own `policy` input as a
# literal string -- is NOT used here and is an alternate-shape risk worth
# naming: that string lands in the module CALL's
# `expressions.policy.constant_value`, so it is statically visible and the
# invisibility proof below would (correctly) refuse it. No rule reads it today
# and none is added, because a rule pinned to that one spelling would score the
# other two shapes' correct solutions 0.0.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no credentials and
# no account, this script plans the correct-principal shape and this shape in a
# scratch directory, captures both graded artifacts, normalises away the two
# fields that differ between any two runs of the same configuration
# (`.timestamp`, and the ORDER of `.relevant_attributes`, which terraform emits
# unsorted), and requires the rest to be IDENTICAL.
#
# If they are, nothing over the graded artifact can tell the two apart, because
# the document never reaches it: `aws_s3_bucket_policy.policy` is a
# `jsonencode(...)` interpolating `module.access_logs.s3_bucket_arn`, which is
# provider-computed and therefore plan-time-UNKNOWN, so `.planned_values` carries
# no `policy` key and `.configuration` reduces the whole expression to its
# reference list. If a future terraform/provider release starts emitting the
# rendered document, the comparison fails, the marker is not printed, the gate
# turns red, and the catch gets re-tiered.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
#
# LIVE=1 additionally proves the catch is REAL rather than merely invisible: the
# two-phase rollout runs for real, both applies must SUCCEED (this fixture's
# whole point is that nothing complains), and only then is the live oracle
# consulted with `--expect stale`.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
LIVE="${LIVE:-0}"
WORK="$(pwd)"
PROBE_DIR="${TMPDIR:-/tmp}/s3-acl-ownership-modules-live-only-probe.$$"

REFERENCE_PRINCIPAL="logging.s3.amazonaws.com"
FIXTURE_PRINCIPAL="delivery.logs.amazonaws.com"
APP_DATA='
module "app_data" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  depends_on = [module.access_logs]

  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  attach_public_policy = false

  logging = {
    target_bucket = module.access_logs.s3_bucket_id
    target_prefix = "app-data/"
  }

  tags = {
    Name = "application-storage-app-data"
  }
}
'

# The destination-bucket call, with `object_ownership` and any extra module
# inputs supplied by the caller. $1 -- the ownership setting; $2 -- extra
# arguments, already indented.
access_logs_call() {
  cat <<TF
module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "${1}"
${2}
  tags = {
    Name = "application-storage-access-logs"
  }
}
TF
}

# ROLLOUT STEP 1 ONLY -- never graded. Ownership is still `ObjectWriter`, so
# `PutBucketAcl` is still legal here; this is the call that clears the
# log-delivery group grant out of the account so the next apply's
# `PutBucketOwnershipControls` is allowed to succeed.
write_acl_reset() {
  {
    access_logs_call "ObjectWriter" ""
    cat <<'TF'

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [module.access_logs]

  bucket = module.access_logs.s3_bucket_id
  acl    = "private"
}
TF
    printf '%s\n' "$APP_DATA"
  } > main.tf
}

# ACLs disabled, and the grant written out by the caller as a root-level
# `aws_s3_bucket_policy`. $1 -- the service principal it grants to. The document
# interpolates `module.access_logs.s3_bucket_arn`, so it is plan-time-unknown
# and never reaches the graded artifact -- which is also why handing the same
# document to the module's own `policy` input is not an option: that argument is
# read BY the call, and a value derived from the call's own output is a cycle.
write_caller_policy_shape() {
  {
    access_logs_call "BucketOwnerEnforced" ""
    cat <<TF

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = module.access_logs.s3_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "S3ServerAccessLogsPolicy"
        Effect    = "Allow"
        Principal = { Service = "${1}" }
        Action    = ["s3:PutObject"]
        Resource  = "\${module.access_logs.s3_bucket_arn}/app-data/*"
        Condition = {
          ArnLike = { "aws:SourceArn" = module.app_data.s3_bucket_arn }
        }
      },
    ]
  })
}
TF
    printf '%s\n' "$APP_DATA"
  } > main.tf
}

# --- the mechanical static-indistinguishability proof -----------------------
# Run in a scratch copy so the probe's own plan files never pollute the graded
# working tree. The vendored registry answers `init` there exactly as it does
# here -- the CLI config is the image's, not the directory's.
mkdir -p "$PROBE_DIR"
trap 'rm -rf "$PROBE_DIR"' EXIT
cp provider.tf "$PROBE_DIR/provider.tf"

artifact_for() {
  # $1 -- the service principal; echoes the NORMALISED graded artifact.
  (
    cd "$PROBE_DIR" \
      && write_caller_policy_shape "$1" \
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
  echo "  '$FIXTURE_PRINCIPAL'. The document interpolates the module's own"
  echo "  computed bucket ARN, so it is plan-time-unknown: no 'policy' key"
  echo "  reaches .planned_values and .configuration reduces the jsonencode()"
  echo "  expression to a reference list. No tier-0 assert, Rego rule or jq path"
  echo "  over the graded artifact can distinguish the second reference from"
  echo "  this fixture. The catch is live-only by construction, not by oracle"
  echo "  weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the graded artifact DOES" >&2
  echo "differ between a correct and an incorrect log-delivery grant on this" >&2
  echo "arm. This catch is no longer 'live'-tier -- re-tier it in the spec and" >&2
  echo "add a real static assert. Diff:" >&2
  diff <(echo "$REFERENCE_ARTIFACT") <(echo "$FIXTURE_ARTIFACT") >&2 || true
fi

# --- the fixture itself: the wrong grant, left in place for grading ---------
cd "$WORK"
write_caller_policy_shape "$FIXTURE_PRINCIPAL"

if [ "$LIVE" = "1" ]; then
  # FIXTURE SELF-PROOF. `--expect stale` requires only `outcome ==
  # "fail_stale"`, and live_check.observe() reports fail_stale for ANY
  # unsatisfied assertion -- INCLUDING "the rollout never ran", which is true BY
  # CONSTRUCTION here: workspace_seed.deploy puts the ACL-granted, ACLs-enabled
  # system in the account before this script starts. A bare
  # `apply || true; live_check --expect stale` would therefore be green even if
  # this fixture did nothing at all.
  #
  # So the specific failure is proved first: both applies must exit 0, because
  # "everything is green and the logs stop anyway" IS the catch.
  echo "== LIVE step 1/2: reset the destination bucket's ACL (identical to the reference) =="
  write_acl_reset
  terraform init -input=false
  terraform apply -input=false -auto-approve

  echo "== LIVE step 2/2: disable ACLs, write the WRONG grant -- expected to succeed =="
  write_caller_policy_shape "$FIXTURE_PRINCIPAL"
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
