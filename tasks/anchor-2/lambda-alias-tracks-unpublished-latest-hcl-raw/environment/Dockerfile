# cdktn-bench / hcl-raw arm — hand-written Terraform HCL, no modules.
#
# Ships: a pinned terraform CLI + a pre-warmed hashicorp/aws provider
# filesystem mirror baked into the image, so `terraform init` and
# `terraform validate` need zero network access at trial time. See
# environment/terraformrc and README.md for how the offline guarantee works.
#
# Grading tools installed here, all pinned + sha256-verified, all offline:
#   terraform 1.15.8  — the arm's own toolchain (plan/validate/show)
#   opa       1.19.0  — tier-1 engine (`opa eval -d policy.rego 'data.<pkg>.deny'`)
#   hcl2json  0.6.9   — tier-1 HCL pre-parse, 4.1 MB. Turns the `*.tf` in
#                       the working directory into JSON so a Rego policy can
#                       resolve a `local.` symbol to the resource attribute
#                       it actually names: `terraform show -json` emits no
#                       `locals` at all, so a plan's reference list dead-ends
#                       on `local.x` and an oracle grading a dedicated
#                       single-ARN argument slot is blind on that hop. See
#                       ../../../docs/design/conftest-hcl-traversal-spike.md.
#                       NOT conftest: conftest EMBEDS this exact parser
#                       (`github.com/tmccombs/hcl2json`) and produces
#                       byte-identical output at 68 MB instead of 4.1 MB, and
#                       adopting it as the ENGINE would reshape `input` for
#                       every existing Rego rule in the repo.
#   aws CLI v2        — agent-container parity only; no grading path uses it
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

# --- hcl2json (tmccombs/hcl2json) 0.6.9: static pinned binary, sha256-
# --- verified. UNLIKE the opa pin above, this one CAN be cross-checked
# --- against an upstream manifest — the project publishes
# --- hcl2json_0.6.9_checksums.txt alongside the release, and both hashes
# --- below were taken from it (and re-verified against the bytes actually
# --- downloaded), so the caveat in the opa block does not apply here.
# ---
# --- The binaries are published UNARCHIVED, so this is a straight
# --- curl + `sha256sum -c` with no unpack step — the same shape as the opa
# --- block, one step shorter than terraform's zip.
# ---
# --- WHAT IT IS FOR: `generator/gen.py::build_hcl_merge_block` emits a step
# --- into this arm's tests/static_tiers.sh (only for a spec that opts in via
# --- `oracle.hcl_traversal`) that runs `hcl2json` over every `*.tf` in
# --- /app/project and merges the result into the plan JSON under one
# --- reserved key before `opa eval` runs. The ENGINE stays opa and the
# --- reward contract is unchanged. It does no I/O beyond reading the file it
# --- is handed — no network at trial time, same as opa.
# ---
# --- NOT INSTALLED IN THE OTHER TWO ARMS, deliberately: awscdk resolves TS
# --- variables at synth time and the CloudFormation template names its
# --- referent in an `Fn::GetAtt`; cdktn does the same and emits no `locals`
# --- block at all (verified across five real cdk.tf.json documents). Neither
# --- arm has anything left to resolve, so neither pays the 4.1 MB.
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) HCL2JSON_SHA256="b609e37094948c0b77cd8c6c0baaf8af2bd168c685c6e3334d671cc9692c34a5" ;; \
      arm64) HCL2JSON_SHA256="cb2ccf59a830829fe122e8dfb85d6ef2500aceda5af45a7c1052a4d2c46541f9" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/hcl2json \
      "https://github.com/tmccombs/hcl2json/releases/download/v0.6.9/hcl2json_linux_${TARGETARCH}"; \
    echo "${HCL2JSON_SHA256}  /usr/local/bin/hcl2json" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/hcl2json; \
    hcl2json -version

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
# and provider.tf (provider bootstrap: pinned hashicorp/aws + a bare
# provider "aws" resolved by the ambient credential chain, NOT
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
# fully rewrites from scratch. Keeping the bootstrap in a file the generator
# never treats as entry_file makes it structurally impossible for such a
# rewrite to delete the provider block — see ../../README.md
# "Generated-task workspace split".
WORKDIR /app/project
COPY workspace/provider.tf ./provider.tf
COPY workspace/main.tf ./main.tf
CMD ["/bin/bash"]
