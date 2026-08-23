# cdktn-bench / tasks/anchor/smoke / environment/Dockerfile
#
# Byte-copy of ../../../../arms/awscdk/environment/Dockerfile (the awscdk
# arm's canonical image contract), used unmodified so this dummy task
# validates the Phase 0 exit criterion — "one dummy task runs end-to-end on
# all 3 arm Dockerfiles" — against the arm's real image, not a lighter
# stand-in. aws-bench builds each task's environment/ as its own Docker
# build context (docs/aws-bench-guide.md §5 "Sandboxing"), so a cross-task-dir
# COPY --from isn't available; keep this in sync by hand until the Slice C
# generator templates task environment/ directly from arms/*/environment/.
# Re-copy with `cp -R arms/awscdk/environment/. tasks/anchor/smoke/environment/`
# after any upstream change to the arm contract.
#
# Agent container for the "awscdk" arm: hand-written AWS CDK (TypeScript),
# aws-cdk-lib L2 constructs. Gate = `tsc --noEmit` + `cdk synth` (no deploy).
#
# Pinned toolchain (exact versions — see ../../../../arms/awscdk/README.md
# "Image contract" for the rationale and how to bump them):
#   node        20.20.2   (node:20.20.2-bookworm-slim, digest-pinned below)
#   typescript  7.0.2
#   aws-cdk-lib 2.263.0
#   constructs  10.8.1
#   aws-cdk CLI 2.1135.0  (global install; matches the local devDependency)
#   cfn-guard   3.2.0     (tier-1 policy grader for generator/gen.py's
#                          generated tests/static_tiers.sh when a spec leaves
#                          oracle.awscdk_tier1_engine at its default -- see
#                          ../../../../DECISIONS.md "tier-1 grading tools
#                          installed in every arm image")
#   opa         1.19.0    (the OTHER tier-1 policy grader for this arm, used
#                          when a spec sets `oracle.awscdk_tier1_engine: rego`
#                          -- specs/SCHEMA.md sect 4.5, ROADMAP.md M8. Same
#                          pinned version as arms/hcl-raw and
#                          arms/terraconstructs, so one OPA behaviour grades
#                          all three arms.)
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

FROM node:20.20.2-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

# --- OS packages -------------------------------------------------------
# Same baseline utility set as the upstream dataset's Dockerfile
# (ca-certificates/curl/unzip/less/groff/jq/zip), plus git (Claude Code
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
# excluded python3 from the shared baseline -- see arms/hcl-raw's own
# Dockerfile comment for that arm's version of this same addition
# (installed earlier, for mock-sfn.py, for an unrelated reason) and
# DECISIONS.md's amendment for the full rationale change.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip less groff jq zip git python3 \
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
    curl -fsSL -o /tmp/cfn-guard.tar.gz \
      "https://github.com/aws-cloudformation/cloudformation-guard/releases/download/3.2.0/${CFN_GUARD_ASSET}"; \
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
    curl -fsSL -o /usr/local/bin/opa \
      "https://github.com/open-policy-agent/opa/releases/download/v1.19.0/opa_linux_${TARGETARCH}_static"; \
    echo "${OPA_SHA256}  /usr/local/bin/opa" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/opa; \
    opa version

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
