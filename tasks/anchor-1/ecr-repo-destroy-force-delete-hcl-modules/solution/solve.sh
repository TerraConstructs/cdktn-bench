#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): one
# `terraform-aws-modules/ecr/aws` 3.2.0 call is the whole solution -- it
# composes the repository, its lifecycle policy and a repository policy, so no
# raw resource is left.
#
# `repository_force_delete = true` is what makes the destroy succeed against a
# repository that still holds images; the module passes it straight onto the
# provider's `force_delete`. NO static assert of this spec reads it on this arm
# (specs/ecr-repo-destroy-force-delete.yaml's header says why): it is graded by
# the teardown tier, which destroys what the live check has just pushed into.
#
# The retention rule is stated explicitly because the module's own default for
# `repository_lifecycle_policy` is the empty string, which is not a policy
# document. `repository_image_scan_on_push` is stated for the opposite reason:
# the module already defaults it to true, and writing it makes the requirement
# the ticket names visible in the call rather than inherited.
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
