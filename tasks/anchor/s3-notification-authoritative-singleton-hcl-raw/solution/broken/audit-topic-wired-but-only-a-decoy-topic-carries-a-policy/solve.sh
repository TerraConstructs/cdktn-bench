#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 15 (2026-08-24) -- THE EXTRA-`topic`-BLOCK LAUNDERING. This adds ONE
# block to the artifact `sns-topic-policy-attached-to-a-decoy-topic-directly`
# already covers, and that one block used to be enough to turn its reward 0.0
# into a reward 1.0.
#
# *** THE MECHANISM, executed. `notification_topic_instances` is a UNION over
# every `topic` block of every notification resource, and the acceptance test
# `references_this_topic` only asked whether a policy's `arn` names SOME
# MEMBER of that set. Wire both `aws_sns_topic.audit` and a decoy, attach the
# single `aws_sns_topic_policy` to the DECOY, and the membership test passes
# -- while `aws_sns_topic.audit`, the topic the ticket is actually about, has
# NO resource policy at all and S3 therefore cannot publish to it.
# `tier0_pass=1 tier1_status=PASS`, deny `[]`, REWARD 1.0. The gate
# `_has_topic_anchor` did not help: it is satisfied if ANY block resolves. ***
#
# WHAT CLOSES IT: policy.rego now grades PER WIRED TOPIC. For every instance
# in `notification_topic_instances` there must be an `aws_sns_topic_policy`
# attached to THAT instance, or an inline `policy` on THAT topic block --
# `some` replaced by `every`, which is the quantifier the old rules were
# missing. The per-block gate added beside it does the same for a `topic`
# block whose `topic_arn` cannot be resolved at all.
#
# WHY BOTH BLOCKS WIRE A REAL DELETE EVENT: so this fixture fails at its own
# defect and nowhere else. `s3:ObjectRemoved:*` on the audit block satisfies
# the tier-0 whitelist and the `audit-topic-events-cover-a-real-delete`
# rule, and the decoy block's `s3:ObjectRemoved:Delete` is inside the same
# whitelist -- so tier 0 passes cleanly and the ONLY thing wrong with this
# artifact is that the wired audit topic is unreachable.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  arns = {
    media_bucket = aws_s3_bucket.media.arn
    audit_topic  = aws_sns_topic.audit.arn
    decoy_topic  = aws_sns_topic.decoy.arn
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

resource "aws_sns_topic" "decoy" {
  name = "cdktn-bench-media-ingest-decoy-topic"
}

resource "aws_sns_topic_policy" "decoy" {
  arn = local.arns.decoy_topic
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.arns.decoy_topic
      Condition = {
        ArnLike = { "aws:SourceArn" = local.arns.media_bucket }
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
    topic_arn = local.arns.audit_topic
    events    = ["s3:ObjectRemoved:*"]
  }

  topic {
    topic_arn = local.arns.decoy_topic
    events    = ["s3:ObjectRemoved:Delete"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.decoy]
}
HCL

bash tests/static_tiers.sh
