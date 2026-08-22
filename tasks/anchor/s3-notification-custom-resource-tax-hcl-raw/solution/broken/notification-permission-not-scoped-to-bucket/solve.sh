#!/usr/bin/env bash
# Broken fixture for catch: notification-permission-not-scoped-to-bucket
# (graph-dependency, all arms; REUSED VERBATIM mechanism from
# s3-lambda-log-retention's own s3-lambda-invoke-permission-scoped catch).
# Reproduces exactly ONE mistake relative to solution/solve.sh:
# `aws_lambda_permission.allow_s3`'s `source_arn` is a hardcoded, unrelated
# ARN literal (not scoped to the bucket this configuration creates) --
# everything else (the notification's own target, the event type) stays
# exactly as the reference solution.
#
# Expected: reward 0.0. Caught at tier 1 (Rego's
# `lambda-permission-scoped-to-bucket-tf`, `references_bucket`): the
# permission's `source_arn` expression has only a `.constant_value`, no
# `.references` entry matching `^aws_s3_bucket\.`. Every tier-0 assert
# still passes.
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
  # MISTAKE: hardcoded, unrelated ARN literal -- not scoped to
  # aws_s3_bucket.claims, the bucket this configuration actually creates.
  source_arn = "arn:aws:s3:::some-totally-unrelated-bucket"
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
