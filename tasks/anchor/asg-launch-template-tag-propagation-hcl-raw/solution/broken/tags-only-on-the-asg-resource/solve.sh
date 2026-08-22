#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the tags-only-on-the-asg-resource catch: writes a
# flat `tags = {...}` map on aws_autoscaling_group, which has no such
# argument at all. Reward must be 0.0 from the toolchain step itself
# (`terraform init`/`validate`, part of plan_command) -- verified directly
# at authoring time against the pinned hashicorp/aws 6.58.0 mirror:
# "Unsupported argument ... An argument named \"tags\" is not expected
# here." No structural_assert or tier-1 policy is ever reached; plan.json
# is never even produced.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_vpc" "worker" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "worker_a" {
  vpc_id            = aws_vpc.worker.id
  cidr_block        = "10.0.0.0/24"
  availability_zone = "us-east-1a"
}

resource "aws_subnet" "worker_b" {
  vpc_id            = aws_vpc.worker.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1b"
}

resource "aws_launch_template" "worker" {
  name          = "cdktn-bench-worker-fleet"
  image_id      = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.small"

  tag_specifications {
    resource_type = "volume"
    tags = {
      CostCenter  = "platform-42"
      Environment = "prod"
    }
  }
}

resource "aws_autoscaling_group" "worker" {
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = [aws_subnet.worker_a.id, aws_subnet.worker_b.id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  # THE MISTAKE: aws_autoscaling_group has no flat `tags` argument -- only
  # repeated `tag` blocks with a required propagate_at_launch. Rejected by
  # `terraform init`/`validate` itself.
  tags = {
    CostCenter  = "platform-42"
    Environment = "prod"
  }
}
HCL

bash tests/static_tiers.sh
