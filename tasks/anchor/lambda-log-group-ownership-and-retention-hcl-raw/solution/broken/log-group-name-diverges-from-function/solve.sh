#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-name-diverges-from-function`: the
# log group exists, matches the `/aws/lambda/...` naming pattern, has
# 30-day retention, and is not skip_destroy'd -- every tier-0 fact this
# scenario checks passes. But its name is a hardcoded literal
# (`/aws/lambda/processor`) that does not exactly match the function's own
# name (`event-processor`) -- a stale copy-paste from a differently-named
# function. Reward must be 0.0, caught ONLY at tier 1
# (log-group-governs-the-function-tf / oracles/rego/
# lambda-log-group-ownership-and-retention/policy.rego): the string
# equality check `lg.values.name == "/aws/lambda/" + fn.values.
# function_name` fails ("/aws/lambda/processor" != "/aws/lambda/event-
# processor"), even though every tier-0 assert this scenario declares
# passes for this exact fixture.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
resource "aws_iam_role" "event_processor" {
  name = "cdktn-bench-event-processor-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "event_processor" {
  function_name = "event-processor"
  role          = aws_iam_role.event_processor.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

# Deliberately mismatched: a hardcoded literal, not built from
# aws_lambda_function.event_processor.function_name -- passes the tier-0
# `^/aws/lambda/` pattern check, fails the tier-1 exact-match check.
resource "aws_cloudwatch_log_group" "event_processor" {
  name              = "/aws/lambda/processor"
  retention_in_days = 30
}
HCL

bash tests/static_tiers.sh
