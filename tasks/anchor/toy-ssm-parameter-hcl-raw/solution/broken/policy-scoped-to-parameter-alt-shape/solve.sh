#!/usr/bin/env bash
# Deliberately-BAD reference solution -- extra negative fixture added by the
# "tier-1 oracle vacuity -- IAM shape coverage" fix (2026-08-06), alongside
# widening oracles/rego/toy-ssm-parameter/policy.rego. NOT keyed to a
# spec.catches[] name (gates/oracle_falsifiability.py discovers any
# solution/broken/<dir>/ not matching a declared catch name and requires it
# to score 0.0 too, same as a catch-named one) -- this is a SECOND,
# equally-idiomatic way to violate policy-scoped-to-parameter, using a
# standalone `aws_iam_policy` + `aws_iam_role_policy_attachment` instead of
# an inline `aws_iam_role_policy`. PROVEN vacuous against the pre-fix
# policy.rego: `role_policies`/`planned_role_policies` filtered
# `r.type == "aws_iam_role_policy"` ONLY, so a plan with an `aws_iam_policy`
# (Action="*", Resource="*") attached via `aws_iam_role_policy_attachment`
# produced an EMPTY `deny` set --
#   $ opa eval -f raw -I -d <old policy.rego> \
#       'data.cdktn_bench.toy_ssm_parameter.deny' < plan.json
#   []
# -- tier1_status=PASS, reward=1.0. Tier-0 still passes (parameter/trust are
# correct); reward must be 0.0 from tier-1 (policy.rego's now-widened
# policy_resources collection) alone.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_ssm_parameter" "greeting" {
  name  = "/cdktn-bench-toy/greeting"
  type  = "String"
  value = "hello-from-cdktn-bench"
}

resource "aws_iam_role" "reader" {
  name = "cdktn-bench-toy-ssm-reader"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "admin" {
  name = "admin-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.reader.name
  policy_arn = aws_iam_policy.admin.arn
}
TF

bash tests/static_tiers.sh
