#!/usr/bin/env bash
# Reference-ALT solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). NOT a
# negative fixture and NOT a declared catch: a manually re-runnable proof
# that a DIFFERENT, equally correct authoring decision also scores 1.0.
#
# WHAT IT PROVES (binding operator ruling 1, 2026-08-22: a physical
# resource NAME is never load-bearing in this oracle -- identity is
# existence + type + properties, keyed on the plan ADDRESS here and the
# template LOGICAL ID on awscdk): this is solution/solve.sh with each
# role's `name = "..."` replaced by `name_prefix = "...-"`, the ordinary
# hand-written Terraform spelling for "let the provider pick the physical
# name". Terraform then omits `name` from
# `.planned_values...aws_iam_role.values` entirely -- it is
# provider-computed -- so the plan carries no role name at all.
#
# WHY IT IS SHIPPED (REPAIR PASS 10, 2026-08-23): this exact authoring
# decision is the shape an adversarial verifier used to demonstrate an
# arm-parity break -- it scored 1.0 on awscdk and 0.0 here and on
# terraconstructs, with two deny messages the graded plan flatly
# contradicted ("no role has ... AmazonS3ReadOnlyAccess attached" for a
# plan holding two attachments whose `values.policy_arn` IS that literal
# ARN). REPAIR PASSES 7-9 re-keyed role identity onto the plan ADDRESS
# and gave the attachment->role edge five resolution paths, which fixed
# it; until now that fix had no shipped, re-runnable proof on this arm.
# Its siblings are `reference-alt-cdk-no-role-name/` (awscdk) and
# `reference-alt-tcons-no-role-name/` (terraconstructs) -- the same
# authoring decision, three arms, so the parity claim is checkable by
# running three commands.
#
# Verified 2026-08-23, real toolchain (terraform 1.15.8 / hashicorp-aws
# 6.58.0, opa 1.19.0): tier0_pass=1, tier1_status=PASS, deny == [],
# reward 1.0 -- identical to solution/solve.sh and to the two sibling
# proofs on the other arms.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_iam_role" "batch_runner" {
  name_prefix = "batch-runner-"
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
  name_prefix = "report-writer-"
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
