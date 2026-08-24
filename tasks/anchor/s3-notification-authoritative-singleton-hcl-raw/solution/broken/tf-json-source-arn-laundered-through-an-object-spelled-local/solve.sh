#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 14 (2026-08-24) -- THE ONLY FIXTURE IN THIS DIRECTORY THAT IS NOT
# WRITTEN IN NATIVE HCL. It is authored in terraform's own JSON SYNTAX
# (`main.tf.json`), and its defect is the ordinary laundering one: the
# `locals` entry `arns.media_bucket` holds the LAMBDA's own ARN, so
# `source_arn` grants S3 the right to invoke a function scoped to the
# function itself and S3 can never invoke it.
#
# WHY IT IS SHAPED THAT WAY -- it is a DISCRIMINATING regression test for
# the `.tf.json` half of the harness glob, which was advertised and did not
# work:
#
#   * hcl2json (over a `.tf`) emits `"locals": [ {...} ]` -- a LIST of
#     blocks. Terraform's own JSON syntax writes `"locals": { "<name>": ... }`
#     -- a bare OBJECT -- and the harness loads a `.tf.json` RAW, because it
#     is already JSON.
#   * The shared library read only the LIST spelling, so `some blk in
#     <object>` iterated the local VALUES (strings), every one of which
#     failed `is_object`, and EVERY local in an object-spelled `main.tf.json`
#     was silently dropped. A fully CORRECT `.tf.json` solution scored 0.0,
#     denied with "no `locals` block in any supplied .tf file defines
#     local.arns.media_bucket" -- about a supplied file that plainly did
#     define it (Amendment 29 sect 6 RULING 3: a deny message the artifact
#     contradicts).
#
# A fixture that merely DENIED would not detect a regression of that bug:
# with the locals dropped, `local.arns.media_bucket` is UNRESOLVABLE, which
# also denies. What discriminates is WHAT THE MESSAGE SAYS. This artifact
# must be denied with the referent NAMED --
# `aws_lambda_function.ingest.arn` -- which is only possible if the
# object-spelled `locals` was actually read and resolved. The assertion
# below is part of the fixture, not commentary: it fails the run loudly if
# the deny message ever regresses to the "no locals block" shape.
#
# The POSITIVE twin (a fully CORRECT `.tf.json` solution, which must score
# 1.0) cannot live under solution/broken/ -- the falsifiability gate has
# exactly one positive slot -- so it is asserted in
# oracles/tests/test_hcl_traversal.py::
# test_a_correct_tf_json_solution_denies_nothing, alongside a per-spelling
# resolver test.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

rm -f main.tf
cat > main.tf.json <<'CDKTN_TF_JSON'
{
  "locals": {
    "arns": {
      "media_bucket": "${aws_lambda_function.ingest.arn}",
      "audit_topic": "${aws_sns_topic.audit.arn}"
    }
  },
  "resource": {
    "aws_s3_bucket": {
      "media": { "bucket": "cdktn-bench-media-ingest-media" }
    },
    "aws_iam_role": {
      "ingest": {
        "name": "cdktn-bench-media-ingest-handler-role",
        "assume_role_policy": "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"lambda.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}"
      }
    },
    "aws_lambda_function": {
      "ingest": {
        "function_name": "cdktn-bench-media-ingest-transcode",
        "role": "${aws_iam_role.ingest.arn}",
        "handler": "index.handler",
        "runtime": "nodejs22.x",
        "filename": "function.zip"
      }
    },
    "aws_lambda_permission": {
      "allow_s3_invoke": {
        "statement_id": "AllowS3Invoke",
        "action": "lambda:InvokeFunction",
        "function_name": "${aws_lambda_function.ingest.function_name}",
        "principal": "s3.amazonaws.com",
        "source_arn": "${local.arns.media_bucket}"
      }
    },
    "aws_sns_topic": {
      "audit": { "name": "cdktn-bench-media-ingest-audit" }
    },
    "aws_sns_topic_policy": {
      "audit": {
        "arn": "${local.arns.audit_topic}",
        "policy": "${jsonencode({\"Version\" = \"2012-10-17\", \"Statement\" = [{\"Sid\" = \"AllowS3Publish\", \"Effect\" = \"Allow\", \"Principal\" = {\"Service\" = \"s3.amazonaws.com\"}, \"Action\" = \"SNS:Publish\", \"Resource\" = local.arns.audit_topic, \"Condition\" = {\"ArnLike\" = {\"aws:SourceArn\" = aws_s3_bucket.media.arn}}}]})}"
      }
    },
    "aws_s3_bucket_notification": {
      "media": {
        "bucket": "${aws_s3_bucket.media.id}",
        "lambda_function": [
          {
            "lambda_function_arn": "${aws_lambda_function.ingest.arn}",
            "events": ["s3:ObjectCreated:Put"]
          }
        ],
        "topic": [
          {
            "topic_arn": "${local.arns.audit_topic}",
            "events": ["s3:ObjectRemoved:*"]
          }
        ],
        "depends_on": [
          "aws_lambda_permission.allow_s3_invoke",
          "aws_sns_topic_policy.audit"
        ]
      }
    }
  }
}
CDKTN_TF_JSON

RC=0
bash tests/static_tiers.sh || RC=$?

# ---------------------------------------------------------------------------
# THE DISCRIMINATING HALF -- and why it edits reward.txt on failure
# ---------------------------------------------------------------------------
# reward 0.0 alone does NOT prove the `.tf.json` locals were read: with them
# dropped, `local.arns.media_bucket` is merely UNRESOLVABLE, which also
# denies and also scores 0.0. What discriminates is WHAT THE DENY SAYS, so
# this fixture re-evaluates the same merged document the tier-1 step built
# and requires the message to NAME the referent the object-spelled local
# actually holds.
#
# gates/oracle_falsifiability.py grades a negative fixture on reward.txt
# ALONE and ignores this script's exit status, so a bare `exit 1` here would
# be invisible to the gate. On regression this therefore REMOVES reward.txt,
# which the gate reports as "no reward.txt written" together with this
# script's stderr -- loud, and attributed to this fixture. It never writes a
# passing reward; the failure mode is "this negative is no longer valid",
# not a fabricated score. (This file is a gate fixture and is never run in a
# real trial.)
#
# The merged-document path is read back OUT OF the script that just ran
# rather than hardcoded: the gate rewrites `/logs/verifier` inside
# tests/static_tiers.sh to a host sandbox directory, so a hardcoded
# `/logs/verifier/...` here would silently skip this check on every
# host-side gate run and only ever fire inside a real container.
fail_regression() {
  echo "REGRESSION in the .tf.json half of the oracle.hcl_traversal glob:" >&2
  echo "$1" >&2
  LOGDIR="${HCL_MERGED:+$(dirname "$HCL_MERGED")}"
  [ -n "${LOGDIR:-}" ] && rm -f "$LOGDIR/reward.txt"
  exit 1
}

HCL_MERGED="$(sed -n 's/^HCL_MERGED="\(.*\)"$/\1/p' tests/static_tiers.sh | head -1)"
if [ -z "${HCL_MERGED:-}" ]; then
  echo "REGRESSION: tests/static_tiers.sh declares no HCL_MERGED path -- the" >&2
  echo "oracle.hcl_traversal merge step is gone, so this fixture cannot prove" >&2
  echo "what it exists to prove." >&2
  exit 1
fi
[ -s "$HCL_MERGED" ] || fail_regression \
  "no merged oracle input at $HCL_MERGED -- the *.tf.json glob did not run, or produced nothing."

if command -v opa >/dev/null 2>&1; then
  DENY_LOG="$(dirname "$HCL_MERGED")/tf-json-deny-check.log"
  opa eval -f raw -I -d tests/policy.rego -d tests/hcl_traversal.rego \
    'data.cdktn_bench.s3_notification_authoritative_singleton.deny' \
    < "$HCL_MERGED" > "$DENY_LOG" 2>&1 || true
  if grep -q 'aws_lambda_function\.ingest\.arn' "$DENY_LOG"; then
    echo "OK: the object-spelled main.tf.json locals WERE resolved -- the deny names aws_lambda_function.ingest.arn"
  else
    fail_regression "$(printf '%s\n' \
      "the deny message does not name aws_lambda_function.ingest.arn, so the" \
      ".tf.json 'locals' OBJECT was not read and the symbol was merely" \
      "unresolvable -- the round-14 defect, back. Deny set was:" \
      "$(cat "$DENY_LOG")")"
  fi
else
  fail_regression "opa is not on PATH, so this fixture's discriminating assertion could not run."
fi
exit "$RC"
