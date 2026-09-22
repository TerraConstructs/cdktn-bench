#!/usr/bin/env bash
# Broken fixture: account-exclusive-policy-attachment -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THE MISTAKE: the team policy is wired by ONE raw aws_iam_policy_attachment
# naming both roles instead of through each role module's `policies` map. That
# resource becomes the account-wide exclusive owner of every principal attached
# to that policy ARN, detaching it from anything another team attaches later.
# The module offers no path to this resource type -- reaching it takes leaving
# the module for raw HCL, which is legal on this arm and is why the catch
# stays declared here.
set -euo pipefail

cat > main.tf <<'HCL'
module "batch_runner" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role"
  version = "6.8.2"

  name            = "batch-runner"
  use_name_prefix = false

  trust_policy_permissions = {
    ecs_tasks = {
      actions    = ["sts:AssumeRole"]
      principals = [{ type = "Service", identifiers = ["ecs-tasks.amazonaws.com"] }]
    }
  }

  policies = {
    s3_read_only = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
  }

  create_instance_profile = false
}

module "report_writer" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role"
  version = "6.8.2"

  name            = "report-writer"
  use_name_prefix = false

  trust_policy_permissions = {
    lambda = {
      actions    = ["sts:AssumeRole"]
      principals = [{ type = "Service", identifiers = ["lambda.amazonaws.com"] }]
    }
  }

  policies = {
    s3_read_only = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
  }

  create_instance_profile = false
}

module "team_metrics" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-policy"
  version = "6.8.2"

  name = "batch-service-roles-team-metrics"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "cloudwatch:PutMetricData"
      Resource = "*"
    }]
  })
}

resource "aws_iam_policy_attachment" "team_metrics" {
  name       = "batch-service-roles-team-metrics"
  roles      = [module.batch_runner.name, module.report_writer.name]
  policy_arn = module.team_metrics.arn
}
HCL

bash tests/static_tiers.sh
