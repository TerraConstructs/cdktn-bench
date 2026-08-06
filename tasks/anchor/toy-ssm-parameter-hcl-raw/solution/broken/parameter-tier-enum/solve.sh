#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8; benchmark-integrity review finding F2, 2026-08-06). Violates
# ONLY the parameter-tier-enum catch (spec's oracle.structural_asserts
# "parameter-tier-standard", tier "0"): explicitly sets tier = "Advanced"
# where the instruction implies the default (Standard, i.e. unset).
# Everything else is identical to solution/solve.sh (still correct), so
# this isolates the one catch -- reward must be 0.0 from tier-0 alone.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_ssm_parameter" "greeting" {
  name  = "/cdktn-bench-toy/greeting"
  type  = "String"
  value = "hello-from-cdktn-bench"
  tier  = "Advanced"
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
