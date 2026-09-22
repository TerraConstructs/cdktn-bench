#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes a main.tf, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# Modules where a module fits (docs/design/hcl-modules-spec-matrix.md §1):
# `iam//modules/iam-role` authors each role plus one ADDITIVE
# aws_iam_role_policy_attachment per entry of its `policies` map (that
# submodule's own main.tf), and `iam//modules/iam-policy` authors the
# team-defined policy. No submodule in `iam@6.8.2` creates the account-wide
# aws_iam_policy_attachment, aws_iam_role_policy_attachments_exclusive, or an
# aws_iam_role.managed_policy_arns argument, so composing the roles from this
# module is what makes the three exclusive-ownership mistakes unreachable here.
#
# `use_name_prefix = false` keeps the roles at the physical names the ticket
# names them; no oracle on any arm grades a physical name, so the module's own
# name_prefix default scores identically (solution/reference-alt-module-default-names/).
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
