#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-lambda-invoke-permission-scoped catch: the
# `aws_lambda_permission.allow_s3` resource grants principal
# s3.amazonaws.com with NO source_arn at all (account-wide, not scoped to
# this scenario's bucket) -- a classic real hand-written-HCL mistake (the
# compiler/provider schema never forces you to add one). Tier-0 still
# passes (bucket/function/log-group/notification/principal are all
# correct); reward must be 0.0 from tier-1 (policy.rego) alone.
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
  retention_in_days = 14
}

# Deliberately no source_arn -- grants ANY s3.amazonaws.com-principal'd
# caller, not just this scenario's bucket. The catch this fixture exists
# to violate.
resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "s3.amazonaws.com"
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
