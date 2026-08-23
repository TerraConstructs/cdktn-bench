#!/usr/bin/env bash
# Reference ALTERNATIVE solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8),
# manually run (no gate iterates `reference-alt-*`; see this scenario's
# spec header for the convention). Proves that the fully-DRY
# "cartesian product of roles x policies" idiom -- a single `for_each`ed
# attachment block keyed on {role,policy} PAIRS, whose keyspace therefore
# differs from the role block's keyspace, and whose `role` argument is a
# DYNAMICALLY indexed reference -- scores reward 1.0, exactly like the
# reference solution.
#
# Every attachment is still the ADDITIVE `aws_iam_role_policy_attachment`
# resource; no exclusive-ownership resource or attribute appears anywhere.
# The roles carry NO physical `name` (only `name_prefix`), so the provider
# computes it -- the operator ruling of 2026-08-22 requires that shape to
# score identically to a literal-name one on every arm.
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

locals {
  policy_arns = {
    s3_read = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
    metrics = aws_iam_policy.team_metrics.arn
  }

  pairs = {
    for pair in setproduct(keys(local.roles), keys(local.policy_arns)) :
    "${pair[0]}:${pair[1]}" => {
      role_key   = pair[0]
      policy_key = pair[1]
    }
  }
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each   = local.pairs
  role       = aws_iam_role.this[each.value.role_key].name
  policy_arn = local.policy_arns[each.value.policy_key]
}
HCL

bash tests/static_tiers.sh
