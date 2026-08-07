# module/main.tf
#
# FIXED, SEEDED Terraform module for the iam-e2e-role scenario. Byte-identical
# across all three arms and NEVER edited by the agent -- the agent authors
# only the deployer role and the workload role, in its own arm-specific
# substrate (main.tf / lib/scenario-stack.ts at the workspace root), never
# here. This directory is a separate, read-only tree (seeded_files, chmod
# 0o444) the agent's own harness/validate.sh applies on the agent's behalf.
#
# Applied under the AGENT-AUTHORED deployer role's ASSUMED credentials (via
# `aws sts assume-role`, see harness/validate.sh) -- never under the agent's
# own base credentials directly, and never against real AWS credentials
# belonging to anyone but the dedicated benchmark account.
#
# Every module-owned resource name is fixed except the S3 bucket and
# security group, which take a harness-generated trial_id suffix because
# S3 bucket names are unique across ALL of AWS, not just this account.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      Project  = "cdktn-bench"
      Scenario = "iam-e2e-role"
      TrialId  = var.trial_id
    }
  }
}

variable "trial_id" {
  type        = string
  description = "Harness-generated per-invocation suffix (see harness/validate.sh) -- used ONLY to keep the S3 bucket name and security group name collision-free across repeated trials. Never chosen by the agent."
}

variable "workload_role_name" {
  type        = string
  description = "Name (not ARN) of the IAM role the agent authored as the workload role (fixed name iam-e2e-role-workload, path /cdktn-bench-task/ -- see the instruction). This module creates ONLY the EC2 instance profile that wraps it; it does not create the role itself, and does not grant it any permissions -- that is entirely the agent's own deliverable."
}

variable "extra_bucket_enabled" {
  type        = bool
  default     = true
  description = "Mirrors the real episode's tfmigrate_enabled module flag. ON by default -- the scratch bucket (and its non-obvious refresh reads) is always in scope for this scenario."
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_kms_alias" "cdktn_bench" {
  name = "alias/cdktn-bench-iam-e2e-role"
}

# The pre-provisioned, PLAIN (non-secret) SSM parameter under the shared
# fixture path. Read as a data source (NOT created here) so the plan/apply
# this module runs exercises the DEPLOYER role's own ssm:GetParameter
# permission on a resource it does not own -- deliberately the same shape
# as the real episode's `data "aws_route53_zone"` (a data-source read on a
# pre-existing resource with its own IAM surface), just on SSM instead of
# Route53. See specs/iam-e2e-role.yaml's own Route53-drop rationale for why
# this substitution was made.
data "aws_ssm_parameter" "app_config" {
  name = "/cdktn-bench-iam-e2e-role/app/config"
}

# ---------------------------------------------------------------------------
# Reaches the real episode's A9: ec2:GetSecurityGroupsForVpc. Describe* does
# NOT cover Get* -- the AWS provider calls this specific action while
# refreshing a security group's VPC. Every other EC2 read in this module is
# a plain Describe*, so this is the one naming-convention trap.
#
# ec2:GetSecurityGroupsForVpc is ALSO one of the many EC2 actions that does
# not support resource-level permissions at all (must be granted on
# Resource: "*") -- the same mechanical class Route53's GetChange exemplified
# in the real episode. Kept deliberately for that reason -- see the
# Route53-drop rationale in specs/iam-e2e-role.yaml.
# ---------------------------------------------------------------------------
resource "aws_security_group" "scratch" {
  name        = "cdktn-bench-iam-e2e-${var.trial_id}-sg"
  description = "cdktn-bench iam-e2e-role scratch security group"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["127.0.0.1/32"]
  }
}

# ---------------------------------------------------------------------------
# Reaches A8 on the EC2 side (a different KMS grant shape than SSM's) plus
# C-1b's self-discovery angle (see harness/assertions.py). Standalone --
# never attached to a running instance, since this reduced module has no
# EC2 instance/ASG/AMI machinery at all (dropped deliberately, see
# specs/iam-e2e-role.yaml's own module-reduction rationale).
# ---------------------------------------------------------------------------
resource "aws_ebs_volume" "scratch" {
  availability_zone = "us-east-1a"
  size              = 1
  encrypted         = true
  kms_key_id        = data.aws_kms_alias.cdktn_bench.target_key_arn

  tags = {
    Name = "cdktn-bench-iam-e2e-${var.trial_id}-scratch"
  }
}

# ---------------------------------------------------------------------------
# Reaches A3: an S3 bucket behind a module flag (var.extra_bucket_enabled,
# ON by default) plus the non-"GetBucket*" refresh reads that only match
# explicitly-listed actions, never a wildcard.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "scratch" {
  count  = var.extra_bucket_enabled ? 1 : 0
  bucket = "cdktn-bench-iam-e2e-${var.trial_id}-scratch"
}

resource "aws_s3_bucket_ownership_controls" "scratch" {
  count  = var.extra_bucket_enabled ? 1 : 0
  bucket = aws_s3_bucket.scratch[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "scratch" {
  count  = var.extra_bucket_enabled ? 1 : 0
  bucket = aws_s3_bucket.scratch[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.scratch[0].arn,
        "${aws_s3_bucket.scratch[0].arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# Reaches A7 (tag-on-create): creating an IAM Instance Profile while
# `default_tags` is active silently ALSO requires iam:TagInstanceProfile --
# CloudTrail never emits it as a separate event; it has to be reasoned
# about, not replayed. This is the ONE IAM resource the module itself
# creates -- it wraps the agent-authored workload role BY NAME. The role
# itself, and everything it is permitted to do, is 100% agent-authored, in
# the agent's own substrate; this module never grants the workload role
# anything.
# ---------------------------------------------------------------------------
resource "aws_iam_instance_profile" "workload" {
  name = "cdktn-bench-iam-e2e-role-workload-profile"
  role = var.workload_role_name
}

output "security_group_id" {
  value = aws_security_group.scratch.id
}

output "volume_id" {
  value = aws_ebs_volume.scratch.id
}

output "bucket_name" {
  value = var.extra_bucket_enabled ? aws_s3_bucket.scratch[0].bucket : null
}

output "instance_profile_arn" {
  value = aws_iam_instance_profile.workload.arn
}

output "app_config_value" {
  value     = data.aws_ssm_parameter.app_config.value
  sensitive = true
}
