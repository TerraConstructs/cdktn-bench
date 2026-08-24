#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the two-notification-resources-for-one-bucket catch
# (THE PLAUSIBLE-WRONG SOLUTION): declares TWO separate
# `aws_s3_bucket_notification` resources, one per stakeholder requirement,
# both targeting the SAME bucket -- exactly the natural shape when two
# tickets are authored independently. `terraform plan` succeeds (no
# cross-resource uniqueness constraint exists at plan time); reward must
# be 0.0 from tier-0 alone (exactly-one-notification-resource-per-bucket-tf
# resolves 2 nodes, and `eq`'s own "0 or >1 resolved nodes FAILS outright"
# rule fails regardless of the two nodes' identical value).
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
resource "aws_s3_bucket" "media" {
  bucket = "cdktn-bench-media-ingest-media"
}

resource "aws_iam_role" "ingest" {
  name = "cdktn-bench-media-ingest-handler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name = "cdktn-bench-media-ingest-transcode"
  role          = aws_iam_role.ingest.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.media.arn
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

resource "aws_sns_topic_policy" "audit" {
  arn = aws_sns_topic.audit.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.audit.arn
      Condition = {
        ArnLike = { "aws:SourceArn" = aws_s3_bucket.media.arn }
      }
    }]
  })
}

# BUG: two separate authoritative notification resources for the SAME
# bucket -- the Product team's ticket and the Compliance team's ticket,
# each authored as its own resource. Both plan/apply green; each apply
# silently clobbers the other's half of S3's one notification document.
resource "aws_s3_bucket_notification" "upload" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}

resource "aws_s3_bucket_notification" "delete_audit" {
  bucket = aws_s3_bucket.media.id

  topic {
    topic_arn = aws_sns_topic.audit.arn
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
