#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 CROSS-ARM CONTROL (2026-08-23). The hcl_raw half of the
# round-10 arm-parity reproduction (see this scenario's spec.yaml
# VERIFIER-REJECTION FIX PASS (round 10) header). Its awscdk twin, of the
# same name, composes the SAME unrelated bucket ARN with `cdk.Fn.sub`;
# here the interpolation comes from a `data "aws_partition"` lookup. Both
# spellings dress a hardcoded literal up as a computed value; neither
# creates a graph edge to `aws_s3_bucket.media`.
#
# This fixture is the standing proof that the two arms now agree. Before
# the round-10 tier-1 engine port, this artifact scored 0.0 here (its
# `source_arn` references list is
# ["data.aws_partition.current.partition", "data.aws_partition.current"] --
# no aws_s3_bucket, no local./var. indirection) while its awscdk twin
# scored 1.0, because cfn-guard 3.2.0 cannot parse a logical id out of an
# Fn::Sub template string and so accepted any Fn::Sub as "an intrinsic,
# not a literal". Nothing in the hcl_raw grading changed at round 10 --
# `arn_slot_denotes` denied this shape all along. The fixture is added so
# that the agreement is re-proven by `make falsifiability` on every run
# instead of being asserted once in a header.
#
# Everything else is correct (one authoritative
# aws_s3_bucket_notification, both event families wired, SNS half fully
# correct including its topic policy). Tier-0 still passes; reward must be
# 0.0 from tier-1 (lambda-permission-scoped-to-bucket-tf) alone.
set -euo pipefail

cat > main.tf <<'HCL'
locals {
  media_bucket_arn = aws_s3_bucket.media.arn
  audit_topic_arn  = aws_sns_topic.audit.arn
}

data "aws_partition" "current" {}

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

  # BUG: the partition really is interpolated, but the bucket name is a
  # hardcoded literal naming a bucket this configuration does not create.
  # The grant is not tied to this configuration's bucket at all.
  source_arn = "arn:${data.aws_partition.current.partition}:s3:::some-totally-unrelated-bucket"
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
