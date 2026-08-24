#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- THE RESIDUAL FOUR PREVIOUS ROUNDS CALLED
# IRREDUCIBLE. This is the two-symbol laundering shape that this spec, this
# policy and the design memo all recorded, in four operator-facing places,
# as "irreducible from `terraform show -json`" and as a standing one-sided
# CROSS-ARM STRICTNESS difference.
#
# The configuration reaches the bucket ARN through ONE symbol (the topic
# policy's condition) and launders the LAMBDA'S OWN ARN through a SECOND
# symbol into `source_arn`. Round 12's evidence was configuration-WIDE:
# `relevant_attributes` says "this configuration depends on some
# aws_s3_bucket's arn", which is TRUE here and says nothing about the slot
# being graded. Executed against the round-12 policy: deny set EMPTY,
# reward 1.0.
#
# It was never irreducible. It was irreducible FROM plan.json -- and once
# the agent's own main.tf is an input, `local.scope` resolves to
# `aws_lambda_function.ingest.arn` in one hop and the slot is denied with a
# message that quotes the referent. The four claims of irreducibility are
# retracted in place (this spec's own ROUND 13 block, the
# lambda-permission-scoped-to-bucket-tf assert, the rego_hints entry, and
# "oracle must tolerate/defend" point 8); this fixture is what keeps them
# retracted.
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
  source_arn    = local.scope
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
locals {
  # A SECOND symbol. The first (local.arns.media_bucket) still
  # genuinely holds the bucket ARN and is still used elsewhere.
  scope = aws_lambda_function.ingest.arn
}

HCL

bash tests/static_tiers.sh
