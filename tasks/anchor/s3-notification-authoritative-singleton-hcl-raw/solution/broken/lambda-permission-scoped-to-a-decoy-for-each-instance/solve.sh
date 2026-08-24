#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 15 (2026-08-24) -- SAME-TYPE / WRONG-INSTANCE reached through a
# `for_each` INSTANCE KEY. This is the fixture for the round-15 blocker, and
# it is a different defect from every `...-decoy-bucket-...` fixture beside
# it: those name two SEPARATE resource blocks (`aws_s3_bucket.media` vs
# `aws_s3_bucket.decoy`), which round 13/14 already discriminated. This one
# names two INSTANCES OF ONE BLOCK.
#
# *** WHAT IT CAUGHT, executed. `hcl.instance_of` used to be
# `array.slice(segs, 0, 2)` -- the first two segments of the referent path,
# full stop. The tokenizer parses the `["key"]` form deliberately, so
# `aws_s3_bucket.b["cdktn-bench-media-ingest-decoy"].arn` RESOLVED cleanly
# and then collapsed to `["aws_s3_bucket","b"]` -- byte-identical to what the
# media instance yields. Every consumer accepted: the source_arn slot, the
# topic-policy condition, both anchor routes. `tier0_pass=1
# tier1_status=PASS`, deny `[]`, REWARD 1.0, on an artifact where S3 can
# never invoke the Lambda. The byte-identical CORRECT variant (permission on
# `b["...-media"]`) also scored 1.0, i.e. the oracle could not tell the two
# apart at all. ***
#
# WHY THE COLLAPSE WAS SILENT RATHER THAN LOUD, which is the part the
# library's own residual list got wrong: the NUMERIC spelling
# (`aws_s3_bucket.b[0].arn`) does not tokenize, so it has always been
# UNRESOLVABLE -> DENY. Three operator-facing texts generalised that to the
# whole `count`/`for_each` family and called it "loud, not silent". For the
# quoted-key spelling it was neither. Those texts are corrected at
# specs/s3-notification-authoritative-singleton.yaml (RESIDUALS),
# oracles/rego/lib/hcl_traversal.rego (header) and
# docs/design/conftest-hcl-traversal-spike.md sect 0.0.
#
# THE PLAN AGREES THESE ARE TWO RESOURCES: `terraform show -json` plans
# `aws_s3_bucket.b["cdktn-bench-media-ingest-media"]` and
# `aws_s3_bucket.b["cdktn-bench-media-ingest-decoy"]` as separate instances,
# each with its own `.index`. Nothing about this artifact is ambiguous --
# the oracle simply was not reading the key.
#
# THE POSITIVE TWIN is not a file in this directory (there is only one
# positive slot per task, `solution/solve.sh`). It is asserted by execution
# in oracles/tests/test_hcl_traversal.py::test_for_each_instance_key_
# discriminates -- byte-identical artifact with the permission on
# `b["...-media"]`, which must deny NOTHING. A fix that closed this fixture
# by refusing every `for_each` referent outright would pass this file and
# fail that one.
#
# ISOLATION NOTE, same convention as the `...-decoy-bucket-directly` fixture
# beside it: the topic policy's `aws:SourceArn` condition names the MEDIA
# instance, so the policy-document rule is satisfied on its own and the
# denies that fire are about the invoke permission alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  bucket_names = [
    "cdktn-bench-media-ingest-media",
    "cdktn-bench-media-ingest-decoy",
  ]
}

resource "aws_s3_bucket" "b" {
  for_each = toset(local.bucket_names)
  bucket   = each.value
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
  source_arn    = aws_s3_bucket.b["cdktn-bench-media-ingest-decoy"].arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

resource "aws_sns_topic_policy" "audit" {
  arn = aws_sns_topic.audit.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.audit.arn
      Condition = {
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.b["cdktn-bench-media-ingest-media"].arn }
      }
    }]
  })
}

resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.b["cdktn-bench-media-ingest-media"].id

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
