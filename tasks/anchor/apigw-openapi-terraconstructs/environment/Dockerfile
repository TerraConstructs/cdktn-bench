# arms/terraconstructs — AWSCDK-style L2 constructs (terraconstructs) synthesizing
# Terraform via cdktn (the community fork of cdktf, formerly "CDK Terrain").
#
# Toolchain: Node 20 + TypeScript + terraconstructs + cdktn/cdktn-cli + the
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
FROM node:20.20.2-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS base

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
# terraform is used by the arm's tests/test.sh oracle (`terraform validate` +
# `terraform plan`, no apply — see docs/aws-bench-guide.md §7c) AND by this
# image's own preflight, which now exercises offline `cdktn synth` ->
# `terraform init` -> `terraform validate` end-to-end (see "provider mirror"
# below). jq/git/curl/unzip match the common agent-container baseline shared
# with arms/awscdk and arms/hcl-raw — see ../../DECISIONS.md "Agent-container
# baseline contract".
# python3 (stdlib only, no pip package ever installed): added fix-round-3
# (benchmark-integrity review finding G2, 2026-08-07) -- same rationale as
# arms/awscdk/environment/Dockerfile's identical addition: this arm's
# generated tests/test.sh invokes `python3 "$DIR/live_check.py"` for any
# spec with verifier.live_check.enabled: true, and this image previously
# had no python3 at all, silently downgrading a perfect live-checked
# solution to reward 0.0 via a shell "command not found" misread as a
# legitimate not_verifiable live-check outcome. Amends DECISIONS.md
# "Agent-container baseline contract".
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      unzip \
      ca-certificates \
      jq \
      git \
      less \
      python3 \
    && curl -fsSL https://apt.releases.hashicorp.com/gpg -o /tmp/hashicorp.gpg \
    && gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg /tmp/hashicorp.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
      > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends terraform=${TERRAFORM_VERSION}-* \
    && rm -rf /var/lib/apt/lists/* /tmp/hashicorp.gpg

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
    curl -fsSL -o /usr/local/bin/opa \
      "https://github.com/open-policy-agent/opa/releases/download/v1.19.0/opa_linux_${TARGETARCH}_static"; \
    echo "${OPA_SHA256}  /usr/local/bin/opa" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/opa; \
    opa version

# --- AWS CLI v2 (agent-container parity with arms/awscdk; not required by
# --- preflight.sh, which proves the toolchain works with zero AWS surface) ---
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip"; \
    else \
        CLI_URL="https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"; \
    fi && \
    curl -sSL "$CLI_URL" -o /tmp/awscliv2.zip && \
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

# --- Seeded workspace reference inputs (generator-appended) ---------------
# One COPY per file generator/gen.py wrote into this task's
# environment/app/ that the arm-level COPYs above do not already
# cover — spec `seeded_files` (specs/SCHEMA.md §2.5). Without these the files
# exist only in the build context and on the host (where the host-side gates
# read them directly), never inside the agent's container, while instruction.md
# tells the agent to read them.
# Named file-by-file, never a blanket `COPY app/ ./`, to preserve
# the arm Dockerfiles' deliberate named-COPY discipline. Generated — regenerate
# with `make gen` / `make gen-all`, never hand-edit (SCHEMA.md §0).
WORKDIR /app/project
COPY app/lambda/placeholder.zip ./lambda/placeholder.zip
COPY app/openapi/widgets-api.json ./openapi/widgets-api.json

CMD ["/usr/local/bin/preflight.sh"]
