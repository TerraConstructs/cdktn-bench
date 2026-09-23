#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instance-tags-but-no-volume-tags catch: the launch
# template declares an `instance` tag_specifications entry, so instances are
# reached twice over (that entry plus the ASG tag blocks the same `tags`
# input fans out to), and the `volume` entry -- the one mechanism that ever
# reaches an EBS volume -- is absent. Reward must be 0.0 via
# volume-tag-costcenter-present / volume-tag-environment-present (tier 0).
set -euo pipefail

cat > main.tf <<'HCL'
module "worker_vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name            = "cdktn-bench-worker-fleet"
  cidr            = "10.0.0.0/16"
  azs             = ["us-east-1a", "us-east-1b"]
  private_subnets = ["10.0.0.0/24", "10.0.1.0/24"]
}

module "worker_fleet" {
  source  = "terraform-aws-modules/autoscaling/aws"
  version = "9.3.2"

  name                = "cdktn-bench-worker-fleet"
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = module.worker_vpc.private_subnets

  image_id      = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.small"

  tags = {
    CostCenter  = "platform-42"
    Environment = "prod"
  }

  tag_specifications = [
    { resource_type = "instance" },
  ]
}
HCL

bash tests/static_tiers.sh
