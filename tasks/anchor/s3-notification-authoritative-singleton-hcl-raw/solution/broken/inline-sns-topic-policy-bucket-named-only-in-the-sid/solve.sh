#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-16 REGRESSION FIXTURE -- THE `Sid` LAUNDER, INLINE-POLICY SHAPE.
# `inline-sns-topic-policy-not-scoped-to-bucket` with ONE line changed:
#
#     Sid = "AllowS3Publish"  ->  Sid = "AllowS3Publish${aws_s3_bucket.media.id}"
#
# It exists as its own fixture because the launder flipped BOTH accepted
# TF policy shapes -- the standalone `aws_sns_topic_policy` and the
# `policy` argument set inline on `aws_sns_topic` -- and it flipped both
# because the two rules were the same MENTION test written twice. They are
# now the same POSITION test written twice, over the same helpers, and
# these two fixtures are what keeps the pair from drifting apart again.
# The grant is still unconditioned: any S3 bucket in any account may
# publish to the audit topic.
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
      Sid       = "AllowS3Publish${aws_s3_bucket.media.id}"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = "arn:aws:sns:us-east-1:123456789012:cdktn-bench-media-ingest-audit"
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
