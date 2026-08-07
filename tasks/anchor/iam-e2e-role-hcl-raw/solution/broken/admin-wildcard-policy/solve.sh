#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), negative fixture for the admin-wildcard-policy catch.
# Identical to solution/solve.sh's own reference main.tf EXCEPT for the
# one change described below -- isolates this fixture to ONLY this catch.
#
# THE MISTAKE: the deployer's policy grants a bare Action="*"/Resource="*" statement instead of the scoped statements the reference solution uses. Trivially "works" for the live loop, but must FAIL the tier-0 no-full-service-wildcard-actions check -- the baseline anti-gaming assertion.
set -euo pipefail

cat > main.tf <<'TF'
# NOTE: deliberately NOT `data "aws_caller_identity"` -- arms/hcl-raw/README.md
# ("What terraform plan needs") documents that ANY `data "aws_*"` source makes
# an offline `terraform plan` fail (a real STS call, which the offline dummy
# credentials this arm's provider.tf uses cannot satisfy). A plain variable
# with a harmless placeholder default keeps the OFFLINE static tier's plan
# fully local; a REAL deploy passes the true account id with
# `-var "account_id=$(aws sts get-caller-identity --query Account --output text)"`.
variable "account_id" {
  type        = string
  default     = "123456789012"
  description = "This account's id. Placeholder default for offline plan; pass the real value (e.g. via `aws sts get-caller-identity`) for a real deploy."
}

locals {
  account_id             = var.account_id
  external_id            = "iam-e2e-role-trial-2026"
  deployer_role_name     = "iam-e2e-role-deployer"
  workload_role_name     = "iam-e2e-role-workload"
  role_path               = "/cdktn-bench-task/"
  deployer_role_arn       = "arn:aws:iam::${local.account_id}:role${local.role_path}${local.deployer_role_name}"
  workload_role_arn       = "arn:aws:iam::${local.account_id}:role${local.role_path}${local.workload_role_name}"
  instance_profile_arn    = "arn:aws:iam::${local.account_id}:instance-profile/cdktn-bench-iam-e2e-role-workload-profile"
  ssm_app_param_arn_glob  = "arn:aws:ssm:us-east-1:${local.account_id}:parameter/cdktn-bench-iam-e2e-role/app/*"
  s3_scratch_arn          = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch"
  s3_scratch_objects_arn  = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch/*"
}

# ---------------------------------------------------------------------------
# DEPLOYER role -- assumed by harness/validate.sh to apply+destroy module/.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "deployer" {
  name = local.deployer_role_name
  path = local.role_path

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = { "sts:ExternalId" = local.external_id }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "deployer" {
  name = "iam-e2e-role-deployer-policy"
  role = aws_iam_role.deployer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AdminEverything"
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# WORKLOAD role -- what module/'s instance profile wraps. Never given any
# permission by module/ itself; every grant below is authored here.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "workload" {
  name = local.workload_role_name
  path = local.role_path

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringEquals = { "sts:ExternalId" = local.external_id }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "workload" {
  name = "iam-e2e-role-workload-policy"
  role = aws_iam_role.workload.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadAppParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
          "ssm:DescribeParameters",
        ]
        Resource = local.ssm_app_param_arn_glob
      },
      {
        Sid    = "DecryptSecureStringViaSsm"
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.us-east-1.amazonaws.com" }
        }
      },
      {
        Sid      = "SelfDiscovery"
        Effect   = "Allow"
        Action   = ["ec2:DescribeVolumes", "ec2:DescribeInstances"]
        Resource = "*"
      },
    ]
  })
}

output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}

output "workload_role_arn" {
  value = aws_iam_role.workload.arn
}

output "external_id" {
  value = local.external_id
}
TF

bash tests/static_tiers.sh
