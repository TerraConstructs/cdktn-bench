#!/usr/bin/env bash
# cdktn-bench / arms/hcl-modules / preflight.sh
#
# Host-side entry point: builds the hcl-modules arm image (if not already
# built) and runs its in-container preflight check with no network access,
# proving the toolchain works fully offline — the vendored module tree hashes
# to its manifest, `terraform init` resolves registry module addresses through
# the loopback responder (direct and transitive), `terraform validate` passes
# against the pre-warmed provider mirror, and a version outside the allowlist
# is refused.
#
# The actual in-container script lives at environment/preflight.sh — it gets
# COPY'd into the image at /opt/preflight/preflight.sh by
# environment/Dockerfile so it ships with every task generated from this arm,
# not just this dev image. Mirrors arms/hcl-raw/preflight.sh's contract.
#
# The build needs network (the provider mirror pre-warm); the preflight run
# does not, and is run with --network none to prove it. Bring the asset mirror
# up first (scripts/asset-mirror-up.sh) to build the way `make build-arms` and
# Harbor build.
#
# Usage:
#   ./preflight.sh                  # build (if needed) + run
#   IMAGE_TAG=my/tag ./preflight.sh # override the image tag
#   SKIP_BUILD=1 ./preflight.sh     # run against an already-built image

set -euo pipefail

ARM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="${IMAGE_TAG:-cdktn-bench/hcl-modules:dev}"

if [ "${SKIP_BUILD:-}" != "1" ]; then
  echo "==> docker build -t ${IMAGE_TAG} -f environment/Dockerfile environment/"
  docker build -t "${IMAGE_TAG}" -f "${ARM_DIR}/environment/Dockerfile" "${ARM_DIR}/environment"
fi

echo "==> docker run --rm --network none ${IMAGE_TAG} /opt/preflight/preflight.sh"
docker run --rm --network none --entrypoint /opt/preflight/preflight.sh "${IMAGE_TAG}"
