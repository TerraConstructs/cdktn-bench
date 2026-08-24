#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop -- the same mechanism
# `lambda-permission-scoped-to-a-different-bucket` next to it already uses.
#
# ROUND-9 (2026-08-23). This is the SECOND spelling of the
# sns-topic-policy-not-scoped-to-bucket catch, and it exists because round
# 8's fix to that rule was over-broad: it accepted ANY `local.`/`var.`
# reference found anywhere in a topic policy document as evidence that the
# policy was scoped to the bucket. An adversarial verifier PROVED by
# execution that taking the sibling fixture next to this one and adding one
# ordinary edit -- hoisting the TOPIC's own ARN into a `locals` block and
# using it for the statement's `Resource` -- flipped it from reward 0.0 to
# reward 1.0, silently defeating a declared catch.
#
# The defect is identical to that sibling's: the policy grants
# s3.amazonaws.com sns:Publish with NO aws:SourceArn condition at all, so
# any bucket in any account can publish to the audit topic. The `local.`
# reference is a red herring that names the topic, not the bucket.
# `policy.rego`'s `bucket_denoting_indirections` now scopes the round-8
# leniency to symbols this configuration itself uses as the BUCKET ARN
# (i.e. ones sitting in an s3.amazonaws.com invoke permission's
# `source_arn` slot), so this shape is rejected again while the ordinary
# DRY hoist the reference solution itself uses is still accepted.
#
# Everything else is correct (one authoritative notification resource, both
# event types wired, Lambda half fully correct including its scoped
# permission). Tier-0 still passes; reward must be 0.0 from tier-1
# (sns-topic-policy-allows-s3-publish-tf) alone.
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
# An ordinary-looking DRY hoist -- of the TOPIC's ARN, which says nothing
# about which bucket may publish.
locals {
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
  source_arn    = aws_s3_bucket.media.arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# BUG: no Condition block at all -- grants s3.amazonaws.com sns:Publish
# unconditionally, never scoped to this scenario's bucket (or any bucket
# in particular). The `local.audit_topic_arn` below is the red herring:
# it is a reference, and it is unresolvable from the plan JSON, but it
# denotes the topic, not the bucket.
resource "aws_sns_topic_policy" "audit" {
  arn = aws_sns_topic.audit.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.audit_topic_arn
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
    topic_arn = aws_sns_topic.audit.arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
