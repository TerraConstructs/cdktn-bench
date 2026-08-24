#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md 8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-17 REGRESSION FIXTURE -- THE VALUE-LIST LAUNDER, INLINE `policy`
# route. The SECOND accepted TF policy shape (`policy` set directly on
# `aws_sns_topic`, the provider's own first-listed example) carrying the
# same defect as `sns-topic-policy-source-arn-ored-with-a-wildcard`: the
# `aws:SourceArn` condition position holds the wired bucket AND a wildcard,
# and IAM OR-s the values inside one position, so any S3 bucket in any
# account can publish to the audit topic.
#
# It ships because the two shapes drifting apart is exactly what the round-16
# launder exploited. Both read the SAME `granting_statements` /
# `_position_is_scoped` helpers, and this fixture is what proves that rather
# than asserting it.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  media_arn = aws_s3_bucket.media.arn
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
  source_arn    = aws_s3_bucket.media.arn
}

# BUG: inline `policy` set directly on aws_sns_topic (the provider's other
# documented shape -- no separate aws_sns_topic_policy resource at all),
# but with NO Condition block -- grants s3.amazonaws.com sns:Publish
# unconditionally, never scoped to this scenario's bucket. The catch this
# fixture exists to violate.
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
        ArnLike = { "aws:SourceArn" = [local.media_arn, "arn:aws:s3:::*"] }
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

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}
HCL

bash tests/static_tiers.sh
