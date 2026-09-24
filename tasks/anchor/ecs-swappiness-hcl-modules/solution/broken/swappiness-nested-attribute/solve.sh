#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-nested-attribute catch: `swappiness` is
# placed as a sibling of the container's own top-level fields (name, image,
# memory) instead of nested inside `linuxParameters`.
#
# MEASURED, and the reason this fixture reproduces the catch on this arm at
# all: `container_definitions` is a `map(object(...))`, and Terraform's type
# conversion DISCARDS the unknown top-level key silently -- `validate` and
# `plan` both succeed, and the planned container JSON simply has no
# `swappiness` anywhere. Where hcl_raw ships the mis-nested key into an
# artifact ECS then ignores, the module drops it before the plan; either way
# the tier-0 swappiness-value-correct assert resolves ZERO nodes and `op: eq`
# fails, which is the tier this catch predicts for every TF-shaped arm.
#
# `linuxParameters` carries `maxSwap` ONLY so this fixture isolates the
# nested-attribute catch from the maxSwap-dependency catch: it must fail at
# tier 0, not through the tier-1 Rego rule.
set -euo pipefail

cat > main.tf <<'TF'
module "task" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "7.6.1"

  create_service = false

  name                     = "ecs-swappiness"
  family                   = "ecs-swappiness"
  launch_type              = "EC2"
  requires_compatibilities = ["EC2"]
  network_mode             = "bridge"

  container_definitions = {
    app = {
      image      = "public.ecr.aws/docker/library/nginx:latest"
      memory     = 256
      swappiness = 42

      linuxParameters = {
        maxSwap = 256
      }
    }
  }
}
TF

bash tests/static_tiers.sh
