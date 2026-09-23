#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): the registry
# publishes no module for API Gateway REST v1, so the rest API, its two
# resources, the three methods and integrations, the deployment and the stage
# are raw HCL here exactly as on hcl_raw. `terraform-aws-modules/lambda/aws`
# 8.8.2 replaces what each route's handler took by hand -- the function, the
# execution role shared across all three, and the invoke permission, which the
# module derives from one `allowed_triggers` entry.
#
# The deployment still carries BOTH an explicit `depends_on` and a `triggers`
# checksum over all three integrations: the module side of this solution
# reaches none of that, which is the whole point of measuring this scenario on
# this arm.
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
TF

bash tests/static_tiers.sh
