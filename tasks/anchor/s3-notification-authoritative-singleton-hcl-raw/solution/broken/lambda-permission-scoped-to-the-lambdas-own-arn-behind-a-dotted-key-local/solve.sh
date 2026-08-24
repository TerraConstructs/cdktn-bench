#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- THE eval_conflict_error REGRESSION FIXTURE.
# Ship this with the code; it is the artifact the spike memo's §5.9
# correction is about.
#
# THE DEFECT IT GUARDS. The spike prototype flattened the `locals` table by
# DOT-JOINING each walk path into a string key
# (`concat(".", array.concat(["local"], path))`). HCL map keys are
# arbitrary strings, so a key may itself contain a dot, and then two
# DIFFERENT paths join to the SAME key:
#
#     ["t", "a.b"]     -> "local.t.a.b"
#     ["t", "a", "b"]  -> "local.t.a.b"      <-- same key, different value
#
# A Rego object rule binding one key to two different values raises
# `eval_conflict_error`, which is a RUNTIME ERROR: OPA aborts the whole
# query, writes NOTHING to stdout, and no `default` clause anywhere
# downstream can intercept it, because the evaluation that would have
# reached the default never completes. The harness gate then piped that
# empty stdout into `jq -e 'length == 0'`, which exits 4, and recorded
# tier1_status=FAIL -- reward 0.0 with no deny message at all. On a CORRECT
# solution carrying the same dotted key, that is a false FAIL; on THIS
# artifact, which is genuinely broken, it is a real defect going UNGRADED
# rather than denied.
#
# WHAT THIS FIXTURE ASSERTS. That the dotted key is a non-event: the
# round-13 library keys its locals table by the path ARRAY (a SET of
# [path, value] pairs -- a set cannot conflict on any input), so this
# artifact is DENIED, loudly and for its real defect (`source_arn` resolves
# to `aws_lambda_function.ingest.arn`), not crashed.
#
# The positive half of the same regression -- the byte-identical dotted-key
# shape on a fully CORRECT solution, which must score 1.0 -- cannot live
# under broken/ (the falsifiability gate has exactly one positive slot, the
# reference solution). It is covered by
# oracles/tests/test_hcl_traversal.py::test_dotted_key_collision_family,
# which runs ONE OPA PROCESS PER SHAPE and checks the exit code -- the only
# probe methodology that can see a runtime error at all, since a
# single-query assertion is inside the blast radius of the crash it is
# meant to detect.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # A `locals` map carrying a key that CONTAINS A DOT, alongside the
  # equivalent nested path, with a DIFFERENT value on each. Kept here
  # deliberately: this is the shape that made the spike prototype raise
  # `eval_conflict_error` and abort evaluation entirely.
  t = {
    "a.b" = aws_s3_bucket.media.arn
    a     = { b = aws_sns_topic.audit.arn }
  }

  # media_bucket is referenced twice below (the invoke permission and the
  # topic policy's condition); audit_topic three times (the topic policy's
  # own `arn`, that policy's `Resource`, and the notification's
  # `topic_arn`). One map, the ordinary DRY spelling.
  arns = {
    media_bucket = aws_lambda_function.ingest.arn
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
        ArnLike = { "aws:SourceArn" = local.arns.media_bucket }
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
# An ordinary, CORRECT IAM read grant on the real bucket. It is what made
# the round-12 `relevant_attributes` positive test pass while the invoke
# permission above was scoped to the Lambda's own ARN.
resource "aws_iam_role_policy" "ingest_read" {
  name = "cdktn-bench-media-ingest-read"
  role = aws_iam_role.ingest.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:GetObject"
      Resource = "${aws_s3_bucket.media.arn}/*"
    }]
  })
}

HCL

bash tests/static_tiers.sh
