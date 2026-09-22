#!/usr/bin/env bash
# Reference solution (alternative shape) -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# The same composition with `use_name_prefix` left at the module's own default,
# so both role names are provider-computed from a prefix and `values.role` on
# every attachment instance is plan-time-unknown. Scores 1.0: no oracle on any
# arm grades a physical role name, and the attachment->role edge resolves
# through the module body's own `role = aws_iam_role.this[0].name` reference.
set -euo pipefail

cat > main.tf <<'HCL'
module "batch_runner" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role"
  version = "6.8.2"

  name            = "batch-runner"

  trust_policy_permissions = {
    ecs_tasks = {
      actions    = ["sts:AssumeRole"]
      principals = [{ type = "Service", identifiers = ["ecs-tasks.amazonaws.com"] }]
    }
  }

  policies = {
    s3_read_only = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
    team_metrics = module.team_metrics.arn
  }

  create_instance_profile = false
}

module "report_writer" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role"
  version = "6.8.2"

  name            = "report-writer"

  trust_policy_permissions = {
    lambda = {
      actions    = ["sts:AssumeRole"]
      principals = [{ type = "Service", identifiers = ["lambda.amazonaws.com"] }]
    }
  }

  policies = {
    s3_read_only = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
    team_metrics = module.team_metrics.arn
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
HCL

bash tests/static_tiers.sh
