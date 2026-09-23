#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates deployment-missing-integration-dependency: the
# aws_api_gateway_deployment has neither `depends_on` nor `triggers`, so it
# can be provisioned before -- or without ever picking up -- any of the three
# routes. Everything the lambda module authors is correct; the deployment
# edge is raw HCL on this arm and no module reaches it. Tier-0 asserts still
# pass; reward must be 0.0 from tier 1 alone.
set -euo pipefail

cat > main.tf <<'TF'
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

module "list_widgets" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "list-widgets"
  handler       = "index.handler"
  runtime       = "nodejs20.x"

  create_package         = false
  local_existing_package = "${path.module}/lambda/placeholder.zip"

  # The module would otherwise also permission the function's published
  # version; nothing here publishes one.
  create_current_version_allowed_triggers = false

  allowed_triggers = {
    api = {
      service    = "apigateway"
      source_arn = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets"
    }
  }
}

module "create_widget" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "create-widget"
  handler       = "index.handler"
  runtime       = "nodejs20.x"

  create_package         = false
  local_existing_package = "${path.module}/lambda/placeholder.zip"

  create_current_version_allowed_triggers = false

  allowed_triggers = {
    api = {
      service    = "apigateway"
      source_arn = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/POST/widgets"
    }
  }
}

module "get_widget" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "get-widget"
  handler       = "index.handler"
  runtime       = "nodejs20.x"

  create_package         = false
  local_existing_package = "${path.module}/lambda/placeholder.zip"

  create_current_version_allowed_triggers = false

  allowed_triggers = {
    api = {
      service    = "apigateway"
      source_arn = "${aws_api_gateway_rest_api.widgets.execution_arn}/*/GET/widgets/*"
    }
  }
}

resource "aws_api_gateway_method" "list_widgets" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "list_widgets" {
  rest_api_id             = aws_api_gateway_rest_api.widgets.id
  resource_id             = aws_api_gateway_resource.widgets.id
  http_method             = aws_api_gateway_method.list_widgets.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.list_widgets.lambda_function_invoke_arn
}

resource "aws_api_gateway_method" "create_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widgets.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "create_widget" {
  rest_api_id             = aws_api_gateway_rest_api.widgets.id
  resource_id             = aws_api_gateway_resource.widgets.id
  http_method             = aws_api_gateway_method.create_widget.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.create_widget.lambda_function_invoke_arn
}

resource "aws_api_gateway_method" "get_widget" {
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  resource_id   = aws_api_gateway_resource.widget.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_widget" {
  rest_api_id             = aws_api_gateway_rest_api.widgets.id
  resource_id             = aws_api_gateway_resource.widget.id
  http_method             = aws_api_gateway_method.get_widget.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.get_widget.lambda_function_invoke_arn
}

resource "aws_api_gateway_deployment" "widgets" {
  rest_api_id = aws_api_gateway_rest_api.widgets.id

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.widgets.id
  rest_api_id   = aws_api_gateway_rest_api.widgets.id
  stage_name    = "prod"
}
TF

bash tests/static_tiers.sh
