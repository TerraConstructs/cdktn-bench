#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `lifecycle-policy-keeps-wrong-count` -- the
# HARDEST form of that mistake, the same two-rule form hcl_raw's fixture
# carries: untagged images are kept 10 deep, tagged images 100 deep. So a rule
# that expires by image count at 10 IS present, and the repository still
# retains 100 images.
#
# The module changes nothing about this mistake and that is the measurement:
# `repository_lifecycle_policy` is one opaque string input the caller writes,
# validated nowhere inside the module, so `terraform validate` and `plan` both
# accept it and only the assert that decodes the document sees the 100. Must
# score reward 0.0 at tier 0.
set -euo pipefail

cat > main.tf <<'TF'
module "registry" {
  source  = "terraform-aws-modules/ecr/aws"
  version = "3.2.0"

  repository_name               = "service-image-registry"
  repository_image_scan_on_push = true
  repository_force_delete       = true

  repository_lifecycle_policy = jsonencode({
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
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 100
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
