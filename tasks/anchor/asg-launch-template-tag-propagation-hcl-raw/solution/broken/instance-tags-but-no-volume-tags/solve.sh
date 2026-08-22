#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instance-tags-but-no-volume-tags catch: tags
# instances correctly via the ASG's own tag-propagation mechanism, but the
# launch template's tag_specifications has NO "volume" resourceType entry
# at all -- every EBS volume the group's instances launch with stays
# untagged. Reward must be 0.0 via volume-tag-costcenter-present /
# volume-tag-environment-present (tier 0): both resolve to zero nodes.
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

  # THE MISTAKE: no "volume" resourceType tag_specifications entry at all.
}

resource "aws_autoscaling_group" "worker" {
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = [aws_subnet.worker_a.id, aws_subnet.worker_b.id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  tag {
    key                 = "CostCenter"
    value               = "platform-42"
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = "prod"
    propagate_at_launch = true
  }
}
HCL

bash tests/static_tiers.sh
