# cdktn-bench / arms/awscdk / environment/Dockerfile
#
# Agent container for the "awscdk" arm: hand-written AWS CDK (TypeScript),
# aws-cdk-lib L2 constructs. Gate = `tsc --noEmit` + `cdk synth` (no deploy).
#
# Pinned toolchain (exact versions — see ../README.md "Image contract" for the
# rationale and how to bump them):
#   node        22.23.2   (node:22.23.2-bookworm-slim, digest-pinned below)
#   typescript  7.0.2
#   aws-cdk-lib 2.263.0
#   constructs  10.8.1
#   aws-cdk CLI 2.1135.0  (global install; matches the local devDependency)
#   cfn-guard   3.2.0     (tier-1 policy grader for generator/gen.py's
#                          generated tests/static_tiers.sh when a spec leaves
#                          oracle.awscdk_tier1_engine at its default -- see
#                          ../../../DECISIONS.md "tier-1 grading tools
#                          installed in every arm image")
#   opa         1.19.0    (the OTHER tier-1 policy grader for this arm, used
#                          when a spec sets `oracle.awscdk_tier1_engine: rego`
#                          -- specs/SCHEMA.md sect 4.5, ROADMAP.md M8. Same
#                          pinned version as arms/hcl-raw and
#                          arms/terraconstructs, so one OPA behaviour grades
#                          all three arms.)
#   jq          1.7.1     (tier-0 grading engine -- the generated tests/ops.py
#                          runs every structural assert through it. Same pin
#                          in all three arms; apt's bookworm jq is 1.6.)
#
# Tuned-equipping tools, pinned the same way and installed at build time so no
# resolve happens at trial time. They are prompt surface, never a grading path;
# equipping/levels/awscdk.tuned*.yaml declares them and the image digest (in the
# equipping hash) covers these pins:
#   uv          0.12.18   (installs the server below into /opt/uv-tools)
#   AWS Docs MCP 1.2.1    (`awslabs.aws-documentation-mcp-server` on PATH)
# The level also declares AWS IaC MCP 1.0.26, which is NOT installed: guardpycfn
# publishes no linux/aarch64 wheel, so on this host arch it only builds through a
# Rust toolchain. The step below says what that would cost.
#
# BOTH tier-1 graders ship here on purpose. cfn-guard 3.2.0 cannot express a
# cross-resource logical-id join, so it cannot be the grading AUTHORITY in a
# cross-arm comparison (DECISIONS.md Amendment 29 sect 4 makes equal-strictness
# grading binding; ROADMAP.md M8 has the executed proof). It is nevertheless
# RETAINED as a real arm capability -- a tool an awscdk team actually has --
# and remains the default engine, so removing it would break every existing
# spec. Which binary a given trial invokes is decided per-scenario by
# oracle.awscdk_tier1_engine, not by what is installed.
#
# Mirrors the aws-bench-datasets environment/Dockerfile convention
# (docs/aws-bench-guide.md §5, aws-bench-datasets-guide.md §2): a plain,
# non-root-unaware base image with AWS CLI v2 baked in, WORKDIR under /app.
# Never COPY from tests/ or solution/ — see aws-bench-datasets-guide.md §6b.

FROM node:22.23.2-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
# --- OS packages -------------------------------------------------------
# Same baseline utility set as the upstream dataset's Dockerfile
# (ca-certificates/curl/unzip/less/groff/zip; jq comes from the pinned
# binary below, not apt), plus git (Claude Code
# harness installs/uses it per-trial per aws-bench-guide.md §5).
#
# python3 (stdlib only, no pip package ever installed): added fix-round-3
# (benchmark-integrity review finding G2, 2026-08-07) -- this arm's
# generated tests/test.sh (generator/gen.py::build_test_sh) invokes
# `python3 "$DIR/live_check.py"` whenever a spec sets
# verifier.live_check.enabled: true. Before
# this line, python3 did not exist in this image at all: the interpreter
# invocation failed with "command not found", and that shell error text
# landed in live_check-result.json (stdout+stderr were merged) where
# gen.py's own gating logic read it as an innocuous "not_verifiable"
# outcome -- silently downgrading a PERFECT solution to reward 0.0 on
# every live-checked trial on this arm. Amends DECISIONS.md
# "Agent-container baseline contract", which previously (deliberately)
# excluded python3 from the shared baseline.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip less groff zip git python3 \
    && rm -rf /var/lib/apt/lists/*

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
    ASSET_MIRROR_URL="$ASSET_MIRROR/$(basename "$CLI_URL")" && \
    { curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1 && CLI_URL="$ASSET_MIRROR_URL" || true; } && \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /tmp/awscliv2.zip "$CLI_URL" && \
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

# --- cfn-guard 3.2.0, pinned prebuilt binary + sha256-verified (same
# --- "hardcode the checksum, don't trust the download at build time"
# --- pattern as arms/hcl-raw's terraform install) -- this is the tool
# --- generator/gen.py's generated tests/static_tiers.sh runs for this
# --- arm's tier-1 (`cfn-guard validate --data ... --rules policy.guard`).
# --- Previously absent from every arm image, which meant tier-1 always
# --- reported SKIPPED (now TOOL_MISSING, a hard verifier failure per
# --- static_tiers.sh -- see ../../../DECISIONS.md) rather than actually
# --- grading anything.
ARG TARGETARCH
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) CFN_GUARD_ASSET="cfn-guard-v3-x86_64-linux-latest.tar.gz"; \
             CFN_GUARD_SHA256="c78f7a1a6c2674f7edbf0ebdc0590126487a14b103e434aea31205a4d1034d21" ;; \
      arm64) CFN_GUARD_ASSET="cfn-guard-v3-aarch64-linux-latest.tar.gz"; \
             CFN_GUARD_SHA256="d562e14831794a4859782f5609186970373e8e0a049fbded2c01612d2dcdb087" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    URL="https://github.com/aws-cloudformation/cloudformation-guard/releases/download/3.2.0/${CFN_GUARD_ASSET}"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/${CFN_GUARD_ASSET}"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /tmp/cfn-guard.tar.gz "$URL"; \
    echo "${CFN_GUARD_SHA256}  /tmp/cfn-guard.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/cfn-guard.tar.gz -C /tmp; \
    install -m 0755 /tmp/cfn-guard-v3-*-linux-latest/cfn-guard /usr/local/bin/cfn-guard; \
    rm -rf /tmp/cfn-guard.tar.gz /tmp/cfn-guard-v3-*-linux-latest; \
    cfn-guard --version

# --- opa (Open Policy Agent) 1.19.0: static pinned binary, sha256-verified
# --- against what was actually downloaded at pin time (opa doesn't publish
# --- a signed SHA256SUMS file the way terraform does, so this hash is
# --- pinned from a verified-good download rather than cross-checked against
# --- an upstream manifest -- see ../../../DECISIONS.md "tier-1 grading
# --- tools installed in every arm image"). Byte-for-byte the same version,
# --- URL and checksums as arms/hcl-raw/environment/Dockerfile and
# --- arms/terraconstructs/environment/Dockerfile install: ROADMAP.md M8
# --- makes OPA the cross-arm grading engine, which is only a parity claim
# --- if all three arms run the SAME opa build.
# --- This is the tool generator/gen.py's generated tests/static_tiers.sh
# --- runs for this arm's tier-1 when the spec sets
# --- `oracle.awscdk_tier1_engine: rego` (specs/SCHEMA.md sect 4.5):
# --- `opa eval -d policy.rego 'data.<pkg>.deny' < ScenarioStack.template.json`
# --- -- same command as the TF arms, a CloudFormation template as `input`
# --- instead of `terraform show -json` plan JSON. Absent this binary, such a
# --- spec's tier-1 reports TOOL_MISSING, which is a hard verifier failure
# --- (reward 0.0), never a silent pass.
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

# --- uv: the installer that puts the pinned MCP server below into this image.
# --- Pinned tarball + hardcoded sha256, fetched through the same mirror probe as
# --- every other asset here (docs/asset-mirror.md). The checksum is the one
# --- astral-sh publishes beside the release asset
# --- (uv-<triple>-unknown-linux-gnu.tar.gz.sha256), re-verified against the
# --- bytes downloaded, so this pin is cross-checked upstream the way terraform's
# --- and hcl2json's are and unlike opa's.
ARG UV_VERSION=0.12.18
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) UV_TRIPLE="x86_64-unknown-linux-gnu"; UV_SHA256="89eadd7c76fc063887959510d5ba0ab1264dfd5f1143b925ddb73021a40acf16" ;; \
      arm64) UV_TRIPLE="aarch64-unknown-linux-gnu"; UV_SHA256="afb6291f3f0a6b4521fc67b947822506c41dde5b60d2189dd8f3695b2ac8c9e7" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_TRIPLE}.tar.gz"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/uv-${UV_TRIPLE}.tar.gz"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /tmp/uv.tar.gz "$URL"; \
    echo "${UV_SHA256}  /tmp/uv.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/uv.tar.gz -C /tmp; \
    install -m 0755 "/tmp/uv-${UV_TRIPLE}/uv" /usr/local/bin/uv; \
    install -m 0755 "/tmp/uv-${UV_TRIPLE}/uvx" /usr/local/bin/uvx; \
    rm -rf /tmp/uv.tar.gz "/tmp/uv-${UV_TRIPLE}"; \
    uv --version

# --- where `uv tool install` lands, and the interpreter it is allowed to use.
# --- UV_TOOL_BIN_DIR is on PATH, so the console script each server's wheel
# --- declares IS the command equipping/levels/<arm>.tuned*.yaml declares and
# --- gates/tuned_equipping.py resolves. UV_PYTHON_DOWNLOADS=never forbids a
# --- python-build-standalone fetch, which would be an unpinned interpreter: both
# --- servers floor at Python >=3.10 and this image's apt python3 is 3.11.
ENV UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_PYTHON_DOWNLOADS=never

# --- AWS Docs MCP server, a `stdio` server this arm's tuned equipping declares
# --- (equipping/levels/*.tuned*.yaml, pinned in equipping/MANIFEST.json).
# --- Installed at BUILD time and pinned by ARG so the image digest covers the
# --- version; never resolved by `uvx` at launch, because claude-code logs an MCP
# --- server it cannot start and carries on, so a trial-time fetch failure would
# --- publish a tuned row whose container had no server.
ARG AWS_DOCUMENTATION_MCP_VERSION=1.2.1
RUN set -eu; \
    uv tool install --no-cache --python /usr/bin/python3 \
      "awslabs.aws-documentation-mcp-server==${AWS_DOCUMENTATION_MCP_VERSION}"; \
    command -v awslabs.aws-documentation-mcp-server

# --- AWS IaC MCP server, the second `stdio` server the awscdk tuned level
# --- declares (equipping/levels/awscdk.tuned*.yaml) -- NOT INSTALLED, and the
# --- reason is upstream, not a choice: 1.0.26 imports `guardpycfn` at module
# --- load (tools/cloudformation_compliance_checker.py), and guardpycfn 0.1.0
# --- publishes wheels for macos-arm64, manylinux x86_64 and win_amd64 only. On
# --- a linux/arm64 build -- the bench's own host arch -- uv therefore builds it
# --- from its Rust sdist, maturin finds no cargo and downloads rustup mid-build.
# --- Installing it here would mean an unpinned Rust toolchain plus a crates.io
# --- crate tree inside a measured image, which is a registered-artifact decision
# --- and not one this file may make. `make equipping-preflight` stays red for
# --- the two awscdk tuned rows until it is taken; ROADMAP.md M2 phase 4 and
# --- DECISIONS.md Amendment 51 carry the options.

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

# --- bake the TypeScript compile once, at image-build time ---
# PARITY with arms/terraconstructs (added 2026-08-26). Both TS arms run
# `npx tsc -p tsconfig.json && node ...` as their app command (cdk.json here,
# cdktf.json there) -- neither uses ts-node any more. terraconstructs has baked
# this compile since the memory finding (../README.md "Memory finding",
# ../../DECISIONS.md "Memory floor for tsc-heavy arms"); awscdk never had it
# backported, so this arm paid a COLD full type-check on EVERY `cdk synth` /
# `cdk deploy`, however many a given task performs.
#
# AGENT-READABLE: the whole environment/ tree is COPYed into the image, so no
# comment here may name a scenario mechanism. Enforced by
# generator/tests/test_workspace_seed.py MECHANISM_PATTERNS; an arm-asymmetric
# leak is the worse case, since it biases the cross-arm comparison directly.
#
# tsconfig.json now sets `"incremental": true` and has no `outDir`, so this RUN
# emits bin/*.js / lib/*.js next to their sources AND a tsconfig.tsbuildinfo --
# the agent's FIRST in-trial compile is the warm incremental one instead of the
# cold one. Emitted JS is never out of date at grading time because every synth
# recompiles by construction (the chained app string in cdk.json).
#
# Deliberately fatal (no `|| true`): in a generated task the COPY above brings
# that task's own skeleton lib/scenario-stack.ts, so a skeleton that does not
# type-check breaks the image build loudly here rather than surfacing as a
# reward-0.0 "agent failure" in every trial of that scenario.
RUN npx --no-install tsc -p tsconfig.json

# --- Preflight -------------------------------------------------------
COPY preflight.sh /usr/local/bin/preflight.sh
RUN chmod +x /usr/local/bin/preflight.sh

# --- Seeded workspace reference inputs (generator-appended) ---------------
# One COPY per file generator/gen.py wrote into this task's
# environment/workspace/ that the arm-level COPYs above do not already
# cover — spec `seeded_files` (specs/SCHEMA.md §2.5). Without these the files
# exist only in the build context and on the host (where the host-side gates
# read them directly), never inside the agent's container, while instruction.md
# tells the agent to read them.
# Named file-by-file, never a blanket `COPY workspace/ ./`, to preserve
# the arm Dockerfiles' deliberate named-COPY discipline. Generated — regenerate
# with `make gen` / `make gen-all`, never hand-edit (SCHEMA.md §0).
WORKDIR /app/project
COPY workspace/lambda/placeholder.zip ./lambda/placeholder.zip
COPY workspace/openapi/widgets-api.json ./openapi/widgets-api.json

CMD ["/bin/bash"]
