#!/usr/bin/env bash
# Broken fixture: policy-attached-to-one-role-only -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THE MISTAKE: the team-defined policy is in batch-runner's `policies` map
# and absent from report-writer's, so only one role receives it. Every tier-0
# assert passes; the per-role coverage rule at tier 1 is what sees it.
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
    team_metrics = module.team_metrics.arn
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
HCL

bash tests/static_tiers.sh
