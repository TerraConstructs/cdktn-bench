#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `repository-not-emptied-on-delete`, predicted tier
# "teardown" on this arm (specs/SCHEMA.md §3, §5.2): the reference solution with
# `force_delete` omitted. It plans, it applies, the repository is exactly what
# the ticket asked for, and the nightly `terraform destroy` fails on a
# repository that still holds images.
#
# IT IS EXPECTED TO SCORE REWARD 1.0. No host gate can run a destroy, so no
# static tier may claim to have caught it; the gate requires the
# CDKTN_BENCH_LIVE_ONLY_CONFIRMED marker instead, and this run EARNS it by
# proving that (1) the plan it delivers differs from the reference's only in
# the `force_delete` attribute, so no other assert could tell them apart, and
# (2) no compiled tier-0 filter and no tier-1 policy in this task's tests/ reads
# that attribute. A provider release that emits the omission elsewhere, or a
# later assert on it, fails one of those checks and withholds the marker --
# turning `make falsifiability` red instead of letting the claim rot.
set -euo pipefail

write_reference() {
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
}

write_broken() {
  cat > main.tf <<'TF'
resource "aws_ecr_repository" "service" {
  name = "service-image-registry"

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
}

# Every scalar in the plan as `path=value`, minus the run timestamp, sorted --
# a whole-document comparison rather than a spot check on the attribute this
# fixture already knows about.
flatten_plan() {
  jq -r 'paths(scalars) as $p | ($p | map(tostring) | join("/")) + "=" + (getpath($p) | tostring)' "$1" \
    | grep -v '^timestamp=' | sort
}

# The reference runs FIRST so the artifact and reward this fixture delivers are
# the BROKEN ones -- the gate reads both from what is left behind.
write_reference
bash tests/static_tiers.sh
cp plan.json plan-reference.json

write_broken
bash tests/static_tiers.sh
cp plan.json plan-broken.json

flatten_plan plan-reference.json > flat-reference.txt
flatten_plan plan-broken.json > flat-broken.txt
differing="$(comm -3 flat-reference.txt flat-broken.txt | sed '/^[[:space:]]*$/d')"

if [ -z "$differing" ]; then
  echo "MARKER REFUSED: the two plans are identical, so this fixture reproduces nothing" >&2
  exit 1
fi
unrelated="$(printf '%s\n' "$differing" | grep -v 'force_delete' || true)"
if [ -n "$unrelated" ]; then
  echo "MARKER REFUSED: the plans differ outside the omitted attribute, so a static assert could tell them apart:" >&2
  printf '%s\n' "$unrelated" >&2
  exit 1
fi

# `ecr_repo_destroy_force_delete` (the Rego package) and
# `ecr-repo-destroy-force-delete` (the scenario id) both contain the attribute
# name as a substring and read nothing; only a real field access counts.
reading_asserts="$(grep -F force_delete tests/static_tiers.sh tests/policy.rego 2>/dev/null \
  | grep -v 'ecr_repo_destroy_force_delete' \
  | grep -v 'ecr-repo-destroy-force-delete' || true)"
if [ -n "$reading_asserts" ]; then
  echo "MARKER REFUSED: this task's own static tiers read the attribute:" >&2
  printf '%s\n' "$reading_asserts" >&2
  exit 1
fi

echo "the delivered plan differs from the reference only in force_delete, and no tier-0 filter or tier-1 policy in tests/ reads it:"
printf '%s\n' "$differing"
echo "CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
