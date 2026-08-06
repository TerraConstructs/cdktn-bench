#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-requires-maxswap catch: swappiness is
# set, correctly nested, with no maxSwap anywhere. Unlike awscdk/
# terraconstructs, hcl_raw's untyped `container_definitions` JSON has no
# construct to silently drop this -- `swappiness: 42` sits right there,
# literal and structurally correct, in the plan JSON. Tier 0 (
# swappiness-value-correct) PASSES this fixture; only the tier-1 Rego rule
# (oracles/rego/ecs-swappiness/policy.rego) catches it -- matching the
# spec's predicted_tier_caught.hcl: "1" for this catch.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_ecs_task_definition" "app" {
  family                   = "ecs-swappiness"
  requires_compatibilities = ["EC2"]
  network_mode              = "bridge"

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = "public.ecr.aws/docker/library/nginx:latest"
      memory    = 256
      essential = true
      linuxParameters = {
        swappiness = 42
      }
    }
  ])
}
TF

bash tests/static_tiers.sh
