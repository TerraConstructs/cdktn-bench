#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md 8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-17 REGRESSION FIXTURE -- the VALUE-LIST launder with a SECOND,
# UNWIRED BUCKET rather than a wildcard, so the defect cannot be dismissed
# as "only a literal string sneaks through". The `aws:SourceArn` condition
# position holds [the wired bucket's arn, a decoy bucket's arn]; IAM OR-s
# them, so the decoy bucket -- which this configuration's own
# `aws_s3_bucket_notification` does NOT wire -- can publish to the audit
# topic. Both values are fully-resolvable references, so nothing about this
# shape is unreadable; it is simply not scoped. Sibling of
# `sns-topic-policy-source-arn-ored-with-a-wildcard`.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # media_bucket is referenced twice below (the invoke permission and the
  # topic policy's condition); audit_topic three times (the topic policy's
  # own `arn`, that policy's `Resource`, and the notification's
  # `topic_arn`). One map, the ordinary DRY spelling.
  arns = {
    media_bucket = aws_s3_bucket.media.arn
    audit_topic  = aws_sns_topic.audit.arn
  }
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
  source_arn    = local.arns.media_bucket
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# S3 cannot publish to a topic with no resource policy granting it
# sns:Publish -- part of "the topic must receive a notification"
# (this scenario's own oracle.intent), not an add-on. Scoped via
# aws:SourceArn to this specific bucket -- the sns-topic-policy-not-
# scoped-to-bucket catch's own target.
resource "aws_sns_topic_policy" "audit" {
  arn = local.arns.audit_topic
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.arns.audit_topic
      Condition = {
        ArnLike = { "aws:SourceArn" = [local.arns.media_bucket, aws_s3_bucket.decoy.arn] }
      }
    }]
  })
}

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  topic {
    topic_arn = local.arns.audit_topic
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
resource "aws_s3_bucket" "decoy" {
  bucket = "cdktn-bench-media-ingest-decoy"
}

HCL

bash tests/static_tiers.sh
