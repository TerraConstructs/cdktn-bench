#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the policy-attached-to-one-role-only catch: the
# `aws_iam_role_policy_attachment.report_writer_metrics` resource is
# omitted entirely -- the team-defined policy is attached to
# `batch-runner` only. Tier-0 still passes identically to the reference
# solution (both roles/trust principals correct, no forbidden
# exclusive-attachment resource/attribute used, S3-readonly attached);
# reward must be 0.0 from tier-1 (policy.rego's `deny` rule) alone.
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

resource "aws_iam_role_policy_attachment" "batch_runner_metrics" {
  role       = aws_iam_role.batch_runner.name
  policy_arn = aws_iam_policy.team_metrics.arn
}

# Deliberately missing: no attachment of team_metrics to report_writer.
HCL

bash tests/static_tiers.sh
