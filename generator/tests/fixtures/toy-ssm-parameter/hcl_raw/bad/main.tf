# Deliberately-BAD reference fixture for generator/check_reference_paths.py
# -- hardcoded wildcard Action="*"/Resource="*", no reference to the created
# parameter at all, PLUS tier = "Advanced" (F2 fix, 2026-08-06: added
# alongside the new parameter-tier-standard structural_assert so this one
# fixture also proves that check discriminates on the not_exists-on-bad-
# fixture differential, not just resolves vacuously). Used (optionally,
# informationally) to prove the policy-resource-scoped-not-wildcard-tf /
# policy-actions-read-only / parameter-tier-standard checks actually
# DISCRIMINATE (fail on this) rather than being permanently vacuous -- not
# just that they pass on the good fixture.
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
      Action   = "*"
      Resource = "*"
    }]
  })
}
