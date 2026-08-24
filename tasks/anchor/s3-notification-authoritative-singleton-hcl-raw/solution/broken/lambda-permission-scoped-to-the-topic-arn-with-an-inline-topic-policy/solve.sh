#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-11 ARM-PARITY FIX (2026-08-23), second spelling. Same defect as
# `lambda-permission-scoped-to-the-topic-arn-behind-a-local`, expressed
# with the provider's OTHER documented topic-policy shape -- `policy` set
# inline on `aws_sns_topic` itself, which this spec declares equally
# acceptable ("oracle must tolerate/defend" point 6). Round 10's
# provenance fix read topic symbols out of `aws_sns_topic_policy.arn`
# ONLY, and that resource does not exist here at all, so the fix could
# never fire for this shape: the evasion was unconditional, not merely
# one-token.
#
# CLOSED at round 11: `topic_denoting_indirections` now also reads
# `aws_s3_bucket_notification.topic[*].topic_arn`, a slot every solution
# that wires the topic has, whichever policy shape it chose. This fixture
# is the falsification of that clause under the inline shape.
#
# The topic policy itself is CORRECT here (scoped to this bucket via
# aws:SourceArn), so the inline-shape SNS rules stay silent and this
# fixture isolates the Lambda-side clause. Tier-0 passes; reward must be
# 0.0 from tier-1 (lambda-permission-scoped-to-bucket-tf) alone.
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
  # BUG: the AUDIT TOPIC's ARN in the bucket's slot.
  source_arn    = local.audit_topic_arn
}

# The inline shape: `policy` set directly on the topic, no separate
# aws_sns_topic_policy resource anywhere in this configuration. Its
# scoping is CORRECT (aws:SourceArn names this bucket) -- the only defect
# in this file is the invoke permission above.
resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = "arn:aws:sns:us-east-1:123456789012:cdktn-bench-media-ingest-audit"
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
    topic_arn = local.audit_topic_arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}
HCL

bash tests/static_tiers.sh
