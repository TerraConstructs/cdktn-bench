#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NEW as of the 2026-08-21 second adversarial-review fix round
# (see specs/lambda-log-group-ownership-and-retention.yaml's own catch
# `retention-left-at-the-construct-default`): this scenario's headline
# value check, `log-group-retention-is-30-days`, previously had no fixture
# that isolated it non-vacuously -- every existing broken fixture that
# failed it did so only because it declared no log group at all (0
# resolved nodes), never because a real, present retention value was
# simply wrong.
#
# Reproduces that catch: the log group is correctly named (built by
# interpolating the function's own `function_name`, same shape as this
# scenario's own reference solution) and correctly left un-retained
# (`skip_destroy` simply omitted, its own default of `false`) -- every
# OTHER tier-0/tier-1 fact this scenario checks passes. The only thing
# missing is `retention_in_days` itself. Verified directly, 2026-08-21,
# against a real offline `terraform plan` (hashicorp/aws 6.58.0, this
# arm's own pin) before this fixture was written: omitting
# `retention_in_days` resolves to a PRESENT `retention_in_days: 0` in
# `.planned_values` (CloudWatch Logs' own "never expire" sentinel), not an
# absent key. Reward must be 0.0, caught at tier 0 by
# `log-group-retention-is-30-days` (`op: eq`, `expected: 30`,
# `resolved: [0]`).
#
# function.zip: same placeholder-package precedent as this scenario's own
# reference solution's solve.sh (see that file's own header comment) --
# `aws_lambda_function.filename` needs a real local file to compute
# source_code_hash/size, and this scenario's oracle is plan-only.
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

# Correctly named (governs the function) and correctly left un-retained
# (skip_destroy omitted, default false) -- but no retention_in_days, so it
# is left at the provider's own "never expire" default (0) rather than the
# 30 days this ticket asks for.
resource "aws_cloudwatch_log_group" "event_processor" {
  name = "/aws/lambda/${aws_lambda_function.event_processor.function_name}"
}
HCL

bash tests/static_tiers.sh
