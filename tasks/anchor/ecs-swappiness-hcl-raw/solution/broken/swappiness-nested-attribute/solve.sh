#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-nested-attribute catch: `swappiness` is
# placed as a sibling of the container's own top-level fields (name,
# image, memory) instead of nested inside `linuxParameters` -- exactly the
# mistake an untyped `container_definitions` JSON blob silently accepts
# (`terraform validate`/`plan` never inspect its interior shape).
# `linuxParameters` is correctly populated with `maxSwap` ONLY (no
# swappiness) so this fixture isolates the nested-attribute catch from the
# maxSwap-dependency catch -- it must fail via swappiness-value-correct
# (tier 0), not via the tier-1 rego rule.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_ecs_task_definition" "app" {
  family                   = "ecs-swappiness"
  requires_compatibilities = ["EC2"]
  network_mode              = "bridge"

  container_definitions = jsonencode([
    {
      name       = "app"
      image      = "public.ecr.aws/docker/library/nginx:latest"
      memory     = 256
      essential  = true
      swappiness = 42
      linuxParameters = {
        maxSwap = 256
      }
    }
  ])
}
TF

bash tests/static_tiers.sh
