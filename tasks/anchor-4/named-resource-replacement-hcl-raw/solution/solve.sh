#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `named-resource-replacement` (the first BROWNFIELD scenario, SCHEMA.md §2.7 /
# DECISIONS.md Amendment 28). Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `main.tf` already holds the deployed
# configuration for a small internal-service network: a VPC, one private subnet,
# a security group named `internal-services-ssm-endpoint`, and an SSM interface
# VPC endpoint that uses that group. The task is ONE change: rename the group to
# `platform-internal-services-ssm-endpoint` and roll it out.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# `name` is ForceNew on `aws_security_group`, so the rename is a REPLACEMENT.
# Terraform's default replacement order is destroy-then-create, and the group is
# attached to the interface endpoint's ENI -- EC2 answers `DependencyViolation`
# and the apply aborts with the rename half-applied. Re-running retries the same
# destroy, so it does not converge on its own.
#
# `lifecycle { create_before_destroy = true }` inverts the order: the new group
# is created, the endpoint's `security_group_ids` is updated to point at it, and
# only then is the old group destroyed -- at which point nothing holds it. The
# two groups coexist for the duration of the replacement, which is safe here
# precisely BECAUSE this is a rename: the new literal name differs from the old
# one, so there is no `InvalidGroup.Duplicate` collision. (Had the change been
# one that forces replacement while KEEPING the name -- editing `description`,
# say, which EC2 has no update API for -- create_before_destroy alone would
# collide and the group would additionally have to move to `name_prefix`.)
#
# WHY NO STATIC TIER CAN TELL THIS FILE FROM THE NAIVE ONE: `terraform show
# -json` emits no `lifecycle` key anywhere in its configuration representation.
# `solution/broken/rename-replaces-an-in-use-security-group/solve.sh`
# demonstrates that mechanically, offline, by planning both variants and
# diffing the graded artifact.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs.
# LIVE=1: additionally run a real `terraform apply` against the SEEDED,
# non-agent-owned ./provider.tf's ambient credentials, and then assert the
# live oracle. This script never writes or edits provider.tf -- exactly the
# constraint a real agent solving this scenario is under.
set -euo pipefail

LIVE="${LIVE:-0}"

write_solution() {
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
}

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real terraform apply against this account =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
