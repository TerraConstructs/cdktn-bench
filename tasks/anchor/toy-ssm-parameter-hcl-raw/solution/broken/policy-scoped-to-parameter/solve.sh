#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# the policy-scoped-to-parameter catch: hardcoded Action="*"/Resource="*",
# no reference to the created parameter at all (byte-identical to
# generator/tests/fixtures/toy-ssm-parameter/hcl_raw/bad/main.tf, the
# fixture generator/check_reference_paths.py already proved discriminates
# both tier-1 structural_asserts). Tier-0 still passes (parameter/trust
# are correct); reward must be 0.0 from tier-1 (policy.rego) alone.
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

resource "aws_iam_role_policy" "reader_policy" {
  name = "read-greeting-parameter"
  role = aws_iam_role.reader.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}
TF

bash tests/static_tiers.sh
