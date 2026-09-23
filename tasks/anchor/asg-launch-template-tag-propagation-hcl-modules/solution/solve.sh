#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): both resources
# the trap lives across are authored by one call. `terraform-aws-modules/
# autoscaling/aws` 9.3.2 creates the launch template and the Auto Scaling
# group together; `terraform-aws-modules/vpc/aws` 6.7.3 creates the VPC and
# its two private subnets and publishes their ids as `private_subnets`. No
# resource is written raw.
#
# `tags` is the module's one fan-out input: it becomes the ASG's `tag` blocks
# with `propagate_at_launch = true` (main.tf:300-307) and is merged into every
# `tag_specifications` entry the call declares (main.tf:1066-1073). It declares
# none by itself, so the volume half is still an explicit ask -- which is the
# two-mechanism split this scenario measures, intact on this arm. The
# `instance` entry is redundant with the ASG blocks, as it is on hcl_raw.
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

  # The only path to a tagged EBS volume: Auto Scaling's own tag propagation
  # never reaches volumes, so the launch template has to carry the entry.
  tag_specifications = [
    { resource_type = "instance" },
    { resource_type = "volume" },
  ]
}
HCL

bash tests/static_tiers.sh
