module "quote_service_packages" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket_prefix = "cdktn-bench-quote-service-"
  force_destroy = true
}

module "quote_service_package" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/object"
  version = "5.16.1"

  bucket         = module.quote_service_packages.s3_bucket_id
  key            = "quote-service.zip"
  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

module "quote_service" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-quote-service"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package = false

  s3_existing_package = {
    bucket = module.quote_service_packages.s3_bucket_id
    key    = module.quote_service_package.s3_object_id
  }

  publish = true

  environment_variables = {
    QUOTE_CURRENCY = "EUR"
  }
}

module "quote_service_live" {
  source  = "terraform-aws-modules/lambda/aws//modules/alias"
  version = "8.8.2"

  name             = "quote-service-live"
  function_name    = module.quote_service.lambda_function_name
  function_version = "1"
}
