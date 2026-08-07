#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), negative fixture for the wildcard-matches-protected-bucket catch.
# Identical to solution/solve.sh's own reference main.tf EXCEPT for the
# one change described below -- isolates this fixture to ONLY this catch.
#
# THE MISTAKE: the S3 resource scope drops the "-scratch" suffix the module's own bucket naming convention has -- "arn:aws:s3:::cdktn-bench-iam-e2e-*" is derived correctly from the module's prefix but ALSO matches the pre-provisioned decoy bucket (cdktn-bench-iam-e2e-tfstate-<account>-us-east-1), a real bucket this task's own module never creates or references. Every static tier-0 check still PASSES (no admin wildcard, no invalid action, valid trust) -- only the tier-1 Rego/cfn-guard glob-match check catches this, exactly like the real episode's own A11 defect: no failing run would ever surface it on its own.
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
  s3_scratch_arn          = "arn:aws:s3:::cdktn-bench-iam-e2e-*"
  s3_scratch_objects_arn  = "arn:aws:s3:::cdktn-bench-iam-e2e-*/*"
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
        Sid    = "ReadOnlyDiscovery"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:GetSecurityGroupsForVpc",
          "ec2:DescribeVolumeStatus",
          "ssm:DescribeParameters",
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
      {
        Sid      = "SsmRead"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = local.ssm_app_param_arn_glob
      },
      {
        Sid    = "InstanceProfileLifecycle"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile",
          "iam:ListInstanceProfilesForRole",
          "iam:GetRole",
          "iam:ListRoleTags",
        ]
        Resource = [local.instance_profile_arn, local.workload_role_arn]
      },
      {
        Sid       = "AssumeWorkloadForTesting"
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Resource  = local.workload_role_arn
      },
      {
        Sid    = "Ec2Write"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:CreateVolume",
          "ec2:DeleteVolume",
        ]
        Resource = "*"
      },
      {
        Sid    = "KmsUseForEbs"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ec2.us-east-1.amazonaws.com" }
        }
      },
      {
        Sid    = "S3Scratch"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:DeleteBucket",
          "s3:ListBucket",
          "s3:GetBucket*",
          "s3:PutBucket*",
          "s3:DeleteBucketPolicy",
          "s3:ListTagsForResource",
          "s3:GetAccelerateConfiguration",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
        ]
        Resource = [local.s3_scratch_arn, local.s3_scratch_objects_arn]
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
