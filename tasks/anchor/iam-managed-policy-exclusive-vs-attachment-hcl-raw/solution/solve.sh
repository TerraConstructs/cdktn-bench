#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# Uses the ADDITIVE `aws_iam_role_policy_attachment` resource for every
# attachment (both the AWS-managed S3-readonly policy and the
# team-defined CloudWatch-metrics policy, on both roles) -- never
# `aws_iam_policy_attachment` (account-wide exclusive -- the
# account-exclusive-policy-attachment catch), never `managed_policy_arns`
# on either `aws_iam_role` (role-scoped exclusive, deprecated -- the
# deprecated-exclusive-role-attribute catch), and never
# `aws_iam_role_policy_attachments_exclusive` either (role-scoped
# exclusive, NOT deprecated but still rejected -- the
# role-scoped-exclusive-attachment catch, REPAIR PASS 4, 2026-08-22: it
# removes any out-of-band attachment to that role its own `policy_arns`
# does not list, which this scenario's own ticket forbids). See
# specs/iam-managed-policy-exclusive-vs-attachment.yaml's own header
# comment for the full evidence trail.
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
}

resource "aws_iam_role" "report_writer" {
  name = "report-writer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
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
