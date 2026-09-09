resource "aws_s3_bucket" "app_data" {
  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  tags = {
    Name = "application-storage-app-data"
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  tags = {
    Name = "application-storage-access-logs"
  }
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [aws_s3_bucket_ownership_controls.access_logs]

  bucket = aws_s3_bucket.access_logs.id
  acl    = "log-delivery-write"
}

resource "aws_s3_bucket_logging" "app_data" {
  depends_on = [aws_s3_bucket_acl.access_logs]

  bucket = aws_s3_bucket.app_data.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "app-data/"
}
