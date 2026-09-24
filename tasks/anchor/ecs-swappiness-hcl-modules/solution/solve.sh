#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1):
# `terraform-aws-modules/ecs/aws//modules/service` 7.6.1 with
# `create_service = false` is the whole solution -- it authors the task
# definition, its execution role, that role's policy and the task role, and its
# own nested `container-definition` submodule renders the container JSON. No
# raw resource is left, and no cluster is needed for a definition-only task.
#
# `linuxParameters` reaches the artifact through the submodule's typed
# `optional(number)` fields and its `jsonencode()`, so the container JSON the
# plan carries is the same shape the raw resource stores: both tier-0 asserts
# resolve on `values.container_definitions|fromjson` and the tier-1 Rego rule
# reads the decoded object.
#
# `launch_type` is stated alongside `requires_compatibilities` because the
# module defaults both to FARGATE, where swappiness is rejected outright rather
# than tuned; `network_mode` follows for the same reason -- awsvpc is the
# module default and bridge is what an EC2 task definition asks for.
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
        maxSwap    = 256
      }
    }
  }
}
TF

bash tests/static_tiers.sh
