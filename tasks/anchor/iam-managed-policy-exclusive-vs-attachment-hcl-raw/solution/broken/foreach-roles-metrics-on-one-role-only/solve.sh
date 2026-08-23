#!/usr/bin/env bash
# BROKEN fixture (extra, non-catch-named -- gates/oracle_falsifiability.py
# discovers and requires reward 0.0). HAND-AUTHORED.
#
# The NO-OVER-CREDIT half of REPAIR PASS 8 / BUG 10 (oracles/rego/.../
# policy.rego). BUG 10 taught the oracle to read an INSTANCE-qualified
# `expressions.role.references` entry (`aws_iam_role.this["batch_runner"]`)
# as the covered role. A careless version of that widening -- crediting
# the whole `aws_iam_role.this` BLOCK instead of the one instance the
# reference names -- would credit one attachment to EVERY role the block
# produces and silently kill the policy-attached-to-one-role-only catch in
# exactly the world (provider-computed role names) BUG 10 opened up.
#
# This fixture is `reference-alt-hcl-foreach-roles/solve.sh` verbatim with
# the `writer_metrics` attachment deleted: for_each'd roles, `name_prefix`
# (no physical role name anywhere), team-metrics policy reaching only
# `batch_runner`. It MUST be caught at tier 1, and the deny message must
# name exactly `{aws_iam_role.this["report_writer"]}` -- verified
# 2026-08-23 against a real `terraform plan` (1.15.8 / hashicorp-aws
# 6.58.0) + `opa eval` 1.19.0.
set -euo pipefail

cat > main.tf <<'HCL'
locals {
  roles = {
    batch_runner  = "ecs-tasks.amazonaws.com"
    report_writer = "lambda.amazonaws.com"
  }
}

resource "aws_iam_role" "this" {
  for_each    = local.roles
  name_prefix = "${replace(each.key, "_", "-")}-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = each.value }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "team_metrics" {
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

resource "aws_iam_role_policy_attachment" "runner_s3" {
  role       = aws_iam_role.this["batch_runner"].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "writer_s3" {
  role       = aws_iam_role.this["report_writer"].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "runner_metrics" {
  role       = aws_iam_role.this["batch_runner"].name
  policy_arn = aws_iam_policy.team_metrics.arn
}

HCL

bash tests/static_tiers.sh
