#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `lifecycle-policy-keeps-wrong-count` -- the
# HARDEST form of that mistake, which is why this arm carries it rather than
# the bare "one number changed" the other two arms use. The policy has two
# rules: untagged images are kept 10 deep, tagged images 100 deep. So a rule
# that expires by image count at 10 IS present, and the repository still
# retains 100 images. Nothing in the toolchain objects (the provider carries
# the policy as an opaque JSON string), the live check's push and the destroy
# both succeed, and an assert asking whether SOME rule keeps 10 scores this
# 1.0 -- which is why the tier-0 assert reads the count of every image-count
# rule as a set. Must score reward 0.0 at tier 0.
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
        description  = "Keep the 10 most recent untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Keep the 100 most recent tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPrefixList  = ["v"]
          countType      = "imageCountMoreThan"
          countNumber    = 100
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
