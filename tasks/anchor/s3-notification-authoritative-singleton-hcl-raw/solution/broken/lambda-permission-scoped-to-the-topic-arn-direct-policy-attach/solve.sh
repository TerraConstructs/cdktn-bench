#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-11 ARM-PARITY FIX (2026-08-23). The sibling fixture
# `lambda-permission-scoped-to-the-topic-arn-behind-a-local` is the SAME
# defect (an s3 invoke permission scoped to the AUDIT TOPIC's ARN through a
# `locals` hoist). Round 10 closed it by PROVENANCE, but collected the
# candidate topic symbols from ONE slot only --
# `aws_sns_topic_policy.arn` -- so an adversarial verifier defeated the fix
# by spelling that one unrelated argument MORE idiomatically: attach the
# topic policy with a direct `arn = aws_sns_topic.audit.arn` and the
# provenance set goes empty, the bug untouched. That scored reward 1.0 on
# hcl_raw while the awscdk twin scored 0.0 -- the round-10 break, live
# again one token later.
#
# CLOSED at round 11 by widening `topic_denoting_indirections` to EVERY
# plan slot that can hold nothing but a topic ARN --
# `aws_s3_bucket_notification.topic[*].topic_arn` (the one used here; every
# solution that wires the topic at all has it, whichever policy shape it
# chose), `aws_sns_topic_policy.arn`, and
# `aws_sns_topic_subscription.topic_arn`. This fixture is the falsification
# of the notification-slot half.
#
# Everything else is the reference solution with the topic policy written
# in its direct form. Tier-0 passes; reward must be 0.0 from tier-1
# (lambda-permission-scoped-to-bucket-tf) alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # Referenced twice below -- the notification's `topic_arn` and (by
  # mistake) the invoke permission's `source_arn`.
  audit_topic_arn = aws_sns_topic.audit.arn
}

resource "aws_s3_bucket" "media" {
  bucket = "cdktn-bench-media-ingest-media"
}

resource "aws_iam_role" "ingest" {
  name = "cdktn-bench-media-ingest-handler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name = "cdktn-bench-media-ingest-transcode"
  role          = aws_iam_role.ingest.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  # BUG: the AUDIT TOPIC's ARN, one paste away from the bucket's. No S3
  # invocation ever presents a topic ARN as its source, so nothing ties
  # this grant to the bucket.
  source_arn    = local.audit_topic_arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# Correct, and written in the DIRECT spelling on purpose: this is the one
# argument the round-11 verifier changed to defeat round 10's fix.
resource "aws_sns_topic_policy" "audit" {
  arn = aws_sns_topic.audit.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.audit.arn
      Condition = {
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.media.arn }
      }
    }]
  })
}

resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  topic {
    # The dedicated single-ARN slot that identifies `local.audit_topic_arn`
    # as the TOPIC's ARN, whatever shape the topic policy takes.
    topic_arn = local.audit_topic_arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
