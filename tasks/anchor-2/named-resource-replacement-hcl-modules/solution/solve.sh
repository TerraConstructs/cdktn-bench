#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `named-resource-replacement`, hcl_modules arm (BROWNFIELD, SCHEMA.md §2.7 /
# DECISIONS.md Amendment 28; the arm is Amendment 46). Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already holds the deployed
# configuration for a small internal-service network, composed from
# `terraform-aws-modules`: a `vpc` 6.7.3 call for the VPC and its private
# subnet, that module's `//modules/vpc-endpoints` submodule for the SSM
# interface endpoint, and a root `aws_security_group` named
# `internal-services-ssm-endpoint` that the endpoint call consumes. The task is
# ONE change: rename the group to `platform-internal-services-ssm-endpoint` and
# roll it out.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT -- identical to the hcl_raw arm's, and
# that identity is the measurement. `name` is ForceNew on
# `aws_security_group`, so the rename is a REPLACEMENT; Terraform's default
# replacement order is destroy-then-create; the group is attached to the
# interface endpoint's ENI, so EC2 answers `DependencyViolation` and the apply
# aborts with the rename half-applied. `lifecycle { create_before_destroy =
# true }` inverts the order: the new group is created, the endpoint's
# `security_group_ids` is updated to point at it, and only then is the old
# group destroyed. The two groups coexist for the duration, which is safe
# BECAUSE this is a rename -- the new literal name differs from the old one, so
# there is no `InvalidGroup.Duplicate` collision.
#
# WHY THE SECURITY GROUP STAYS A ROOT RESOURCE HERE, while everything else is
# module-composed: no module block accepts a `lifecycle` meta-argument, so a
# group a module owns cannot be handed one. `vpc//modules/vpc-endpoints@6.7.3`
# main.tf:88-105 writes `create_before_destroy = true` into its own
# `aws_security_group` instead, which means moving the group into that call is
# a SECOND correct answer on this arm and no other -- and also the reason the
# seed could not put it there: a group the module owns arrives already fixed,
# and the seed would have handed the agent a disarmed trap.
#
# WHY NO STATIC TIER CAN TELL THIS FILE FROM THE NAIVE ONE: `terraform show
# -json` emits no `lifecycle` key anywhere in its configuration representation,
# on a module plan exactly as on a flat one.
# `solution/broken/rename-replaces-an-in-use-security-group/solve.sh`
# demonstrates that mechanically, offline.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs.
# LIVE=1: additionally run a real `terraform apply` against the SEEDED,
# non-agent-owned ./provider.tf's ambient credentials, and then assert the live
# oracle. This script never writes or edits provider.tf -- exactly the
# constraint a real agent solving this scenario is under.
set -euo pipefail

LIVE="${LIVE:-0}"

write_solution() {
  cat > main.tf <<'TF'
module "internal_services" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = "internal-services"
  cidr = "10.20.0.0/16"

  azs                  = ["us-east-1a"]
  private_subnets      = ["10.20.1.0/24"]
  private_subnet_names = ["internal-services-a"]

  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_security_group" "ssm_endpoint" {
  name        = "platform-internal-services-ssm-endpoint"
  description = "HTTPS from the internal services subnet to the SSM interface endpoint"
  vpc_id      = module.internal_services.vpc_id

  ingress {
    description = "HTTPS from the internal services VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-internal-services-ssm-endpoint"
  }

  # Renaming this group forces a replacement, and it is attached to the
  # interface endpoint's ENI: the default destroy-then-create order cannot
  # delete it while the endpoint holds it.
  lifecycle {
    create_before_destroy = true
  }
}

module "ssm_endpoint" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "6.7.3"

  region = "us-east-1"

  vpc_id             = module.internal_services.vpc_id
  subnet_ids         = module.internal_services.private_subnets
  security_group_ids = [aws_security_group.ssm_endpoint.id]

  endpoints = {
    ssm = {
      service_endpoint    = "com.amazonaws.us-east-1.ssm"
      private_dns_enabled = true
      tags = {
        Name = "internal-services-ssm"
      }
    }
  }
}
TF
}

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
