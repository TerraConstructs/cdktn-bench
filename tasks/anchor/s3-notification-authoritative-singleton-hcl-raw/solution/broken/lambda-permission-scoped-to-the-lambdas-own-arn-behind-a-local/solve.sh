#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-12 ARM-PARITY FIX (2026-08-23). This is the artifact an adversarial
# verifier used to PROVE that rounds 8-11 accepted a WRONG-TYPE ARN in the
# `source_arn` slot whenever it was laundered through a local: taking this
# scenario's own hcl_raw reference solution and changing ONE token in its
# own locals block -- `media_bucket_arn = aws_lambda_function.ingest.arn`
# instead of `= aws_s3_bucket.media.arn` -- scored reward 1.0 on hcl_raw
# (deny set EMPTY) while the byte-equivalent awscdk twin
# (`const mediaBucketArn = fn.functionArn; sourceArn: mediaBucketArn`,
# shipped alongside this file as the awscdk fixture of the same name)
# scored 0.0. Round 11's value test only ever rejected laundered LITERALS,
# and its provenance test only knew about TOPIC-ARN slots, so any other
# resource's `.arn` sailed through.
#
# CLOSED at round 12 by making the acceptance POSITIVE instead of residual:
# `policy.rego`'s `config_reaches_arn_of` reads the plan's own top-level
# `relevant_attributes` list -- which terraform computes AFTER expression
# evaluation, and which therefore resolves the `locals` hop that
# `.configuration`'s reference lists dead-end on. Dumped side by side: the
# reference solution lists `aws_s3_bucket.media ["arn"]`; THIS artifact
# lists `aws_s3_bucket.media ["id"]` (from the notification's `bucket`
# argument) and no bucket `arn` entry at all, so there is no bucket ARN in
# this configuration for any indirection to be carrying.
#
# TWO denies fire here, not one, and both are TRUE of this artifact
# (RULING 3): the same `local.media_bucket_arn` also feeds the topic
# policy's `aws:SourceArn` condition, so that condition names the Lambda
# too and the topic policy really is unscoped. That is a consequence of the
# defect, not oracle over-reach -- and it is why this fixture cannot be
# written in an "isolated" form: an artifact that reaches the bucket ARN
# through a SECOND symbol and launders the Lambda's ARN through this one
# passes the bucket slot, and is the residual policy.rego's ROUND-12 block
# records rather than claims to have closed.
#
# Everything else here is the reference solution verbatim (in the flat
# two-locals spelling, which the round-12 reference no longer uses).
# Tier-0 passes; reward must be 0.0 from tier-1 alone.
#
# ROUND-13 CORRECTION (2026-08-23). The header above describes the ROUND-12
# mechanism, and that mechanism no longer exists. `config_reaches_arn_of`,
# `relevant_attributes`-based positive evidence, `slot_is_plan_time_unknown`,
# `bucket_denoting_indirections`, `topic_target_indirections` and
# `deepest_refs` were all DELETED from
# oracles/rego/s3-notification-authoritative-singleton/policy.rego. The
# hcl_raw arm now parses the agent's own `.tf` with `hcl2json` and merges it
# into the oracle input (`oracle.hcl_traversal`, specs/SCHEMA.md sect 4.6),
# so a `local.` symbol is RESOLVED to the resource attribute it names rather
# than reasoned about circumstantially. THIS FIXTURE STILL SCORES 0.0 and
# still isolates at tier 1 -- what changed is the reason quoted in the deny
# message, which now states the referent. Read policy.rego's ROUND 13 block
# for what replaced the machinery this header names.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # BUG: the hoist reaches the LAMBDA's own ARN, not the bucket's. The
  # invoke permission below is therefore scoped to the function it is
  # granting access to -- which no S3 event ever matches -- and nothing in
  # this configuration ties the grant to the bucket at all.
  media_bucket_arn = aws_lambda_function.ingest.arn

  # Referenced three times below -- the topic policy's own `arn`, that
  # policy's `Resource`, and the notification's `topic_arn`.
  audit_topic_arn = aws_sns_topic.audit.arn
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
  source_arn    = local.media_bucket_arn
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

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
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
