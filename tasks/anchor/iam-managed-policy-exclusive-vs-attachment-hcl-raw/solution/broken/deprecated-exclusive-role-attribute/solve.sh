#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the deprecated-exclusive-role-attribute catch: sets
# `managed_policy_arns` directly on `aws_iam_role.batch_runner` (the
# deprecated, role-scoped-exclusive attribute), AND separately keeps an
# `aws_iam_role_policy_attachment` for the team-defined metrics policy on
# the SAME role -- the detach/reattach churn shape the provider's own
# docs warn about verbatim ("this resource will take over exclusive
# management of the role's respective policy types... incompatible
# with... aws_iam_role_policy_attachment... you will get resource cycling
# and/or errors", website/docs/r/iam_role.html.markdown). Everything else
# matches the reference solution -- this fixture isolates exactly one
# mistake, so only no-deprecated-role-managed-policy-arns (tier 0) should
# falsify it.
#
# REPAIR PASS 2 (2026-08-21): `managed_policy_arns` is set to an EXPLICIT
# EMPTY LIST here (was a non-empty literal list before this pass), not
# because the non-empty form was wrong, but because `= []` is the single
# most destructive shape of this exact mistake (the provider's own docs,
# website/docs/r/iam_role.html.markdown: "configuring an empty set... will
# cause Terraform to remove ALL managed policy attachments" out-of-band --
# precisely the failure mode this scenario's one load-bearing prompt
# sentence, "other teams attach their own policies... that must keep
# working", exists to test), and because the FIRST-pass
# `no-deprecated-role-managed-policy-arns` tier-0 assert had a real bug
# that specifically failed to catch `= []` (it read
# `.planned_values...values.managed_policy_arns`, which Terraform OMITS
# entirely for an explicit empty set -- see that assert's own updated
# spec note for the full before/after). Using `= []` here means this
# fixture actually exercises the exact case the bug was in, rather than
# merely a case adjacent to it. batch-runner no longer gets
# AmazonS3ReadOnlyAccess via this role's own (exclusive) attribute, but
# report-writer's aws_iam_role_policy_attachment below still attaches it,
# so this fixture's S3-readonly coverage is unaffected -- it still isolates
# exactly the one mistake this catch is about.
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

  # THE MISTAKE: role-scoped-exclusive attribute, set alongside an
  # additive aws_iam_role_policy_attachment for a DIFFERENT policy on the
  # same role below -- the detach/reattach churn shape. Deliberately an
  # EXPLICIT EMPTY LIST (see this file's own header note) -- the most
  # destructive, and the specifically bug-fixed, variant.
  managed_policy_arns = []
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

# Additive attachment on batch_runner, the SAME role that also sets
# managed_policy_arns above -- the churn-producing mix.
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
