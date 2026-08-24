#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-11 ARM-PARITY FIX (2026-08-23). This is the artifact an adversarial
# verifier used to PROVE that the round-7 defect
# (`lambda-permission-scoped-to-a-different-bucket`: an invoke permission
# scoped to a hardcoded ARN for an unrelated bucket) was still live at
# REWARD level on hcl_raw -- 1.0 here versus 0.0 on the awscdk twin of the
# same name -- because rounds 8-10 accepted ANY `^(local|var)\.` reference
# in the `source_arn` slot without asking what it held. Laundering the
# literal through the reference solution's own `locals` block was all it
# took.
#
# CLOSED at round 11 by reading the plan's OWN RESOLVED VALUE for the slot
# (`policy.rego`'s `arn_slot_indirection_is_unresolved`): a `local.`/`var.`
# reference is accepted in an ARN slot only when the plan cannot resolve it
# (`planned_values...values.source_arn` absent/null -- what a hoist of a
# provider-computed `.arn` always produces, including this scenario's own
# reference solution). A `local.` that the plan resolves to a CONSTANT
# STRING, as here, is exactly the inline literal spelled one hop away, and
# is now rejected exactly as the inline literal always was. The round-11
# verifier's own `jq` dump of the two plans is the evidence: this artifact
# resolves `values.source_arn` to
# "arn:aws:s3:::some-totally-unrelated-bucket", the reference solution
# resolves it to null.
#
# Everything else here is the reference solution verbatim. Tier-0 passes;
# reward must be 0.0 from tier-1 alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # BUG: a hardcoded ARN for a bucket this configuration does not create,
  # hoisted into a local so it stops LOOKING like a literal. The plan
  # resolves it to that constant string all the same.
  media_bucket_arn = "arn:aws:s3:::some-totally-unrelated-bucket"

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
  # BUG: reaches the laundered literal above. Nothing here ties the grant
  # to the bucket this configuration creates.
  source_arn    = local.media_bucket_arn
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
