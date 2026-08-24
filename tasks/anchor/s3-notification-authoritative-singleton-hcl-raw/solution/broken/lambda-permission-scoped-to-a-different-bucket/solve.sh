#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop -- the same mechanism
# `inline-sns-topic-policy-not-scoped-to-bucket` next to it already uses.
#
# ROUND-7 ARM-PARITY FIX (2026-08-22). This is the SECOND spelling of the
# lambda-permission-not-scoped-to-bucket catch: not an OMITTED source_arn
# (that is the sibling fixture next to this one) but a HARDCODED literal
# one naming a different, unrelated bucket. It ships on all three arms so
# the cross-arm claim can be re-proved by execution rather than asserted:
# the awscdk-side rule used to be a bare `Properties.SourceArn EXISTS`
# presence check, so this exact defect scored 1.0 there and 0.0 here. The
# awscdk rule is now a graph-edge mirror of this arm's `references_bucket`
# and all three arms score 0.0 on this shape. (ROUND 10, 2026-08-23: that
# mirror moved off cfn-guard onto OPA/Rego -- oracles/rego-cfn/s3-
# notification-authoritative-singleton/policy.rego -- because cfn-guard
# could not express the `Fn::Sub` spelling of this same defect; see the
# sibling `lambda-permission-scoped-via-an-interpolated-literal` fixture,
# which ships on both arms for exactly that spelling.)
#
# Everything else is correct (one authoritative notification resource,
# both event types wired, SNS half fully correct including its topic
# policy). Tier-0 still passes (lambda-permission-principal-is-s3 only
# reads the principal, which is right here); reward must be 0.0 from
# tier-1 (lambda-permission-scoped-to-bucket-tf) alone.
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

# BUG: source_arn is a HARDCODED literal ARN naming a bucket this
# configuration does not create -- the grant is not tied to this
# scenario's bucket at all (the expression references nothing, so it has
# no graph edge to aws_s3_bucket.media). The catch this fixture exists to
# violate.
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::some-totally-unrelated-bucket"
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
