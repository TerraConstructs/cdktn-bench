#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-16 REGRESSION FIXTURE -- THE `Sid` LAUNDER. This file is
# `sns-topic-policy-not-scoped-to-bucket` with ONE line changed:
#
#     Sid = "AllowS3Publish"  ->  Sid = "AllowS3Publish${aws_s3_bucket.media.id}"
#
# Nothing else differs. The topic policy STILL grants s3.amazonaws.com
# sns:Publish with NO aws:SourceArn condition of any kind, so any S3
# bucket in any account can publish to the audit topic -- exactly the
# defect the fixture it is derived from exists to describe.
#
# Until round 16 that ONE line moved this artifact from REWARD 0.0 to
# REWARD 1.0, executed, image built from this task own Dockerfile,
# `docker run --network none`, generated tests/static_tiers.sh verbatim.
# The topic-policy rule was a MENTION test -- it required only that SOME
# reference ANYWHERE in the whole policy document resolve to the wired
# bucket, with no position requirement at all -- and a reference inside a
# `Sid` string satisfied it. The rule is now POSITIONAL (every statement
# granting s3.amazonaws.com sns:Publish must carry an aws:SourceArn
# condition naming a wired bucket), and this fixture is what keeps it that
# way. Its twin on the awscdk arm is
# `hand-authored-topic-policy-bucket-named-only-in-the-sid`.
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

# BUG: no Condition block at all -- grants s3.amazonaws.com sns:Publish
# unconditionally, never scoped to this scenario's bucket (or any bucket
# in particular). The catch this fixture exists to violate.
resource "aws_sns_topic_policy" "audit" {
  arn = aws_sns_topic.audit.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish${aws_s3_bucket.media.id}"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.audit.arn
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
