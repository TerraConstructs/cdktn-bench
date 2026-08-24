#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- THE DEPTH EVASION. The same defect as
# `lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local` (the S3
# invoke permission is scoped to the LAMBDA'S OWN ARN), laundered through a
# five-hop `local` chain, with the topic policy left FULLY CORRECT so that
# every cross-referencing round-12 rule is satisfied.
#
# This is the verifier's evasion artifact from the spike memo (§5.8), and
# it is the reason the resolver walks chains with `graph.reachable` rather
# than hand-unrolled hops. The prototype unrolled FOUR hops; at four this
# artifact denied and at FIVE it was silent -- not because a rule decided
# it was fine, but because every clause failed and the verdict went
# UNDEFINED, which is indistinguishable from a pass in the output. Round 12
# is silent on it too, so there is no additive-merge safety net here: on
# this shape the older rules catch nothing.
#
# `graph.reachable` is a non-recursive builtin with NO depth limit that
# terminates on cycles by construction, so there is no cliff left to move.
# Executed at 1, 5 and 12 hops: all deny, all naming
# `aws_lambda_function.ingest.arn` as what the chain reaches.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # media_bucket is referenced twice below (the invoke permission and the
  # topic policy's condition); audit_topic three times (the topic policy's
  # own `arn`, that policy's `Resource`, and the notification's
  # `topic_arn`). One map, the ordinary DRY spelling.
  arns = {
    media_bucket = aws_s3_bucket.media.arn
    audit_topic  = aws_sns_topic.audit.arn
  }
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

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.a
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# S3 cannot publish to a topic with no resource policy granting it
# sns:Publish -- part of "the topic must receive a notification"
# (this scenario's own oracle.intent), not an add-on. Scoped via
# aws:SourceArn to this specific bucket -- the sns-topic-policy-not-
# scoped-to-bucket catch's own target.
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
        ArnLike = { "aws:SourceArn" = local.arns.media_bucket }
      }
    }]
  })
}

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

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
# A five-hop laundering chain. The slot's own reference list is exactly
# ["local.a"], so an arity gate alone never fires on it.
locals {
  a = local.b
  b = local.c
  c = local.d
  d = local.e
  e = aws_lambda_function.ingest.arn
}

HCL

bash tests/static_tiers.sh
