module "reports" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-reports-archive"
  force_destroy = true

  tags = {
    Name = "reports-archive"
  }

  lifecycle_rule = [
    {
      id      = "expire-raw-logs"
      enabled = true

      filter = {
        prefix = "logs/"
      }

      expiration = {
        days = 30
      }
    },
  ]
}
