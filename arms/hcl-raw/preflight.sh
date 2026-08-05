#!/usr/bin/env bash
# cdktn-bench / arms/hcl-raw / preflight.sh
#
# Host-side entry point: builds the hcl-raw arm image (if not already built)
# and runs its in-container preflight check with no network access, proving
# the toolchain (terraform init + validate, offline via the pre-warmed
# provider filesystem mirror) works fully offline.
#
# The actual in-container script lives at environment/preflight.sh — it gets
# COPY'd into the image at /opt/preflight/preflight.sh by
# environment/Dockerfile so it ships with every task generated from this arm,
# not just this dev image. Mirrors arms/awscdk/preflight.sh's contract.
#
# Usage:
#   ./preflight.sh                  # build (if needed) + run
#   IMAGE_TAG=my/tag ./preflight.sh # override the image tag

set -euo pipefail

ARM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${IMAGE_TAG:-cdktn-bench/hcl-raw:dev}"

if [ "${SKIP_BUILD:-}" != "1" ]; then
  echo "==> docker build -t ${IMAGE_TAG} -f environment/Dockerfile environment/"
  docker build -t "${IMAGE_TAG}" -f "${ARM_DIR}/environment/Dockerfile" "${ARM_DIR}/environment"
fi

echo "==> docker run --rm --network none ${IMAGE_TAG} /opt/preflight/preflight.sh"
docker run --rm --network none --entrypoint /opt/preflight/preflight.sh "${IMAGE_TAG}"
