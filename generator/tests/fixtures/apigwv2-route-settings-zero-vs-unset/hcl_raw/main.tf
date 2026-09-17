# Oracle-CORRECT reference fixture for `make check-paths`
# (generator/check_reference_paths.py): the same shape as
# tasks/anchor/apigwv2-route-settings-zero-vs-unset-hcl-raw/solution/solve.sh
# writes, so every declared tf_jsonpath -- tier 0 and tier 1 -- is resolved
# against a real `terraform show -json` plan.
#
# One difference from that solve.sh, and it is forced: the gate overlays
# this ONE file onto the generated workspace and writes nothing else, so
# the function's code package cannot be a local placeholder file here. It
# is an inline S3 object instead, the same precedent
# generator/tests/fixtures/lambda-alias-tracks-unpublished-latest/hcl_raw/
# main.tf sets. No declared assert reads the packaging.

resource "aws_iam_role" "orders" {
  name = "cdktn-bench-orders-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "orders_logs" {
  role       = aws_iam_role.orders.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_s3_bucket" "orders_packages" {
  bucket_prefix = "cdktn-bench-orders-"
  force_destroy = true
}

resource "aws_s3_object" "orders" {
  bucket         = aws_s3_bucket.orders_packages.id
  key            = "orders.zip"
  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

resource "aws_lambda_function" "orders" {
  function_name = "orders"
  role          = aws_iam_role.orders.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  s3_bucket = aws_s3_bucket.orders_packages.id
  s3_key    = aws_s3_object.orders.key
}

resource "aws_apigatewayv2_api" "orders" {
  name          = "orders-http-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "orders" {
  api_id                 = aws_apigatewayv2_api.orders.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.orders.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_orders" {
  api_id    = aws_apigatewayv2_api.orders.id
  route_key = "GET /orders"
  target    = "integrations/${aws_apigatewayv2_integration.orders.id}"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "prod"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 100
    throttling_burst_limit = 200
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orders.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.orders.execution_arn}/*/*"
}
