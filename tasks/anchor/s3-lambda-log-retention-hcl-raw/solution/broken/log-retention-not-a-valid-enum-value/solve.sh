#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the log-retention-not-a-valid-enum-value catch:
# `retention_in_days = 10`. Reward must be 0.0 from the toolchain step
# itself (`terraform validate`, part of plan_command) -- verified directly
# at authoring time against the pinned hashicorp/aws 6.58.0: `expected
# retention_in_days to be one of [0 1 3 5 7 14 30 60 90 120 150 180 365 400
# 545 731 1096 1827 2192 2557 2922 3288 3653], got 10`. No structural_assert
# or tier-1 policy is ever reached; plan.json is never even produced.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
resource "aws_s3_bucket" "upload" {
  bucket = "cdktn-bench-s3-lambda-log-retention-upload"
}

resource "aws_iam_role" "handler" {
  name = "cdktn-bench-s3-lambda-log-retention-handler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "handler" {
  function_name = "cdktn-bench-s3-lambda-log-retention-handler"
  role          = aws_iam_role.handler.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_cloudwatch_log_group" "handler" {
  name              = "/aws/lambda/${aws_lambda_function.handler.function_name}"
  retention_in_days = 10
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.upload.arn
}

resource "aws_s3_bucket_notification" "upload" {
  bucket = aws_s3_bucket.upload.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.handler.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
HCL

bash tests/static_tiers.sh
