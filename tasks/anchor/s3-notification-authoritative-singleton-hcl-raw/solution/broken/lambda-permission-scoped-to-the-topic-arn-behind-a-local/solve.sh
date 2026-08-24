#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 ARM-PARITY FIX (2026-08-23). This is the artifact an adversarial
# verifier used to PROVE that round 8/9's `local.`/`var.` tolerance in an
# ARN slot was a live arm-parity break on THIS scenario, not the
# "strictly more work than writing the literal inline" residual those
# rounds described. It is this scenario's own hcl_raw reference solution
# with ONE token changed -- `source_arn = local.audit_topic_arn` instead of
# `local.media_bucket_arn` -- and both symbols already exist in the
# reference's `locals` block (the topic ARN is referenced three times), so
# the mistake costs an author nothing. It scored reward 1.0 on hcl_raw,
# while the byte-for-byte equivalent awscdk decision (`const auditTopicArn
# = auditTopic.topicArn; sourceArn: auditTopicArn`, this fixture's twin of
# the same name on that arm) scored 0.0, because a TS const vanishes at
# synth time and the template still carries the `Ref` to the topic.
#
# CLOSED at round 10 by narrowing the tolerance by PROVENANCE
# (`policy.rego`'s `slot_provenance_conflict`): an unresolvable symbol
# still stands in for an ARN, but not one this configuration also uses in
# an `aws_sns_topic_policy.arn` slot -- a topic ARN does not scope an
# invoke grant to the bucket whichever of its two usages the author meant.
# A correct DRY hoist uses one symbol for one ARN and never conflicts,
# which is why the reference solution (hoisting BOTH ARNs) still scores
# 1.0 on every run.
#
# Everything else here is the reference solution verbatim. Tier-0 passes;
# reward must be 0.0 from tier-1 (lambda-permission-scoped-to-bucket-tf)
# alone -- this fixture is the isolated falsification of that clause.
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
  # Referenced twice below -- the invoke permission and the topic policy.
  media_bucket_arn = aws_s3_bucket.media.arn

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
  # BUG: `local.audit_topic_arn`, one token off the correct
  # `local.media_bucket_arn` -- the grant is scoped to the AUDIT TOPIC's
  # ARN, which no S3 invocation ever matches, so nothing ties it to the
  # bucket at all.
  source_arn    = local.audit_topic_arn
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
