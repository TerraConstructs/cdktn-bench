#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instances-never-tagged catch: the tags are passed
# only inside the `volume` tag_specifications entry, never through the
# module's `tags`/`autoscaling_group_tags` inputs, so neither
# instance-reaching mechanism carries them -- the ASG's own tag blocks hold
# nothing but the module's `Name` tag. Every tier-0 fact still passes;
# reward must be 0.0 via the tier-1 Rego policy's instance_tag_reaches
# OR-check, which finds neither mechanism for either required key.
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

  tag_specifications = [
    {
      resource_type = "volume"
      tags = {
        CostCenter  = "platform-42"
        Environment = "prod"
      }
    },
  ]
}
HCL

bash tests/static_tiers.sh
