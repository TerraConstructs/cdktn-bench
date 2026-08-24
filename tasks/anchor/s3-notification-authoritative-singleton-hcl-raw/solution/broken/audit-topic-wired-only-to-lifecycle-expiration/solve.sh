#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the NEW (round 6) audit-topic-events-cover-a-real-
# delete tier-1 rule: both requirements are otherwise wired correctly
# (one authoritative notification resource, Lambda half fully correct
# including its scoped permission, topic policy correctly scoped) -- but
# the topic target's events are `["s3:LifecycleExpiration:*"]` ONLY, with
# NO `s3:ObjectRemoved:*`-family entry anywhere. This passes the tier-0
# six-literal whitelist outright (its one resolved event IS a member of
# the six) but s3:LifecycleExpiration:* never fires for an ordinary
# user-initiated delete -- only for one S3's own Lifecycle engine
# performs (AWS's own S3 User Guide) -- so "when any object is deleted"
# is not actually satisfied. Reward must be 0.0 from tier-1
# (audit-topic-events-cover-a-real-delete) alone.
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

  # BUG: LifecycleExpiration ONLY -- no s3:ObjectRemoved:* / :Delete /
  # :DeleteMarkerCreated entry anywhere. Passes the tier-0 whitelist
  # (a member of the six-literal set) but never fires for an ordinary
  # user-initiated delete -- the catch this fixture exists to violate.
  topic {
    topic_arn = aws_sns_topic.audit.arn
    events    = ["s3:LifecycleExpiration:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
