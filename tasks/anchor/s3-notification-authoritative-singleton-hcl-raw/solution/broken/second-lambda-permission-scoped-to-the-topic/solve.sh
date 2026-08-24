#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 CROSS-ARM CONTROL (2026-08-23; DECISIONS.md Amendment 29 §4
# RULING 2). The hcl_raw twin of the awscdk fixture of the same name: a
# fully correct invoke permission PLUS a second one whose `source_arn` is
# the AUDIT TOPIC's ARN -- an ordinary copy/paste defect in a
# configuration that has two ARNs hoisted into its own `locals` block.
#
# What it proves: `policy.rego` quantifies `some rp in
# s3_invoke_permissions` -- PER PLAN ADDRESS -- so the second permission is
# denied on its own even though the first one is correctly scoped. The
# retired cfn-guard bundle on awscdk could not express that (its `let`
# bindings flatten SourceArn targets across all matching resources, so it
# asked "is SOME permission scoped to a bucket?" and answered yes); the
# round-10 Rego port makes the awscdk rule quantify per LOGICAL ID, so
# both arms now grade this artifact the same way at tier 1.
#
# HONEST SCOPE NOTE, mirroring the awscdk twin's: this shape was never a
# reward-level parity break. Tier-0's `lambda-permission-principal-is-s3`
# uses op `eq` (exactly one resolved node), so any two-permission artifact
# already failed tier-0 identically on both arms, for reward 0.0 on both.
# What differed -- and what these two fixtures keep falsified -- is the
# tier-1 RULE.
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

# Correct.
resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.media_bucket_arn
}

# BUG: a SECOND s3.amazonaws.com invoke grant, scoped to the audit TOPIC's
# ARN instead of the bucket's. Nothing ties it to the bucket, and an
# aws:SourceArn naming an SNS topic never matches an S3 invocation -- so
# the grant is effectively unbounded for its stated purpose while still
# passing any "at least one permission is scoped to the bucket" check.
resource "aws_lambda_permission" "allow_s3_invoke_legacy" {
  statement_id  = "AllowS3InvokeLegacy"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.audit_topic_arn
}

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

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
