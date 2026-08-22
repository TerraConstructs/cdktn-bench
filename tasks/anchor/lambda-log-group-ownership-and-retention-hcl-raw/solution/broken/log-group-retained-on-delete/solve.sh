#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-retained-on-delete`: the log group
# is otherwise identical to the reference solution (right name, right
# 30-day retention) but adds `skip_destroy = true`. Reward must be 0.0 via
# tier-0's `log-group-not-retained-on-stack-delete-tf` (`skip_destroy`
# resolves to `true`, not `false`/absent).
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

resource "aws_cloudwatch_log_group" "event_processor" {
  name              = "/aws/lambda/${aws_lambda_function.event_processor.function_name}"
  retention_in_days = 30
  skip_destroy      = true
}
HCL

bash tests/static_tiers.sh
