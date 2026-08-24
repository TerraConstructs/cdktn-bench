#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the only-one-of-the-two-events-wired catch: wires the
# Product half only (upload -> transcode, correctly scoped) and never
# creates the SNS topic, its policy, or any ObjectRemoved wiring at all --
# the Compliance half of the ticket is dropped entirely. Reward must be
# 0.0 from tier-0 alone (sns-topic-exists and
# object-removed-notification-targets-a-topic both resolve 0 nodes).
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

# BUG: no aws_sns_topic, no aws_sns_topic_policy, no `topic` block below --
# the Compliance ask was never attempted.
resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}
HCL

bash tests/static_tiers.sh
