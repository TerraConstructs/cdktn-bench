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
# Expected verdict: reward 0.0, caught at TIER 1 (the Rego policy family in
# oracles/rego/named-resource-replacement/policy.rego), NOT at tier 0. Tier 0
# passes here on purpose -- the group is renamed, the endpoint exists and is
# still wired to it -- which is what makes this fixture exercise the tier-1
# chain for real rather than being rejected earlier by a cheaper check.
# gates/oracle_falsifiability.py verifies the observed tier, not just the
# reward, so a solution that started failing at tier 0 instead would show up as
# a tier-attribution mismatch rather than passing quietly.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_vpc" "internal_services" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "internal-services"
  }
}

resource "aws_subnet" "internal_services_a" {
  vpc_id            = aws_vpc.internal_services.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = "us-east-1a"

  tags = {
    Name = "internal-services-a"
  }
}

resource "aws_security_group" "ssm_endpoint" {
  name        = "platform-internal-services-ssm-endpoint"
  description = "HTTPS from the internal services subnet to the SSM interface endpoint"
  vpc_id      = aws_vpc.internal_services.id

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

resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.internal_services.id
  service_name        = "com.amazonaws.us-east-1.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.internal_services_a.id]
  security_group_ids  = [aws_security_group.ssm_endpoint.id]
  private_dns_enabled = true

  tags = {
    Name = "internal-services-ssm"
  }
}
TF

exec bash tests/static_tiers.sh
