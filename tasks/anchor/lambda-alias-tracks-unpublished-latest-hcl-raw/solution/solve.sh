#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# BROWNFIELD: this is the SEED with exactly two lines changed. Everything else
# -- the role, the packages bucket, the object, the function's packaging -- is
# reproduced byte-for-byte from workspace_seed.entry_file.hcl_raw, because a
# reference solution for a change request must be the existing configuration
# plus the change, not a rewrite that happens to satisfy the asserts.
#
# THE TWO CHANGES:
#   1. QUOTE_CURRENCY  "EUR" -> "USD"          -- the ticket.
#   2. aws_lambda_alias.live.function_version
#        "1" -> aws_lambda_function.quote_service.version
#      -- the alias's target now DERIVES from the function instead of being
#      written down, so the version `publish = true` cuts on this apply is the
#      version the alias names. Without (2) the apply still succeeds, the
#      function's own configuration is USD, and every caller going through the
#      alias keeps getting the euro snapshot frozen into version 1.
#
# (2) is not the only accepted answer -- see the spec's `oracle.intent`. An
# agent that reads the account and writes the new number down explicitly also
# satisfies both tiers. This one is the maintainable shape and is what the
# oracle's own negative fixture is contrasted against.
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

resource "aws_lambda_alias" "live" {
  name             = "quote-service-live"
  function_name    = aws_lambda_function.quote_service.function_name
  function_version = aws_lambda_function.quote_service.version
}
HCL

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  # The gating live oracle, invoked in its fixture shape. Exits 1 if the
  # account contradicts "the alias serves USD", 2 if the account could not be
  # read at all (which is never scored as a solution failure).
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
