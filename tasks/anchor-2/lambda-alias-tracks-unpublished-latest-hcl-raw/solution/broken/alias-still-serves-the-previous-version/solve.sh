#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-still-serves-the-previous-version`, whose predicted_tier_caught is
# "0" on this arm.
#
# THE MISTAKE: the plausible, competent-looking answer. It makes exactly the
# change the ticket asks for -- `QUOTE_CURRENCY` becomes `USD` -- and touches
# nothing else. It validates, it plans, and it applies CLEANLY: `publish = true`
# cuts version 2 with the new configuration. The alias, still carrying the
# literal `function_version = "1"` an operator typed once, goes on naming
# version 1, whose immutable snapshot still says `EUR`.
#
# WHY THIS IS A REWARD-0.0 FIXTURE ON THIS ARM AND A REWARD-1.0 ONE ON awscdk:
# `terraform show -json` puts the alias's target straight into the graded
# artifact, so tier 0 can read it. Measured on terraform 1.15.8 +
# hashicorp/aws 6.58.0:
#   this shape           -> .planned_values...aws_lambda_alias.values
#                             .function_version == "1"
#   the reference shape  -> that key is ABSENT (known-after-apply, because the
#                           value now references the function's own attribute)
# The tier-0 assert `alias-is-no-longer-pinned-to-the-seeds-version` is written
# as a REFUSAL of the seed's value rather than a demand for a shape, so it fails
# here and passes for both accepted answers (derive it, or write the new number
# down). CloudFormation expresses the same edge as an `Fn::GetAtt` map in BOTH
# shapes, which is why that arm has nothing to read and is graded live instead.
#
# Expected verdict: reward 0.0, caught at tier 0.
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
  function_version = "1"
}
HCL

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this apply is EXPECTED to succeed and to leave the alias behind =="
  terraform init -input=false
  # FIXTURE SELF-PROOF (the discipline finding M5 introduced on the sibling
  # brownfield scenario): `--expect stale` alone cannot tell this catch from a
  # no-op, because workspace_seed.deploy has the harness put the euro-serving
  # alias in the account BEFORE this script starts -- `fail_stale` is true by
  # construction until something changes it. The discriminating fact is that
  # the apply must SUCCEED and the alias must still be stale afterwards.
  DEPLOY_LOG=/tmp/lambda-alias-broken-hcl-raw.log
  set +e
  terraform apply -input=false -auto-approve > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -ne 0 ]; then
    echo "FIXTURE PROOF FAILED: the apply exited $deploy_rc." >&2
    echo "This fixture exists to pin a change that APPLIES CLEANLY and is still" >&2
    echo "wrong. A failed apply also reaches live_check's 'fail_stale', so" >&2
    echo "accepting it would let a broken toolchain wear this catch's costume." >&2
    echo "Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== apply succeeded, as this fixture requires; now asking the account =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
