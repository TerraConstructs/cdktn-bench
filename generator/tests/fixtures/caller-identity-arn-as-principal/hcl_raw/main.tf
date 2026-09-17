data "aws_caller_identity" "current" {}

# The deploying credentials are an STS session, not an identity IAM can name
# in a policy; this maps that session back to the role that issued it.
data "aws_iam_session_context" "deployer" {
  arn = data.aws_caller_identity.current.arn
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "release-artifact-store-"
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PipelineOnly"
      Effect    = "Allow"
      Principal = { AWS = data.aws_iam_session_context.deployer.issuer_arn }
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
      ]
      Resource = [
        aws_s3_bucket.artifacts.arn,
        "${aws_s3_bucket.artifacts.arn}/*",
      ]
    }]
  })
}
