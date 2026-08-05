# cdktn-bench / hcl-raw arm — hand-written Terraform HCL, no modules.
#
# Ships: a pinned terraform CLI + a pre-warmed hashicorp/aws provider
# filesystem mirror baked into the image, so `terraform init` and
# `terraform validate` need zero network access at trial time. See
# environment/terraformrc and README.md for how the offline guarantee works.
#
# Base image is digest-pinned (not just tag-pinned) so a rebuild months from
# now can't silently swap the OS layer under an already-measured toolchain —
# see ../../DECISIONS.md "Pinning standard". Re-pin by running
# `docker pull debian:bookworm-slim && docker inspect --format='{{index
# .RepoDigests 0}}' debian:bookworm-slim` and updating both the tag and the
# digest together.
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241

ARG TERRAFORM_VERSION=1.15.8
ARG AWS_PROVIDER_VERSION=6.58.0
# NOTE: deliberately no default value here. TARGETARCH is one of BuildKit's
# predefined platform ARGs, auto-populated from --platform (or the builder's
# native platform if --platform is omitted). Giving it a literal default
# (e.g. "=amd64") would SHADOW that auto-injected value — a well-known
# Docker/BuildKit footgun — and silently install the wrong-arch terraform
# binary on an arm64 build host. Leave it bare.
ARG TARGETARCH

LABEL org.opencontainers.image.title="cdktn-bench hcl-raw" \
      org.opencontainers.image.description="Hand-written Terraform HCL arm: terraform CLI + offline hashicorp/aws provider mirror" \
      cdktn-bench.arm="hcl-raw" \
      cdktn-bench.terraform.version="${TERRAFORM_VERSION}" \
      cdktn-bench.aws-provider.version="${AWS_PROVIDER_VERSION}"

# Baseline agent-container utility set shared with arms/awscdk and
# arms/terraconstructs — see ../../DECISIONS.md "Agent-container baseline
# contract". gnupg is needed for the HashiCorp apt-key step below.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gnupg \
      unzip \
      jq \
      git \
      less \
    && rm -rf /var/lib/apt/lists/*

# --- AWS CLI v2 (agent-container parity with arms/awscdk/arms/terraconstructs;
# --- not required by preflight.sh, which proves the toolchain works with zero
# --- AWS surface area) ---
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

# --- terraform CLI: pinned version, downloaded + sha256-verified against
# --- HashiCorp's published SHA256SUMS for this release (hardcoded below, not
# --- fetched at build time, so a compromised releases.hashicorp.com response
# --- would be caught rather than trusted).
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) TF_SHA256="d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d" ;; \
      arm64) TF_SHA256="8891e9dcedc9e3b8950bc6af9d4d8af1f4cfade3062f53b9dc403a89f6ce8c9c" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/terraform.zip \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip"; \
    echo "${TF_SHA256}  /tmp/terraform.zip" | sha256sum -c -; \
    unzip -q /tmp/terraform.zip -d /usr/local/bin; \
    chmod 0755 /usr/local/bin/terraform; \
    rm -f /tmp/terraform.zip

# --- pre-warm the hashicorp/aws provider filesystem mirror. This step needs
# --- network (image build time only); nothing after this layer does.
WORKDIR /opt/mirror-src
COPY mirror-src/main.tf ./main.tf
RUN terraform providers mirror /opt/terraform-plugin-mirror \
    && rm -rf /opt/mirror-src/.terraform*

# --- CLI config: filesystem_mirror only, no direct{} network fallback for
# --- ANY provider — a provider missing from the mirror fails loudly instead
# --- of silently reaching out. TF_CLI_CONFIG_FILE makes this the default for
# --- every `terraform` invocation in the container, agent trials included.
COPY terraformrc /etc/terraform.d/cli.tfrc
ENV TF_CLI_CONFIG_FILE=/etc/terraform.d/cli.tfrc \
    TF_IN_AUTOMATION=true \
    TF_INPUT=false \
    CHECKPOINT_DISABLE=1

# --- preflight fixture + script, baked into the image so `preflight.sh` runs
# --- standalone with no extra mounts.
WORKDIR /opt/preflight
COPY fixtures/ ./fixtures/
COPY preflight.sh ./preflight.sh
RUN chmod +x ./preflight.sh

# Agent working directory — matches arms/awscdk's /app/project and
# arms/terraconstructs' /app/project convention (see ../../DECISIONS.md
# "Agent-container baseline contract"; was /workspace, unique to this arm).
WORKDIR /app/project
CMD ["/bin/bash"]
