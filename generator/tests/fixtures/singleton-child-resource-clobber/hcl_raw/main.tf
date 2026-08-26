resource "aws_s3_bucket" "reports" {
  bucket        = "cdktn-bench-reports-archive"
  force_destroy = true

  tags = {
    Name = "reports-archive"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "expire-raw-logs"
    status = "Enabled"

    filter {
      prefix = "logs/"
    }

    expiration {
      days = 30
    }
  }

  rule {
    id     = "archive-exports"
    status = "Enabled"

    filter {
      prefix = "exports/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }
}
