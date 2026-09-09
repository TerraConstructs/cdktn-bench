resource "aws_iam_role" "quote_service" {
  name = "cdktn-bench-quote-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "quote_service_logs" {
  role       = aws_iam_role.quote_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_s3_bucket" "quote_service_packages" {
  bucket_prefix = "cdktn-bench-quote-service-"
  force_destroy = true
}

resource "aws_s3_object" "quote_service" {
  bucket = aws_s3_bucket.quote_service_packages.id
  key    = "quote-service.zip"

  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

resource "aws_lambda_function" "quote_service" {
  function_name = "cdktn-bench-quote-service"
  role          = aws_iam_role.quote_service.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  s3_bucket = aws_s3_bucket.quote_service_packages.id
  s3_key    = aws_s3_object.quote_service.key

  publish = true

  environment {
    variables = {
      QUOTE_CURRENCY = "EUR"
    }
  }
}

resource "aws_lambda_alias" "live" {
  name             = "quote-service-live"
  function_name    = aws_lambda_function.quote_service.function_name
  function_version = "1"
}
