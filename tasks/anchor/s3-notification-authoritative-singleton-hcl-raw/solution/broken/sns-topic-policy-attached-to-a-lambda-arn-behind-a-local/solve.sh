#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-12 ARM-PARITY FIX (2026-08-23), the ATTACHMENT-slot half of the
# finding the sibling fixture
# `lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local` covers
# for the bucket slot. An adversarial verifier PROVED by execution that
# `arn = local.ingest_fn_arn`, with that local holding
# `aws_lambda_function.ingest.arn`, scored reward 1.0 on hcl_raw -- i.e.
# the audit topic ends up with NO resource policy at all and S3 silently
# drops every publish -- while the awscdk twin (`topics: [auditTopicArn]`
# with `const auditTopicArn = fn.functionArn`) scored 0.0, because a
# synthesized template still carries the Fn::GetAtt and the CFN-side rule
# joins on the referenced logical id's Type.
#
# CLOSED at round 12 by CORROBORATION (`policy.rego`'s
# `topic_target_indirections`): an unresolvable symbol is accepted in the
# `aws_sns_topic_policy.arn` slot only if this same configuration also uses
# THAT SAME SYMBOL in a slot that WIRES a topic -- the notification's
# `topic[*].topic_arn` or a subscription's `topic_arn`, neither of which
# the policy resource writes itself, and at least one of which every
# solution that wires the audit topic has (this scenario's own tier-0
# `object-removed-notification-targets-a-topic` assert requires it).
# `local.ingest_fn_arn` appears in no such slot; `local.audit_topic_arn`,
# which the reference solution uses here, does.
#
# `relevant_attributes` alone cannot decide this one, which is why the
# corroboration clause exists: this artifact still wires the topic from the
# notification, so `aws_sns_topic.audit.arn` is a genuine dependency of the
# plan no matter what the policy is attached to.
#
# Everything else here is the reference solution verbatim (in the flat
# two-locals spelling), so the invoke permission, the policy document's
# aws:SourceArn scoping and both notification targets are all CORRECT and
# must pass their own rules: this fixture must fail at the attachment rule
# and nowhere else. Tier-0 passes; reward must be 0.0 from tier-1 alone.
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

  # Referenced twice below -- the topic policy's `Resource` and the
  # notification's `topic_arn`.
  audit_topic_arn = aws_sns_topic.audit.arn

  # BUG: the topic policy's `arn` is attached to THIS hoist, which holds
  # the Lambda's ARN rather than the audit topic's. The topic that actually
  # receives the delete notifications is left with no resource policy.
  ingest_fn_arn = aws_lambda_function.ingest.arn
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
  arn = local.ingest_fn_arn
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
