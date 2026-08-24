#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 (2026-08-23). Falsifies `policy.rego`'s tier-1 FAIL-CLOSED
# companion rule ("an aws_s3_bucket exists, but no aws_lambda_permission
# resource granting principal s3.amazonaws.com exists anywhere in the
# plan"), which no fixture on any arm had ever exercised -- an unfalsified
# rule is an untested rule. The awscdk twin of the same name does the same
# for that arm's mirror of this rule.
#
# HONEST NOTE ON TIER ATTRIBUTION, because this fixture cannot isolate its
# rule and claiming otherwise would be false: with zero permissions in the
# plan, tier-0's `lambda-permission-principal-is-s3` (op `eq`, which
# requires EXACTLY ONE resolved node) also fails, so both tiers reject this
# artifact. That is a property of the scenario, not a gap -- every artifact
# that can trigger the fail-closed rule necessarily resolves that tier-0
# path to zero nodes. The rule is still genuinely exercised (`tier1_status=
# FAIL`, with exactly this message in the deny set). It is an EXTRA fixture
# precisely so gates/oracle_falsifiability.py checks reward only (0.0),
# with no predicted_tier_caught claim attached.
set -euo pipefail

cat > main.tf <<'HCL'
locals {
  media_bucket_arn = aws_s3_bucket.media.arn
  audit_topic_arn  = aws_sns_topic.audit.arn
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

# BUG: no aws_lambda_permission resource at all -- S3 is authorised to
# invoke nothing, so the ObjectCreated notification silently never fires.

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

resource "aws_sns_topic_policy" "audit" {
  arn = local.audit_topic_arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.audit_topic_arn
      Condition = {
        ArnLike = { "aws:SourceArn" = local.media_bucket_arn }
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

  depends_on = [aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
