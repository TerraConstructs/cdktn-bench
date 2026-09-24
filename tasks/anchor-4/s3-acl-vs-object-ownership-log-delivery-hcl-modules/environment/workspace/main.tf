module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "ObjectWriter"

  tags = {
    Name = "application-storage-access-logs"
  }
}

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [module.access_logs]

  bucket = module.access_logs.s3_bucket_id
  acl    = "log-delivery-write"
}

module "app_data" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  depends_on = [aws_s3_bucket_acl.access_logs]

  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  attach_public_policy = false

  logging = {
    target_bucket = module.access_logs.s3_bucket_id
    target_prefix = "app-data/"
  }

  tags = {
    Name = "application-storage-app-data"
  }
}
