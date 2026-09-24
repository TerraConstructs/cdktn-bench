#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `ingress-widened-to-the-internet`, predicted_tier_caught "1" on every arm.
#
# THE MISTAKE: re-authoring the security group is exactly where an ingress rule
# gets "tidied up". This fixture does the rename correctly AND keeps
# create_before_destroy -- it would deploy cleanly -- but widens the 443 ingress
# from the VPC CIDR to 0.0.0.0/0, putting the SSM interface endpoint on the
# public internet.
#
# The group is a root resource on this arm, so the widening is the same edit to
# the same inline `ingress` block as on hcl_raw, and the tier-1 policy reads it
# from the same `planned_values` path. The two module calls are left exactly as
# the seed composed them -- the mistake is not about composition, and a fixture
# that also disturbed the modules could not attribute its 0.0 to this catch.
#
# Expected verdict: reward 0.0, caught at TIER 1 (the Rego policy family in
# oracles/rego/named-resource-replacement/policy.rego), NOT at tier 0. Tier 0
# passes here on purpose -- the group is renamed and the endpoint still exists
# -- which is what makes this fixture exercise the tier-1 chain for real rather
# than being rejected earlier by a cheaper check.
# gates/oracle_falsifiability.py verifies the observed tier, not just the
# reward, so a solution that started failing at tier 0 instead would show up as
# a tier-attribution mismatch rather than passing quietly.
set -euo pipefail

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
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
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

exec bash tests/static_tiers.sh
