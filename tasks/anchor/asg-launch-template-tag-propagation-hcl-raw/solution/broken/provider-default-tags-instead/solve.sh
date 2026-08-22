#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the provider-default-tags-instead catch: the agent
# reaches for the AWS provider's default_tags mechanism instead of either
# accepted resource-level mechanism. The shared, non-agent-owned
# provider.tf already declares one default_tags block (project/arm,
# unrelated to this scenario -- see specs/asg-launch-template-tag-
# propagation.yaml's own HARNESS FACT comment); the only file this
# fixture can edit is main.tf, so it adds a SECOND, duplicate
# `provider "aws" {}` block there. Terraform permits exactly one
# non-aliased default provider configuration per config -- reward must be
# 0.0 from `terraform init` itself ("Duplicate provider configuration for
# \"aws\"..."), verified directly against terraform 1.15.8 + this arm's
# real provider.tf fixture at authoring time, BEFORE this file was written
# into the task tree. main.tf otherwise carries no CostCenter/Environment
# tag mechanism anywhere -- even setting the toolchain failure aside,
# aws_autoscaling_group has no tags/tags_all attribute for any default_tags
# mechanism to merge into at all, so this would not have worked even had
# Terraform accepted the duplicate block.
#
# NOTE: this fixture is a solution/broken/ hand-authored proof artifact,
# not an agent-visible file -- writing to the arm's normally non-agent-
# owned provider.tf here is a deliberate, documented exception for
# falsifiability-proof purposes only (see this catch's own description in
# the spec). A real agent trial never does this: the generated
# instruction.md tells the agent not to modify provider.tf, and this
# fixture's own duplicate-provider-block mistake is exactly what happens
# if that guidance is ignored.
set -euo pipefail

cat > main.tf <<'HCL'
# THE MISTAKE: a second, duplicate default provider configuration, trying
# to extend the shared provider.tf's own default_tags block with this
# scenario's two required tags. Rejected by `terraform init` before plan
# ever runs.
provider "aws" {
  default_tags {
    tags = {
      CostCenter  = "platform-42"
      Environment = "prod"
    }
  }
}

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
}

resource "aws_autoscaling_group" "worker" {
  min_size            = 2
  max_size            = 6
  vpc_zone_identifier = [aws_subnet.worker_a.id, aws_subnet.worker_b.id]

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }
}
HCL

bash tests/static_tiers.sh
