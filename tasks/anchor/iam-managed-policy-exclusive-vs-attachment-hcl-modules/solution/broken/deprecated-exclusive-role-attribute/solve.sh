#!/usr/bin/env bash
# Broken fixture: deprecated-exclusive-role-attribute -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THE MISTAKE: batch-runner is authored as a raw aws_iam_role carrying the
# deprecated, role-scoped-exclusive `managed_policy_arns = []` alongside
# additive attachments on the same role -- the detach/reattach churn shape. The
# empty set is the most destructive variant: it removes ALL managed-policy
# attachments on every apply. `iam//modules/iam-role` never emits this
# argument, so the mistake is reachable only by authoring the role raw.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_iam_role" "batch_runner" {
  name = "batch-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  managed_policy_arns = []
}

resource "aws_iam_role_policy_attachment" "batch_runner_s3_read" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "batch_runner_metrics" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = module.team_metrics.arn
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
