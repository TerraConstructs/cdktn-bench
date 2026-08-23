#!/usr/bin/env bash
# Reference-ALT solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Proves
# the FOR_EACH-OVER-POLICIES shape (REPAIR PASS 5, 2026-08-22, adversarial-
# verifier finding, BUG 6 in oracles/rego/.../policy.rego's own header
# comment): a single `locals.shared_policy_arns` map naming BOTH policies
# (the AWS-managed S3-readonly ARN as a literal, the team-defined policy's
# ARN as a resource reference), attached to each role via ONE
# `aws_iam_role_policy_attachment` resource per role with
# `for_each = local.shared_policy_arns`. This is a fully correct, additive,
# idiomatically-DRY solution -- every attachment is still
# `aws_iam_role_policy_attachment` (never an exclusive resource/attribute)
# -- but its `policy_arn = each.value` expression never REFERENCES
# `aws_iam_policy.team_metrics` directly (the reference is to `each.value`,
# an iteration variable), which is exactly the graph-edge shape BUG 6
# fixed policy.rego to resolve via a plan-time-unknown fallback instead of
# a literal `.references` match. See that file's own BUG 6 comment for the
# full evidence trail (a prior policy.rego scored this shape reward 0.0
# with a deny message falsely claiming the policy was unattached).
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

# Both policies both roles need, named once, in one place -- the
# idiomatically-DRY authoring choice this reference-alt exists to prove is
# oracle-accepted. One value is a plan-time-known literal (the AWS-managed
# policy's ARN never changes), the other is a reference to a
# not-yet-created resource's own `.arn` (unknown until apply) -- both are
# ordinary, legitimate map values.
locals {
  shared_policy_arns = {
    s3_read_only = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
    team_metrics = aws_iam_policy.team_metrics.arn
  }
}

resource "aws_iam_role_policy_attachment" "batch_runner" {
  for_each   = local.shared_policy_arns
  role       = aws_iam_role.batch_runner.name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "report_writer" {
  for_each   = local.shared_policy_arns
  role       = aws_iam_role.report_writer.name
  policy_arn = each.value
}
HCL

bash tests/static_tiers.sh
