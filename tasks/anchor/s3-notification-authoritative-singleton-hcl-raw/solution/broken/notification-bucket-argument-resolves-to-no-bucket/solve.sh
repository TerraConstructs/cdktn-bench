#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 14 (2026-08-24) -- THE ANCHOR ITSELF IS THE DEFECT, and it must be
# a DENY rather than a widening. Reproduction 2 of the verifier's blocker:
# it scored REWARD 1.0 under round 13.
#
#     locals { notif_bucket = format("%s", aws_s3_bucket.media.id) }
#     resource "aws_s3_bucket_notification" "media" {
#       bucket = local.notif_bucket
#       ...
#     }
#
# `format(...)` is an opaque expression this resolver refuses to evaluate
# (by design -- see oracles/rego/lib/hcl_traversal.rego's header), and
# terraform cannot fold it either, so the plan's `.values.bucket` is
# UNKNOWN. Neither of the anchor's two routes identifies a bucket: the
# reference route dead-ends on the function call, and the plan-value route
# has no plan-time-known string to match. With no anchor, "which bucket
# must the invoke permission name" has no answer -- and round 13 answered
# it by widening to a resource-TYPE test, which accepted the decoy bucket's
# ARN and scored this artifact 1.0.
#
# Round 14 DENIES instead. Three deny messages fire and all three trace to
# the one cause, which is stated rather than hidden: the notification's own
# anchor deny names the argument and quotes both routes' failure; the
# `source_arn` slot and the topic-policy document each report that there is
# nothing to check WHICH instance they name against. That is deliberate --
# the anchor is load-bearing for all three rules, so there is no spelling
# of this fixture that produces exactly one deny.
#
# The decoy bucket is kept so the artifact is GENUINELY BROKEN and not
# merely unresolvable: S3 can never invoke the function here.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  notif_bucket = format("%s", aws_s3_bucket.media.id)
  arns = {
    media_bucket = aws_s3_bucket.media.arn
    audit_topic  = aws_sns_topic.audit.arn
  }
}

resource "aws_s3_bucket" "media" {
  bucket = "cdktn-bench-media-ingest-media"
}

resource "aws_s3_bucket" "decoy" {
  bucket = "cdktn-bench-media-ingest-decoy"
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
  source_arn    = aws_s3_bucket.decoy.arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

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
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.decoy.arn }
      }
    }]
  })
}

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
resource "aws_s3_bucket_notification" "media" {
  bucket = local.notif_bucket

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
HCL

bash tests/static_tiers.sh
