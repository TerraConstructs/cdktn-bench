resource "aws_api_gateway_rest_api" "widgets" {
  name = "widgets-api"
}

resource "aws_api_gateway_resource" "widgets" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id
  parent_id   = aws_api_gateway_rest_api.widgets.root_resource_id
  path_part   = "widgets"
}

resource "aws_api_gateway_resource" "widget" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id
  parent_id   = aws_api_gateway_resource.widgets.id
  path_part   = "{id}"
}

resource "aws_iam_role" "lambda_exec" {
  name = "widgets-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "list_widgets" {
  function_name = "list-widgets"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_lambda_function" "create_widget" {
  function_name = "create-widget"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_lambda_function" "get_widget" {
  function_name = "get-widget"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "index.handler"
  runtime       = "nodejs20.x"
  filename      = "${path.module}/lambda/placeholder.zip"
}

resource "aws_api_gateway_method" "list_widgets" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "list_widgets" {
  rest_api_id             = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widgets.id
  http_method              = aws_api_gateway_method.list_widgets.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.list_widgets.invoke_arn
}

resource "aws_api_gateway_method" "create_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "create_widget" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widgets.id
  http_method              = aws_api_gateway_method.create_widget.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.create_widget.invoke_arn
}

resource "aws_api_gateway_method" "get_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widget.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_widget" {
  rest_api_id              = aws_api_gateway_rest_api.widgets.id
  resource_id              = aws_api_gateway_resource.widget.id
  http_method              = aws_api_gateway_method.get_widget.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.get_widget.invoke_arn
}

resource "aws_lambda_permission" "list_widgets" {
  statement_id  = "AllowAPIGatewayInvokeListWidgets"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_widgets.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets"
}

resource "aws_lambda_permission" "create_widget" {
  statement_id  = "AllowAPIGatewayInvokeCreateWidget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_widget.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/POST/widgets"
}

resource "aws_lambda_permission" "get_widget" {
  statement_id  = "AllowAPIGatewayInvokeGetWidget"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.get_widget.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets/*"
}

resource "aws_api_gateway_deployment" "widgets" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_integration.list_widgets.id,
      aws_api_gateway_integration.create_widget.id,
      aws_api_gateway_integration.get_widget.id,
    ]))
  }

  depends_on = [
    aws_api_gateway_integration.list_widgets,
    aws_api_gateway_integration.create_widget,
    aws_api_gateway_integration.get_widget,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.widgets.id
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  stage_name    = "prod"
}
