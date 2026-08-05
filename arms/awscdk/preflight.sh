#!/usr/bin/env bash
# cdktn-bench / arms/awscdk / preflight.sh
#
# Host-side entry point: builds the awscdk arm image (if not already built)
# and runs its in-container preflight check with no network and no AWS
# credentials, proving the toolchain (tsc, cdk synth) works fully offline.
#
# The actual in-container script lives at environment/preflight.sh — it gets
# COPY'd into the image at /usr/local/bin/preflight.sh by environment/Dockerfile
# so it ships with every task generated from this arm, not just this dev image.
#
# Usage:
#   ./preflight.sh                  # build (if needed) + run
#   IMAGE_TAG=my/tag ./preflight.sh # override the image tag

set -euo pipefail

ARM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${IMAGE_TAG:-cdktn-bench/awscdk:dev}"

if [ "${SKIP_BUILD:-}" != "1" ]; then
  echo "==> docker build -t ${IMAGE_TAG} -f environment/Dockerfile environment/"
  docker build -t "${IMAGE_TAG}" -f "${ARM_DIR}/environment/Dockerfile" "${ARM_DIR}/environment"
fi

echo "==> docker run --rm --network none ${IMAGE_TAG} /usr/local/bin/preflight.sh"
docker run --rm --network none --entrypoint /usr/local/bin/preflight.sh "${IMAGE_TAG}"
