#!/usr/bin/env bash
# Broken fixture: role-scoped-exclusive-attachment -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THE MISTAKE: each role's whole managed-policy set is declared by a raw
# aws_iam_role_policy_attachments_exclusive resource instead of the role
# module's `policies` map. That resource removes, on the next apply, any
# attachment to that role its own policy_arns does not list -- the out-of-band
# survival the ticket requires. Same reachable-only-by-leaving-the-module shape
# as account-exclusive-policy-attachment.
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

resource "aws_iam_role_policy_attachments_exclusive" "batch_runner" {
  role_name = module.batch_runner.name
  policy_arns = [
    "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    module.team_metrics.arn,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "report_writer" {
  role_name = module.report_writer.name
  policy_arns = [
    "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    module.team_metrics.arn,
  ]
}
HCL

bash tests/static_tiers.sh
