#!/usr/bin/env bash
# BROKEN fixture for the `trust-principals-not-split-across-both-roles`
# catch -- HAND-AUTHORED (SCHEMA.md §8.2 point 8).
#
# Two roles still exist, both policies are still attached additively to
# both of them, and no exclusive-ownership resource or attribute is used
# anywhere -- so every tier-0 assert passes. What is wrong is the PAIRING
# the ticket states: the ticket asks for `batch-runner`, assumed by ECS
# tasks, AND `report-writer`, assumed by Lambda. Here the FIRST role is
# made assumable by both ECS tasks and Lambda, and the second by Step
# Functions instead -- so the role meant to be assumed by Lambda cannot be
# assumed by Lambda at all, while the flattened union of both roles' trust
# principals still contains both service names (which is precisely why the
# two tier-0 `contains` asserts cannot see this and the tier-1 per-role
# rules must).
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_iam_role" "batch_runner" {
  name = "batch-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["ecs-tasks.amazonaws.com", "lambda.amazonaws.com"] }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role" "report_writer" {
  name = "report-writer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# AWS-managed policy: attached additively, per role. policy_arn is a
# static literal (never provider-computed), so this is plan-time-known
# regardless.
resource "aws_iam_role_policy_attachment" "batch_runner_s3_read" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "report_writer_s3_read" {
  role       = aws_iam_role.report_writer.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

# Team-defined policy: a real resource, attached additively to BOTH
# roles. cloudwatch:PutMetricData has no resource-level ARN in IAM's
# policy grammar, so Resource = "*" is the correct, necessary form for
# this specific action, not a "scoped, not broader" mistake.
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

resource "aws_iam_role_policy_attachment" "batch_runner_metrics" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = aws_iam_policy.team_metrics.arn
}

resource "aws_iam_role_policy_attachment" "report_writer_metrics" {
  role       = aws_iam_role.report_writer.name
  policy_arn = aws_iam_policy.team_metrics.arn
}
HCL

bash tests/static_tiers.sh
