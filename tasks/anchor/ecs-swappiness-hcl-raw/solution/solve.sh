#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
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
        maxSwap    = 256
      }
    }
  ])
}
TF

bash tests/static_tiers.sh
