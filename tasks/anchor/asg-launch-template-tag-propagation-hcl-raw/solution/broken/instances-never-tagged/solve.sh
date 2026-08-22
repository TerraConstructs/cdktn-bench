#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instances-never-tagged catch: the launch
# template's volume tag_specifications correctly carries both keys, but
# NEITHER accepted instance-reaching mechanism is present -- no ASG `tag`
# blocks at all, and no "instance" resourceType tag_specifications entry
# either. Every tier-0 fact this scenario declares still passes (ASG
# exists, capacity, launch template exists, both volume-tag values,
# instance type, AMI); reward must be 0.0 via the tier-1 Rego policy's
# instance_tag_reaches OR-check, which finds neither mechanism for either
# required key.
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
  # THE MISTAKE: no "instance" resourceType tag_specifications entry.
}

resource "aws_autoscaling_group" "worker" {
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = [aws_subnet.worker_a.id, aws_subnet.worker_b.id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  # THE MISTAKE: no ASG-level `tag` blocks for CostCenter/Environment at
  # all.
}
HCL

bash tests/static_tiers.sh
