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
#
# python3 (stdlib only, no pip package ever installed) is NOT part of that
# shared baseline -- it exists solely to run workspace/mock-sfn.py, this
# arm's own offline-plan fixture for `aws_sfn_state_machine`'s
# CustomizeDiff-triggered `states:ValidateStateMachineDefinition` call (see
# workspace/provider.tf's own header comment and mock-sfn.py's docstring
# for the full mechanism -- the same class of gap arms/terraconstructs'
# Node-based mock-sts.js fixes for that arm's `data "aws_caller_identity"`
# call). Kept out of the grading-tool baseline deliberately: structural
# assertions still run entirely on jq (generator/jsonpath_jq.py's own
# docstring, "no Python, no jsonpath-ng" -- unaffected by this addition).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gnupg \
      unzip \
      jq \
      git \
      less \
      python3 \
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

# --- opa (Open Policy Agent) 1.19.0: static pinned binary, sha256-verified
# --- against what was actually downloaded at pin time (opa doesn't publish
# --- a signed SHA256SUMS file the way terraform does, so this hash is
# --- pinned from a verified-good download rather than cross-checked against
# --- an upstream manifest -- see ../../../DECISIONS.md "tier-1 grading
# --- tools installed in every arm image"). This is the tool
# --- generator/gen.py's generated tests/static_tiers.sh runs for this arm's
# --- tier-1 (`opa eval -d policy.rego 'data.<pkg>.deny' < plan.json`).
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
#
# --- Workspace scaffold ---------------------------------------------------
# Bakes the starter main.tf (resource-only skeleton, agent-owned entry_file)
# and provider.tf (offline provider/skip_*/dummy-credential bootstrap, NOT
# agent-owned) into the agent's working directory, mirroring how
# arms/awscdk COPYs workspace/lib and arms/terraconstructs COPYs app/main.ts
# into /app/project (see ../../DECISIONS.md "Agent-container baseline
# contract"). Added alongside the Slice C generator (specs/SCHEMA.md §2.4's
# hcl_raw output_contract row): the generator overwrites workspace/main.tf
# per scenario; nothing else about this Dockerfile (including provider.tf)
# changes per task.
#
# provider.tf is COPY'd as its own file, separately from main.tf, because
# main.tf is output_contract.entry_file — the file a normal agent solution
# fully rewrites from scratch. When the offline provider bootstrap used to
# live at the top of main.tf, a correct-but-bare agent rewrite silently
# deleted the skip_*/dummy-credential fixture lines and `terraform plan`
# failed with "No valid credential sources found" even for a correct
# solution — see ../../README.md "Generated-task workspace split".
WORKDIR /app/project
COPY workspace/provider.tf ./provider.tf
COPY workspace/mock-sfn.py ./mock-sfn.py
COPY workspace/main.tf ./main.tf

# --- Seeded workspace reference inputs (generator-appended) ---------------
# One COPY per file generator/gen.py wrote into this task's
# environment/workspace/ that the arm-level COPYs above do not already
# cover — spec `seeded_files` (specs/SCHEMA.md §2.5). Without these the files
# exist only in the build context and on the host (where the host-side gates
# read them directly), never inside the agent's container, while instruction.md
# tells the agent to read them: docs/design/poisoned-workspace-design.md §9-B1.
# Named file-by-file, never a blanket `COPY workspace/ ./`, to preserve
# the arm Dockerfiles' deliberate named-COPY discipline. Generated — regenerate
# with `make gen` / `make gen-all`, never hand-edit (SCHEMA.md §0).
WORKDIR /app/project
COPY workspace/lambda/placeholder.zip ./lambda/placeholder.zip
COPY workspace/openapi/widgets-api.json ./openapi/widgets-api.json

CMD ["/bin/bash"]
