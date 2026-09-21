# arms/terraconstructs — AWSCDK-style L2 constructs (terraconstructs) synthesizing
# Terraform via cdktn (the community fork of cdktf, formerly "CDK Terrain").
#
# Toolchain: Node 22 + TypeScript + terraconstructs + cdktn/cdktn-cli + the
# @cdktn/provider-* prebuilt bindings terraconstructs' peerDependencies require,
# plus the `terraform` CLI + a pre-warmed hashicorp/aws provider filesystem
# mirror for the arm's validate/plan gate (no apply, no credentials — see
# ../README.md and docs/aws-bench-guide.md §7c).
#
# Versions pinned to what terraconstructs@0.2.13 was built/tested against
# (its own devDependencies), not just "whatever satisfies the peer range" —
# see ../README.md "Version pins" for the research trail.
#
# --- Build-context contract ---
# The aws-bench/Harbor runner always builds a task's environment/ directory
# AS the Docker build context (harbor/environments/docker/docker.py
# `context_dir=self.environment_dir`); it never uses the arm root. Every COPY
# below is therefore relative to THIS directory (environment/), matching
# arms/awscdk and arms/hcl-raw. Build with:
#   cd arms/terraconstructs/environment && docker build -t cdktn-bench/terraconstructs:dev .
# See ../../DECISIONS.md "Arm build-context contract".
FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS base
# NOTE: deliberately no default value -- one of BuildKit's predefined
# platform ARGs, auto-populated from --platform (or the builder's native
# platform). A literal default would shadow that auto-injected value and
# silently install the wrong-arch opa binary below on a non-default build
# host -- see arms/hcl-raw/environment/Dockerfile's own TARGETARCH comment.
ARG TARGETARCH

ARG TERRACONSTRUCTS_VERSION=0.2.13
ARG CDKTN_VERSION=0.23.0
ARG CDKTN_CLI_VERSION=0.23.0
ARG CONSTRUCTS_VERSION=10.6.0
ARG PROVIDER_AWS_VERSION=24.8.0
ARG PROVIDER_ARCHIVE_VERSION=13.1.0
ARG PROVIDER_CLOUDINIT_VERSION=13.1.0
ARG PROVIDER_DOCKER_VERSION=15.3.0
ARG PROVIDER_TIME_VERSION=13.1.0
ARG PROVIDER_TLS_VERSION=13.1.0
ARG AWS_CDK_CAS_VERSION=49.4.0
ARG AWS_CDK_REGION_INFO_VERSION=2.233.0
ARG TYPESCRIPT_VERSION=5.7.3
ARG TS_NODE_VERSION=10.9.1
ARG TERRAFORM_VERSION=1.15.8
# Exact hashicorp/aws version @cdktn/provider-aws@24.8.0's generated Terraform
# JSON pins (`required_providers.aws.version`) — verified by running this
# arm's own `cdktn synth` and reading the emitted terraform{} block. This is
# NOT the same version arms/hcl-raw mirrors (6.58.0) — see
# ../../DECISIONS.md "TF provider version per arm" for why that's fine.
ARG TERRAFORM_AWS_PROVIDER_VERSION=6.52.0

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=development \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false \
    CHECKPOINT_DISABLE=1

# --- baseline agent-container utilities + terraform CLI (HashiCorp apt repo,
# --- pinned exact version) ---
# terraform serves the generated tests/static_tiers.sh (`validate` + `plan`)
# and this image's own preflight (`cdktn synth` -> `terraform init` ->
# `validate`, offline against the provider mirror below). git/curl/unzip
# and python3 (stdlib only; tests/test.sh runs `python3 live_check.py`) are
# the agent-container baseline shared with arms/awscdk and arms/hcl-raw
# (DECISIONS.md "Agent-container baseline contract").
# The HashiCorp apt source and keyring are removed once terraform is
# installed: Harbor runs `apt-get update` in this image at trial start to
# install the agent CLI, and a rotated HashiCorp signing key then fails that
# update (NO_PUBKEY) and voids every trial on this arm before the agent runs.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      unzip \
      ca-certificates \
      git \
      less \
      python3 \
    && curl -fsSL https://apt.releases.hashicorp.com/gpg -o /tmp/hashicorp.gpg \
    && gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg /tmp/hashicorp.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
      > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends terraform=${TERRAFORM_VERSION}-* \
    && rm -f /etc/apt/sources.list.d/hashicorp.list /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && rm -rf /var/lib/apt/lists/* /tmp/hashicorp.gpg

# --- ASSET_MIRROR: base URL of a local mirror of the pinned build-time
# --- downloads below (scripts/asset_mirror.py serve). The default is
# --- NON-EMPTY and nothing overrides it, so every builder -- `make build-arms`,
# --- scripts/prebuild-tasks.sh, and the no-build-arg `docker compose build`
# --- the harness runs -- hashes these RUN lines identically and shares one
# --- layer cache. Each fetch below probes the mirror and falls back to
# --- upstream when it does not answer, so a build with no mirror running
# --- still succeeds; see docs/asset-mirror.md.
# --- Every fetch still runs its hardcoded `sha256sum -c`, so the mirror is a
# --- SOURCE and never an authority: a substituted file fails the build.
ARG ASSET_MIRROR=http://host.lima.internal:8899

# --- opa (Open Policy Agent) 1.19.0: static pinned binary, sha256-verified
# --- (same pin as arms/hcl-raw -- see ../../../DECISIONS.md "tier-1 grading
# --- tools installed in every arm image"). This is the tool
# --- generator/gen.py's generated tests/static_tiers.sh runs for this arm's
# --- tier-1 (`opa eval -d policy.rego 'data.<pkg>.deny' < plan.json`), same
# --- as arms/hcl-raw since both are graded against the same
# --- `terraform show -json` plan shape.
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) OPA_SHA256="1dd5c5591ff856f5e20a1d66bafae9511ddf3c5552ed3b5070c70b2b6580ee3f" ;; \
      arm64) OPA_SHA256="06680087ed236c8c6aaa021660d83178db829a2ad30bdb3482481fada6791b2a" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    URL="https://github.com/open-policy-agent/opa/releases/download/v1.19.0/opa_linux_${TARGETARCH}_static"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/opa_linux_${TARGETARCH}_static"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /usr/local/bin/opa "$URL"; \
    echo "${OPA_SHA256}  /usr/local/bin/opa" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/opa; \
    opa version

# --- jq 1.7.1: pinned prebuilt binary, sha256-verified against the release's
# --- own sha256sum.txt. jq is a GRADING ENGINE, not a convenience: the
# --- generated tests/ops.py runs every tier-0 structural assert through it,
# --- so it is pinned exactly like opa. Debian bookworm's apt jq is 1.6,
# --- whose behaviour differs from the 1.7.x the host gates run
# --- (../../../docs/gates.md). Same version, URL and checksums in all three
# --- arms, so one jq behaviour grades tier 0 everywhere.
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) JQ_SHA256="5942c9b0934e510ee61eb3e30273f1b3fe2590df93933a93d7c58b81d19c8ff5" ;; \
      arm64) JQ_SHA256="4dd2d8a0661df0b22f1bb9a1f9830f06b6f3b8f7d91211a1ef5d7c4f06a8b4a5" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    URL="https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-${TARGETARCH}"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/jq-linux-${TARGETARCH}"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /usr/local/bin/jq "$URL"; \
    echo "${JQ_SHA256}  /usr/local/bin/jq" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/jq; \
    jq --version

# --- AWS CLI v2 (agent-container parity with arms/awscdk; not required by
# --- preflight.sh, which proves the toolchain works with zero AWS surface) ---
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip"; \
    else \
        CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"; \
    fi && \
    ASSET_MIRROR_URL="$ASSET_MIRROR/$(basename "$CLI_URL")" && \
    { curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1 && CLI_URL="$ASSET_MIRROR_URL" || true; } && \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /tmp/awscliv2.zip "$CLI_URL" && \
    unzip -q /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/aws /tmp/awscliv2.zip

# --- agent working directory (matches arms/awscdk's /app/project convention
# --- — see ../../DECISIONS.md "Agent-container baseline contract") ---
WORKDIR /app/project

# --- minimal preflight app: proves offline `cdktn synth` -> Terraform JSON ---
COPY app/package.json app/package-lock.json ./
RUN npm ci

COPY app/cdktf.json ./cdktf.json
COPY app/tsconfig.json ./tsconfig.json
COPY app/main.ts ./main.ts
# lib/scenario-stack.ts is output_contract.entry_file (specs/SCHEMA.md
# §2.4) -- the agent-owned resource file, split out of main.ts so a normal
# agent solution can fully rewrite it without touching the App/provider
# bootstrap in main.ts -- see ../README.md "Generated-task workspace split".
COPY app/lib ./lib

# --- bake the TypeScript compile once, at image-build time ---
# cdktf.json's app command is now `npx tsc -p tsconfig.json && node main.js`
# (was `npx ts-node main.ts`) and the generated tests/static_tiers.sh runs the
# same `npx tsc -p tsconfig.json` as its own explicit build gate -- see
# ../../generator/gen.py::build_static_tiers_sh and
# ../../docs/ts-runtime-spike2-results.md. tsconfig.json sets
# `"incremental": true` and no `outDir`, so this RUN emits main.js /
# lib/*.js / *.d.ts next to their sources AND a tsconfig.tsbuildinfo, which
# means the agent's FIRST in-trial compile is the warm incremental one
# (~1.9 s / ~989 MB with skipLibCheck) instead of the cold one (~4.4 s /
# ~1416 MB). Emitted JS is never out of date at grading time because every synth
# recompiles by construction (the chained app string above).
#
# Deliberately fatal (no `|| true`): in a generated task this compiles that
# task's own skeleton lib/scenario-stack.ts, so a skeleton that does not
# type-check breaks the image build loudly here rather than surfacing as a
# reward-0.0 "agent failure" in every trial of that scenario.
RUN npx --no-install tsc -p tsconfig.json

# --- pre-warm the hashicorp/aws provider filesystem mirror at the exact
# --- version this arm's own synth output pins. Build-time network only;
# --- nothing after this layer needs network (mirrors arms/hcl-raw's pattern
# --- exactly — see arms/hcl-raw/environment/Dockerfile). ---
WORKDIR /opt/mirror-src
COPY mirror-src/main.tf ./main.tf
RUN terraform providers mirror /opt/terraform-plugin-mirror \
    && rm -rf /opt/mirror-src/.terraform*

COPY terraformrc /etc/terraform.d/cli.tfrc
ENV TF_CLI_CONFIG_FILE=/etc/terraform.d/cli.tfrc \
    TF_IN_AUTOMATION=true \
    TF_INPUT=false

WORKDIR /app/project
COPY preflight.sh /usr/local/bin/preflight.sh
RUN chmod +x /usr/local/bin/preflight.sh

CMD ["/usr/local/bin/preflight.sh"]
