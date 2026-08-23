#!/usr/bin/env bash
# BROKEN fixture -- HAND-AUTHORED, manually run (this negative has no
# `catches` entry of its own: it is the SAME mistake the
# `policy-attached-to-one-role-only` catch already names, written in a different
# authoring SHAPE, exactly like solution/broken/foreach-roles-metrics-on-
# one-role-only/ next to it -- the catch taxonomy records distinct
# MISTAKES, not distinct spellings of one).
#
# Purpose: falsify PATH E, the cardinality-matched block-coverage
# resolution added to oracles/rego/iam-managed-policy-exclusive-vs-
# attachment/policy.rego in REPAIR PASS 9 (see that file's BUG 11 note).
# PATH E credits all N role instances of a for_each'd role block when
# exactly N of an attachment block's planned instances carry one policy
# identity. This fixture is the reference-alt-hcl-cartesian solution with
# ONE {role, policy} pair removed from `local.pairs`, so that policy
# identity is carried by 1 instance against 2 role instances -- PATH E
# must credit nobody and `deny` must fire.
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
    if !(pair[0] == "report_writer" && pair[1] == "metrics")
  }
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each   = local.pairs
  role       = aws_iam_role.this[each.value.role_key].name
  policy_arn = local.policy_arns[each.value.policy_key]
}
HCL

bash tests/static_tiers.sh
