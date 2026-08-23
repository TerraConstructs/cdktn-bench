#!/usr/bin/env bash
# Reference-ALT solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Proves
# the FOR_EACH-OVER-ROLES + PROVIDER-COMPUTED-ROLE-NAME shape (REPAIR
# PASS 8, 2026-08-23, adversarial-verifier finding, BUG 10 in
# oracles/rego/.../policy.rego's own header comment).
#
# Two roles from one `for_each = local.roles` block, carrying NO physical
# role name at all (`name_prefix`, so AWS computes the name -- exactly
# what the terraconstructs L2 does by default when `roleName` is omitted,
# and what CDK does when `roleName` is omitted), attached by four
# ORDINARY, non-iterated `aws_iam_role_policy_attachment` blocks that each
# name one role instance directly (`aws_iam_role.this["batch_runner"]`).
# Fully correct and fully additive -- every attachment is still
# `aws_iam_role_policy_attachment`, both policies reach both roles.
#
# Before REPAIR PASS 8 this scored reward 0.0 while the byte-identical
# config with `name = replace(each.key, "_", "-")` scored 1.0 -- one
# attribute apart -- and the same authoring decision (DRY loop over a role
# map, no physical role name) scored 1.0 on BOTH awscdk and
# terraconstructs. That is the arm-parity break operator RULING 1
# (2026-08-22: physical resource NAMES are never load-bearing in an
# oracle) forbids. This fixture is the regression guard: it must stay at
# reward 1.0, and so must the same file with `name_prefix` swapped back to
# `name`.
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

resource "aws_iam_role_policy_attachment" "writer_metrics" {
  role       = aws_iam_role.this["report_writer"].name
  policy_arn = aws_iam_policy.team_metrics.arn
}
HCL

bash tests/static_tiers.sh
