#!/usr/bin/env bash
# Broken fixture for catch: notification-targets-the-wrong-function
# (graph-dependency, all arms). Reproduces exactly ONE mistake relative to
# solution/solve.sh: `aws_s3_bucket_notification`'s `lambda_function_arn`
# is a hardcoded, unrelated ARN literal instead of a reference to
# `aws_lambda_function.processor.arn` -- everything else (the permission,
# its scoping, the event type) stays exactly as the reference solution.
#
# Expected: reward 0.0. Caught at tier 1 (Rego's
# `notification-targets-created-function-tf`, mirrored in
# oracles/rego/s3-notification-custom-resource-tax/policy.rego's
# `target_references_created_function`): the notification's
# `lambda_function[0].lambda_function_arn` expression has only a
# `.constant_value`, no `.references` entry matching
# `^aws_lambda_function\.`. Every tier-0 assert still passes.
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
    # MISTAKE: hardcoded, unrelated ARN literal -- not a reference to
    # aws_lambda_function.processor, the function this configuration
    # actually creates.
    lambda_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:some-other-function"
    events               = ["s3:ObjectCreated:Put"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
HCL

bash tests/static_tiers.sh
