#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf plus a placeholder Lambda deployment package, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# function.zip: same established precedent as tasks/anchor/
# s3-lambda-log-retention-hcl-raw/solution/solve.sh's own header comment --
# `aws_lambda_function.filename` needs a real local file to compute
# source_code_hash/size, but this scenario's oracle is plan-only (never
# apply), and `terraform plan` succeeds fully offline against a plain
# placeholder file with no real zip structure at all (verified directly).
# This arm's own mirror does not carry `hashicorp/archive` (unlike
# terraconstructs' -- see specs/lambda-log-group-ownership-and-
# retention.yaml's header comment for why this spec does not add it, a
# shared, non-scenario-owned bootstrap file this task must not touch), so a
# plain placeholder file -- not `data "archive_file"` -- is this arm's own
# path, matching the established precedent above.
#
# aws_cloudwatch_log_group.name is built by interpolating
# aws_lambda_function.event_processor.function_name -- verified directly at
# this spec's own authoring time that this stays fully plan-time-known
# (function_name is Required in the provider's own schema, never
# Optional+computed) -- see the spec's header comment, deviation 2.
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

# Named to match the function's own name EXACTLY -- this is the only
# way AWS Lambda's own /aws/lambda/<function-name> log destination is
# actually governed by this resource (see this scenario's own catch 4,
# log-group-name-diverges-from-function). 30-day retention, no
# skip_destroy (left at its own default of false -- this resource is
# destroyed with the rest of the stack, same as every other resource
# here, with no protection left in place).
resource "aws_cloudwatch_log_group" "event_processor" {
  name              = "/aws/lambda/${aws_lambda_function.event_processor.function_name}"
  retention_in_days = 30
}
HCL

bash tests/static_tiers.sh
