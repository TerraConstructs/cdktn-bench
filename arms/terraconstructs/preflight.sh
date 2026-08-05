#!/usr/bin/env bash
# cdktn-bench / arms/terraconstructs / preflight.sh
#
# Host-side entry point: builds the terraconstructs arm image (if not already
# built) and runs its in-container preflight check with no network access,
# proving the toolchain works fully offline: `cdktn synth` (prebuilt provider
# bindings, no network) followed by `terraform init` + `terraform validate`
# against the pre-warmed hashicorp/aws provider filesystem mirror.
#
# The actual in-container script lives at environment/preflight.sh — it gets
# COPY'd into the image at /usr/local/bin/preflight.sh by
# environment/Dockerfile. Mirrors arms/awscdk/preflight.sh's contract.
#
# Note: this arm needs a Docker daemon memory ceiling of at least ~4GB for
# `tsc`/`cdktn synth`'s type-check pass — see ../README.md "Memory finding"
# and ../../DECISIONS.md "Memory floor for tsc-heavy arms". This script does
# not enforce that (it's a host/daemon setting, not something `docker run`
# --memory alone fixes if the daemon's own VM is capped below it) but a bare
# OOM (container exit 137) here almost certainly means the ceiling is too low,
# not that the toolchain is broken.
#
# Usage:
#   ./preflight.sh                  # build (if needed) + run
#   IMAGE_TAG=my/tag ./preflight.sh # override the image tag

set -euo pipefail

ARM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${IMAGE_TAG:-cdktn-bench/terraconstructs:dev}"

if [ "${SKIP_BUILD:-}" != "1" ]; then
  echo "==> docker build -t ${IMAGE_TAG} -f environment/Dockerfile environment/"
  docker build -t "${IMAGE_TAG}" -f "${ARM_DIR}/environment/Dockerfile" "${ARM_DIR}/environment"
fi

echo "==> docker run --rm --network none --memory 4g ${IMAGE_TAG} /usr/local/bin/preflight.sh"
docker run --rm --network none --memory 4g --entrypoint /usr/local/bin/preflight.sh "${IMAGE_TAG}"
