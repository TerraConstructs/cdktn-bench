#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md 8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-17 FIXTURE -- a policy document whose STRUCTURE this resolver
# genuinely cannot read: `policy = jsonencode(var.topic_doc)`. The
# `jsonencode(...)` body re-parses (it is valid HCL) but comes back as the
# bare symbol `"${var.topic_doc}"`, which is not an object, and `var.` is
# not something the parsed `locals` can dereference.
#
# This is the FAIL-CLOSED half of the round-17 correction, and the reason
# the `is_object` guard exists: WITHOUT it the recovered string counted as
# a document, `_policy_document_unreadable` was false, the promised loud
# deny never fired, and the artifact was graded as "0 granting statements".
# That same missing guard scored a CORRECT `jsonencode(local.topic_doc)`
# solution 0.0 with a message the artifact refutes. This fixture pins the
# branch that is supposed to deny; the correct DRY spelling that must PASS
# is pinned by oracles/tests/test_hcl_traversal.py::
# test_a_policy_document_hoisted_into_a_local_is_read_not_refused.
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
variable "topic_doc" {
  type    = any
  default = null
}

resource "aws_sns_topic_policy" "audit" {
  arn    = local.arns.audit_topic
  policy = jsonencode(var.topic_doc)
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
HCL

bash tests/static_tiers.sh
