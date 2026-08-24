#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the lambda-permission-not-scoped-to-bucket catch
# (s3-lambda-log-retention's own scoping catch, reused verbatim): both
# requirements are otherwise wired correctly (one authoritative
# notification resource, SNS half fully correct including its topic
# policy), but the Lambda permission grants principal s3.amazonaws.com
# with NO source_arn -- account-wide, not scoped to this bucket. Tier-0
# still passes (lambda-permission-principal-is-s3 only checks the
# principal); reward must be 0.0 from tier-1
# (lambda-permission-scoped-to-bucket-tf) alone.
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

# BUG: no source_arn -- grants ANY s3.amazonaws.com-principal'd caller,
# not just this scenario's bucket. The catch this fixture exists to
# violate.
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

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
    topic_arn = aws_sns_topic.audit.arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
