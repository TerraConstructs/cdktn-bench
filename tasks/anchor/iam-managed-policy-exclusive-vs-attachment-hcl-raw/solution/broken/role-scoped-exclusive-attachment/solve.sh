#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the role-scoped-exclusive-attachment catch (ADDED IN
# REPAIR PASS 4, 2026-08-22 -- see specs/iam-managed-policy-exclusive-vs-
# attachment.yaml's own header comment, defect 8, and
# oracles/rego/.../policy.rego's own header comment, BUG 5, for the full
# evidence trail): uses ONE `aws_iam_role_policy_attachments_exclusive`
# resource PER ROLE (role-scoped exclusive, declared as such by its own
# name) instead of individual `aws_iam_role_policy_attachment` resources.
#
# THIS FILE PRESERVES, UNCHANGED, THE HCL FROM
# `solution/reference-alt-exclusive/solve.sh` (DELETED in this same
# repair pass -- that path used to be a POSITIVE reference proof, scoring
# 1.0, before REPAIR PASS 4 found that `aws_iam_role_policy_attachments_
# exclusive` removes any out-of-band attachment to that role its own
# `policy_arns` does not list -- exactly what this scenario's ticket
# forbids ("Other teams attach their own policies to these roles out of
# band; that must keep working."). Same HCL, now a NEGATIVE fixture
# instead of a positive one: it plans clean and satisfies every
# *functional* tier-0 assert except the new
# no-role-scoped-exclusive-attachment one, which is exactly what
# falsifies it.
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

# THE MISTAKE: role-scoped exclusive attachment. Each resource below
# becomes the CANONICAL, sole owner of its role's ENTIRE managed-policy
# set -- both roles get the right policies HERE (satisfying every
# functional/tier-0-minus-one assert), but on the next apply this
# resource removes any policy some other team attached to that role
# out of band, which this scenario's own ticket says must keep working.
resource "aws_iam_role_policy_attachments_exclusive" "batch_runner" {
  role_name = aws_iam_role.batch_runner.name
  policy_arns = [
    "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    aws_iam_policy.team_metrics.arn,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "report_writer" {
  role_name = aws_iam_role.report_writer.name
  policy_arns = [
    "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    aws_iam_policy.team_metrics.arn,
  ]
}
HCL

bash tests/static_tiers.sh
