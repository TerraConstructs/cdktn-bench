#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the account-exclusive-policy-attachment catch: the
# team-defined CloudWatch-metrics policy is attached to both roles via a
# SINGLE `aws_iam_policy_attachment` resource (the account-wide-exclusive
# form, `roles = [both]`) instead of two `aws_iam_role_policy_attachment`
# resources. This is the PLAUSIBLE-WRONG solution -- it plans clean and
# satisfies every tier-0 assert this scenario declares EXCEPT
# no-account-exclusive-policy-attachment, which is exactly what falsifies
# it. See specs/iam-managed-policy-exclusive-vs-attachment.yaml's own
# header comment for the full rationale.
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

resource "aws_iam_role_policy_attachment" "batch_runner_s3_read" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "report_writer_s3_read" {
  role       = aws_iam_role.report_writer.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
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

# THE MISTAKE: account-wide-exclusive attachment. This resource becomes
# the CANONICAL, sole owner of every principal attached to
# aws_iam_policy.team_metrics.arn account-wide -- both roles get the
# policy here (satisfying every functional/tier-0 assert), but the
# mechanism itself is what no-account-exclusive-policy-attachment exists
# to catch.
resource "aws_iam_policy_attachment" "team_metrics_both" {
  name       = "batch-service-roles-team-metrics-attachment"
  policy_arn = aws_iam_policy.team_metrics.arn
  roles      = [aws_iam_role.batch_runner.name, aws_iam_role.report_writer.name]
}
HCL

bash tests/static_tiers.sh
