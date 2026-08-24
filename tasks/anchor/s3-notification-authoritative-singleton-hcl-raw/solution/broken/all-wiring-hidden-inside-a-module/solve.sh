#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 15 (2026-08-24) -- THE TIER-1 POLICY MUST NOT FAIL OPEN WHEN THE
# CONFIGURATION IT READS IS NOT WHERE IT LOOKS.
#
# *** THE DEFECT, executed. `configured_resources` was a BARE reference,
# `input.configuration.root_module.resources` -- nine lines above
# `planned_resources`, whose own comment already said why that is unsafe. An
# absent key makes the reference UNDEFINED, which makes every rule downstream
# of it undefined, and an undefined `deny` rule DOES NOT DENY. Measured on
# this scenario's own reference-solution oracle input: deleting
# `.configuration.root_module.resources` -> deny length 0; setting it to a
# string -> deny length 0; deleting `.configuration` outright -> deny
# length 0. Fail-OPEN, i.e. the whole tier-1 oracle silently passes.
#
# That is reachable from an ordinary agent artifact, which is why this is a
# fixture and not just a comment: a `module` block puts every resource under
# `.configuration.root_module.module_calls` /
# `.planned_values.root_module.child_modules` and leaves
# `root_module.resources` ABSENT. This exact artifact -- all wiring in
# `./modules/wiring`, `source_arn` on a DECOY bucket -- returned
# `tier1_status=PASS`, deny `[]`. Its reward was 0.0 only because tier 0
# errored, and "already denied at tier 0" is precisely the mitigation this
# scenario RETRACTED as unsound (docs/design/conftest-hcl-traversal-spike.md
# sect 5.3). A fixture that leans on tier 0 proves nothing about tier 1, so
# the assertion this file makes is the tier-1 one. ***
#
# WHAT CLOSES IT: `configured_resources` is `object.get(...)` with an
# `is_array` guard (the guard is load-bearing -- a key present with a
# non-list value has `count() > 0` and sailed through the default alone),
# plus two fail-closed denies: modules are refused BY NAME, the way the
# symbol resolver already refuses `module.x.out`, and an empty configuration
# list against a non-empty plan is refused too.
#
# THE GRADED CLAIM here is tier-1: `deny` must be non-empty and name the
# module. tier 0 also fails on this artifact (it reads `.planned_values.
# root_module.resources`, which is likewise absent) -- that is expected and
# is NOT what this fixture is about.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

mkdir -p modules/wiring

cat > main.tf <<'HCL'
module "wiring" {
  source = "./modules/wiring"
}
HCL

cat > modules/wiring/main.tf <<'HCL'
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
  filename      = "${path.module}/../../function.zip"
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
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.media.arn }
      }
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
