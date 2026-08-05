# cdktn-bench / arms/awscdk / environment/Dockerfile
#
# Agent container for the "awscdk" arm: hand-written AWS CDK (TypeScript),
# aws-cdk-lib L2 constructs. Gate = `tsc --noEmit` + `cdk synth` (no deploy).
#
# Pinned toolchain (exact versions — see ../README.md "Image contract" for the
# rationale and how to bump them):
#   node        20.20.2   (node:20.20.2-bookworm-slim, digest-pinned below)
#   typescript  7.0.2
#   aws-cdk-lib 2.263.0
#   constructs  10.8.1
#   aws-cdk CLI 2.1135.0  (global install; matches the local devDependency)
#
# Mirrors the aws-bench-datasets environment/Dockerfile convention
# (docs/aws-bench-guide.md §5, aws-bench-datasets-guide.md §2): a plain,
# non-root-unaware base image with AWS CLI v2 baked in, WORKDIR under /app.
# Never COPY from tests/ or solution/ — see aws-bench-datasets-guide.md §6b.

FROM node:20.20.2-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

# --- OS packages -------------------------------------------------------
# Same baseline utility set as the upstream dataset's Dockerfile
# (ca-certificates/curl/unzip/less/groff/jq/zip), plus git (Claude Code
# harness installs/uses it per-trial per aws-bench-guide.md §5).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip less groff jq zip git \
    && rm -rf /var/lib/apt/lists/*

# --- AWS CLI v2 ----------------------------------------------------------
# Not required by preflight.sh (which proves the CDK toolchain works fully
# offline) but included for parity with the upstream agent-container
# convention and for later task slices whose instructions may need it.
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

# --- npm / CDK behavior: no network needed at synth time ----------------
# CDK_DISABLE_VERSION_CHECK stops `cdk` from phoning home to npm for a
# newer-CLI notice; NPM_CONFIG_UPDATE_NOTIFIER/NPM_CONFIG_FUND silence npm's
# own network-touching nags. None of these affect synth correctness.
ENV CDK_DISABLE_VERSION_CHECK=true \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

# --- aws-cdk CLI, global install (exact version, matches workspace's
# devDependency so `cdk` on PATH and `npx cdk` inside the workspace agree) --
RUN npm install -g aws-cdk@2.1135.0 && cdk --version

# --- Workspace scaffold ---------------------------------------------------
# /app/project is the agent's working directory: a starting CDK TypeScript
# project with pinned dependencies pre-installed via `npm ci` at build time
# (network only happens here, at image-build time — never at trial/preflight
# time). Slice C's generator overwrites lib/ per scenario; bin/app.ts and
# lib/example-stack.ts stay as the offline-synth smoke test consumed by
# preflight.sh.
WORKDIR /app/project

COPY workspace/package.json workspace/package-lock.json ./
RUN npm ci

COPY workspace/tsconfig.json workspace/cdk.json ./
COPY workspace/bin ./bin
COPY workspace/lib ./lib

# --- Preflight -------------------------------------------------------
COPY preflight.sh /usr/local/bin/preflight.sh
RUN chmod +x /usr/local/bin/preflight.sh

CMD ["/bin/bash"]
