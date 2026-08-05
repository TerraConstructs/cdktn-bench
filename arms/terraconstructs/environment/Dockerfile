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
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      gnupg \
      unzip \
      ca-certificates \
      jq \
      git \
      less \
    && curl -fsSL https://apt.releases.hashicorp.com/gpg -o /tmp/hashicorp.gpg \
    && gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg /tmp/hashicorp.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
      > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends terraform=${TERRAFORM_VERSION}-* \
    && rm -rf /var/lib/apt/lists/* /tmp/hashicorp.gpg

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
