#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-removed-instead-of-repointed`, predicted_tier_caught "0" on every arm.
#
# THE MISTAKE: make the symptom go away by removing the thing that has it. The
# environment variable becomes `USD` and the alias is deleted outright, so the
# new configuration IS reachable -- at the unqualified function ARN. It is not
# the ticket ("every caller reaches this function through its alias") and it
# breaks every one of those callers the moment it applies.
#
# Worth pinning as its own fixture rather than trusting the main catch to cover
# it: deleting the alias ALSO makes
# `alias-is-no-longer-pinned-to-the-seeds-version` pass -- that assert uses
# `not_regex`, which is true over zero resolved nodes. Without
# `the-alias-still-exists` (op `eq`, which pins the COUNT as well as the value)
# this workspace would score 1.0 at tier 0 while having deleted the interface
# every caller uses. That is exactly the vacuity shape this repo keeps finding,
# and this fixture is what keeps proving it is closed.
#
# Expected verdict: reward 0.0, caught at tier 0 by `the-alias-still-exists`.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_iam_role" "quote_service" {
  name = "cdktn-bench-quote-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "quote_service_logs" {
  role       = aws_iam_role.quote_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_s3_bucket" "quote_service_packages" {
  bucket_prefix = "cdktn-bench-quote-service-"
  force_destroy = true
}

resource "aws_s3_object" "quote_service" {
  bucket = aws_s3_bucket.quote_service_packages.id
  key    = "quote-service.zip"

  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

resource "aws_lambda_function" "quote_service" {
  function_name = "cdktn-bench-quote-service"
  role          = aws_iam_role.quote_service.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  s3_bucket = aws_s3_bucket.quote_service_packages.id
  s3_key    = aws_s3_object.quote_service.key

  publish = true

  environment {
    variables = {
      QUOTE_CURRENCY = "USD"
    }
  }
}
HCL

exec bash tests/static_tiers.sh
