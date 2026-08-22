#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# Idiomatic, no escape hatch needed: the ordinary aws_s3_bucket_notification
# resource has zero extra functions/roles by construction -- this arm's own
# platform-constraint compliance is free (see this scenario's own
# arms.terraconstructs.reason / header comment for the contrast with
# awscdk, which must reach for an L1 escape hatch).
#
# function.zip: same placeholder-package convention as
# s3-lambda-log-retention-hcl-raw's own reference solution -- the aws
# provider's aws_lambda_function resource requires a real local file at
# `filename` to compute source_code_hash/size, but v1's oracle is
# plan-only (never apply), so the file's actual byte content is never
# graded (verified directly: `terraform plan` succeeds fully offline
# against a plain placeholder file with no real zip structure at all).
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
resource "aws_s3_bucket" "claims" {
  bucket = "cdktn-bench-s3-notification-custom-resource-tax-claims"
}

resource "aws_iam_role" "processor" {
  name = "cdktn-bench-s3-notification-custom-resource-tax-processor-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "processor" {
  function_name = "cdktn-bench-s3-notification-custom-resource-tax-processor"
  role          = aws_iam_role.processor.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowClaimsBucketInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.claims.arn
}

resource "aws_s3_bucket_notification" "claims" {
  bucket = aws_s3_bucket.claims.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
HCL

bash tests/static_tiers.sh
