#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# `force_delete = true` is what makes the destroy succeed against a repository
# that still holds images. NO static assert of this spec reads it on this arm
# (specs/ecr-repo-destroy-force-delete.yaml's header says why): it is graded by
# the teardown tier, which destroys what the live check has just pushed into.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_ecr_repository" "service" {
  name         = "service-image-registry"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  repository = aws_ecr_repository.service.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the 10 most recent images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
TF

bash tests/static_tiers.sh
