#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- SAME-TYPE / WRONG-INSTANCE, topic half, written
# DIRECTLY. The clean round-12 FALSE PASS on the topic side: `arn =
# aws_sns_topic.decoy.arn` satisfies round 12's first acceptance clause
# outright (`direct_reference(refs, "aws_sns_topic.")` -- a TYPE test), so
# the corroboration clause that catches the laundered twin is never even
# reached. Executed against the round-12 policy: deny set EMPTY, reward 1.0,
# on an artifact whose audit topic has no resource policy at all.
#
# Needs no HCL parsing to catch: the plan's own `.references` list names the
# decoy. Closed on both TF-shaped arms by comparing the resolved INSTANCE
# against the one `aws_s3_bucket_notification.topic[*].topic_arn` resolves
# to.
#
# ISOLATION NOTE. Unlike most fixtures in this directory, this one does NOT
# reproduce the reference solution's `locals` map verbatim: the topic
# policy's `aws:SourceArn` condition is spelled DIRECTLY
# (`aws_s3_bucket.media.arn`) rather than through `local.arns.media_bucket`.
# That is deliberate and it is what makes the fixture prove what it claims.
# With the hoisted spelling, the defect below ALSO knocks the policy-
# document rule over (the same symbol feeds both), so the artifact denies
# twice and one cannot tell which rule is doing the work -- and under the
# round-12 oracle the ONLY deny it produced was the knock-on one, which is
# how this class of defect looked "caught" while the rule that grades it was
# silent. Spelled this way, the document rule is satisfied on its own and
# exactly ONE deny fires: the one this fixture is about.
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
  source_arn    = local.arns.media_bucket
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
  arn = aws_sns_topic.decoy.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.arns.audit_topic
      Condition = {
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.media.arn }
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
resource "aws_sns_topic" "decoy" {
  name = "cdktn-bench-media-ingest-decoy-topic"
}

HCL

bash tests/static_tiers.sh
