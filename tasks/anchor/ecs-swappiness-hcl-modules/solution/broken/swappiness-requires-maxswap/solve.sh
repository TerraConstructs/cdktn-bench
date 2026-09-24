#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-requires-maxswap catch: swappiness is set,
# correctly nested, with no maxSwap anywhere.
#
# The module supplies neither half -- `maxSwap` and `swappiness` are both bare
# `optional(number)` with no default, and the container-definition submodule
# only strips nulls and merges `initProcessEnabled` in -- so the planned
# container carries `linuxParameters` = {initProcessEnabled, swappiness} and
# tier 0 PASSES, exactly as on hcl_raw. Only the tier-1 Rego rule
# (oracles/rego/ecs-swappiness/policy.rego) catches it, with the same deny
# message, matching the spec's predicted_tier_caught.hcl: "1".
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
      image  = "public.ecr.aws/docker/library/nginx:latest"
      memory = 256

      linuxParameters = {
        swappiness = 42
      }
    }
  }
}
TF

bash tests/static_tiers.sh
