#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-9 (2026-08-23). Falsifies `policy.rego`'s `references_this_topic`
# clause, which until this pass had NO covering fixture at all: its only
# observed behaviour in the whole repo was a FALSE deny against a correct
# solution (an adversarial verifier PROVED by execution that hoisting the
# audit topic's ARN into a `locals` block tripped it, with a deny message
# that was factually false about that artifact). An unfalsified rule is an
# untested rule, so the clause now has this.
#
# The defect: the topic policy resource exists and its document is
# correctly scoped to this bucket, but its `arn` argument is a pasted
# literal ARN naming a topic this configuration does not create -- so the
# policy attaches to something else entirely and the audit topic is left
# with no resource policy at all. S3 silently drops every publish to it.
# Reachable by simply pasting an ARN from the console instead of
# referencing the resource.
#
# Everything else is correct (one authoritative notification resource, both
# event types wired, Lambda half fully correct including its scoped
# permission, the policy document itself correctly aws:SourceArn-scoped).
# Tier-0 still passes; reward must be 0.0 from tier-1
# (sns-topic-policy-allows-s3-publish-tf's attachment clause) alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
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
  source_arn    = aws_s3_bucket.media.arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# BUG: `arn` is a HARDCODED literal ARN naming a topic this configuration
# does not create, so this policy is attached to some other topic. The
# expression references nothing, so it has no graph edge to
# aws_sns_topic.audit. The clause this fixture exists to violate.
resource "aws_sns_topic_policy" "audit" {
  arn = "arn:aws:sns:us-east-1:123456789012:cdktn-bench-some-other-topic"
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
    topic_arn = aws_sns_topic.audit.arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
