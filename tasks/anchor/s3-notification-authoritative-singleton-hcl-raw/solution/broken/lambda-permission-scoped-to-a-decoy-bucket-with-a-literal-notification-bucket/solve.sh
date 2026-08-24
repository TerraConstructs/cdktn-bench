#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 14 (2026-08-24) -- THE VERIFIER'S OWN BLOCKER ARTIFACT, byte for
# byte in its essentials. It scored REWARD 1.0 under round 13.
#
# The defect is the same one
# `lambda-permission-scoped-to-a-decoy-bucket-directly` carries -- an
# invoke permission scoped to a bucket the notification does not wire, so
# S3 can never invoke the function -- but with ONE extra, entirely
# ORDINARY change: the notification's own `bucket` argument is written as
# the bucket NAME, which is what that argument actually takes:
#
#     bucket = "cdktn-bench-media-ingest-media"
#
# That spelling carries ZERO references, so `hcl.slot` returned
# `unresolvable`, the instance-join anchor set was EMPTY, and round 13's
# `slot_names_arn_of` second clause (`count(anchors) != 1`) accepted the
# decoy's ARN on resource TYPE alone. Executed in the real hcl_raw image
# under `--network none`: `tier0_pass=1 tier1_status=PASS`, deny `[]`,
# reward.txt `1.0` -- with only a `not_verifiable` note, which the
# generated script itself says "does NOT deny the plan and does NOT affect
# tier1_status/reward".
#
# Round 14 deletes that clause. The anchor is now established POSITIVELY
# from the plan's own values -- the notification's planned `bucket` string
# is the planned `bucket` name of exactly one `aws_s3_bucket` in this
# configuration -- so this artifact's anchor resolves to
# `aws_s3_bucket.media` and the decoy's ARN is denied by NAME.
#
# WHY THE LITERAL SPELLING IS NOT ITSELF THE DEFECT, and why this fixture
# has a positive twin: a CORRECT solution written with the same literal
# `bucket` argument scores 1.0 (proved by execution alongside this
# fixture). If it did not, round 14 would have traded a silent pass for a
# false fail.
#
# ISOLATION. The topic policy's `aws:SourceArn` condition is spelled
# DIRECTLY (`aws_s3_bucket.media.arn`), not through the hoisted symbol, so
# the document rule is satisfied on its own and exactly ONE deny fires:
# the one this fixture is about.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
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
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.media.arn }
      }
    }]
  })
}

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
resource "aws_s3_bucket_notification" "media" {
  bucket = "cdktn-bench-media-ingest-media"

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
