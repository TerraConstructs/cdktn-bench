#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-readonly-missing-on-one-role catch: the AWS
# managed policy AmazonS3ReadOnlyAccess is attached to `batch-runner`
# only -- the `report_writer_s3_read` attachment resource is simply
# absent, so report-writer has no read access to the reporting data in S3
# at all, which the ticket's second paragraph asks for on BOTH roles.
# Everything else is byte-identical to solution/solve.sh: both roles
# exist with the right trust principals, the team-defined metrics policy
# is still attached additively to both, and no exclusive-ownership
# resource or attribute is used anywhere. Every tier-0 assert therefore
# passes exactly as it does for the reference solution; reward must be
# 0.0 from tier-1 alone (policy.rego's AmazonS3ReadOnlyAccess deny rule,
# whose per-role set difference over role plan ADDRESSES REPAIR PASS 7
# introduced -- before that tightening this fixture scored reward 1.0,
# which is the defect it exists to keep fixed; see
# specs/iam-managed-policy-exclusive-vs-attachment.yaml's header comment,
# defect 13).
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

# THE MISTAKE: the AWS-managed S3-readonly policy is attached to
# batch-runner only. The matching `report_writer_s3_read` attachment the
# reference solution carries is absent, so report-writer never gets the
# read access the ticket asks for on both roles.
resource "aws_iam_role_policy_attachment" "batch_runner_s3_read" {
  role       = aws_iam_role.batch_runner.name
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
