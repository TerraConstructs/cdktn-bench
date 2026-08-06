#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8; benchmark-
# integrity review finding F2, 2026-08-06). Writes an oracle-CORRECT
# main.tf (verified against generator/tests/fixtures/toy-ssm-parameter/
# hcl_raw/main.tf -- byte-identical to it), then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
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
      Action   = ["ssm:GetParameter", "ssm:GetParameters"]
      Resource = "arn:*:ssm:*:*:parameter${aws_ssm_parameter.greeting.name}"
    }]
  })
}
TF

bash tests/static_tiers.sh
