#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf (verified against a real `terraform plan` run --
# generator/tests/fixtures/s3-lambda-log-retention/hcl_raw/main.tf is
# byte-identical to it) plus a placeholder Lambda deployment package, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# function.zip: the aws provider's aws_lambda_function resource requires a
# real local file at `filename` to compute source_code_hash/size, but
# v1's oracle is plan-only (never apply) so the file's actual byte content
# is never graded -- verified directly: `terraform plan` succeeds fully
# offline (--network none) against a plain placeholder file with no real
# zip structure at all. This arm's image has no `zip` binary (only
# `unzip`), so a real agent trial would need to reach the same conclusion
# (a real handler zip is not actually required for this v1, plan-only
# oracle) -- flagged as an open concern in this scenario's delivery notes.
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

# Standalone log group, named to match Lambda's own default log group
# (/aws/lambda/<function-name>) -- the aws provider has no native
# "attach a log group to this function" attribute at all, so a real
# hand-written HCL solution always takes this shape. Retention picked
# from the valid CloudWatch retention set nearest the instruction's
# "10 days" (7 or 14 -- see the spec's log-retention-not-a-valid-enum-value
# catch: retention_in_days = 10 is rejected by `terraform validate` itself).
resource "aws_cloudwatch_log_group" "handler" {
  name              = "/aws/lambda/${aws_lambda_function.handler.function_name}"
  retention_in_days = 14
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
