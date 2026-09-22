# cdktn-bench / hcl-modules arm — Terraform composed from `terraform-aws-modules`
# registry modules.
#
# Derived from arms/hcl-raw/environment/Dockerfile: same digest-pinned base, same
# pinned terraform/opa/jq/hcl2json/AWS-CLI fetches with the same
# probe-then-fallback and sha256 pins, same /app/project workspace contract. The
# two Terraform arms must differ ONLY in whether the agent composes registry
# modules, or a cross-arm score difference could be a toolchain difference.
#
# What this arm ADDS, all of it DECISIONS.md Amendment 46 (the module arm's
# delivery decisions) and explained at the step that builds it:
#   /opt/terraform-modules   the vendored, pruned module tree + manifest.json,
#                            COPYed from the build context, verified at build
#   /opt/tf-registry/        the loopback registry the sidecar runs (46 (a):
#                            sidecar and agent are one image, two commands)
#   terraformrc host block   makes a registry module source resolve to that
#                            sidecar with no discovery request and no DNS
#   eight mirrored providers the union the vendored tree declares, not just aws
#
# Base image is digest-pinned (not just tag-pinned) so a rebuild months from
# now can't silently swap the OS layer under an already-measured toolchain —
# see ../../DECISIONS.md "Pinning standard". Re-pin by running
# `docker pull debian:bookworm-slim && docker inspect --format='{{index
# .RepoDigests 0}}' debian:bookworm-slim` and updating both the tag and the
# digest together.
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241
ARG TERRAFORM_VERSION=1.15.8
ARG AWS_PROVIDER_VERSION=6.66.0
# NOTE: deliberately no default value here. TARGETARCH is one of BuildKit's
# predefined platform ARGs, auto-populated from --platform (or the builder's
# native platform if --platform is omitted). Giving it a literal default
# (e.g. "=amd64") would SHADOW that auto-injected value — a well-known
# Docker/BuildKit footgun — and silently install the wrong-arch terraform
# binary on an arm64 build host. Leave it bare.
ARG TARGETARCH

LABEL org.opencontainers.image.title="cdktn-bench hcl-modules" \
      org.opencontainers.image.description="Terraform registry-module arm: terraform CLI, offline provider mirror, vendored terraform-aws-modules tree and its loopback registry responder" \
      cdktn-bench.arm="hcl-modules" \
      cdktn-bench.terraform.version="${TERRAFORM_VERSION}" \
      cdktn-bench.aws-provider.version="${AWS_PROVIDER_VERSION}"

# Baseline agent-container utility set shared with arms/awscdk,
# arms/terraconstructs and arms/hcl-raw — see ../../DECISIONS.md
# "Agent-container baseline contract". gnupg is needed for the HashiCorp
# apt-key step below. python3 is load-bearing in THIS arm rather than
# incidental: the registry sidecar (/opt/tf-registry/responder.py) and the
# build-time manifest verification below are both stdlib Python and this is
# the interpreter they run on.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gnupg \
      unzip \
      git \
      less \
      python3 \
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

# --- AWS CLI v2 (agent-container parity with arms/awscdk/arms/terraconstructs;
# --- not required by preflight.sh, which proves the toolchain works with zero
# --- AWS surface area) ---
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
    URL="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /tmp/terraform.zip "$URL"; \
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
    URL="https://github.com/tmccombs/hcl2json/releases/download/v0.6.9/hcl2json_linux_${TARGETARCH}"; \
    ASSET_MIRROR_URL="$ASSET_MIRROR/hcl2json_linux_${TARGETARCH}"; \
    if curl -fsI --connect-timeout 2 --max-time 5 "$ASSET_MIRROR_URL" >/dev/null 2>&1; then URL="$ASSET_MIRROR_URL"; fi; \
    curl -fsSL --http1.1 --retry 5 --retry-all-errors -o /usr/local/bin/hcl2json "$URL"; \
    echo "${HCL2JSON_SHA256}  /usr/local/bin/hcl2json" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/hcl2json; \
    hcl2json -version

# --- pre-warm the provider filesystem mirror. This step needs network (image
# --- build time only); nothing after this layer does. mirror-src/main.tf
# --- declares the UNION of every provider the vendored module tree names, not
# --- just hashicorp/aws: `terraform init` resolves a module's whole tree, so a
# --- provider only a never-called submodule declares still has to be present.
WORKDIR /opt/mirror-src
COPY mirror-src/main.tf ./main.tf
RUN terraform providers mirror /opt/terraform-plugin-mirror \
    && rm -rf /opt/mirror-src/.terraform*

# --- the vendored module tree + its integrity check.
# ---
# --- READABLE BY THE AGENT, and that is not an oversight: Amendment 46 (c)'s
# --- first half ("the tree is unreadable to the agent user") is VOID as built.
# --- No arm Dockerfile declares a `USER` and generator/gen.py REFUSES one for a
# --- seeded spec, because Harbor's ScriptRunner prepares /logs/pre_invoke as
# --- root, so the agent is uid 0 and file modes hide nothing from it. The half
# --- that carries (c) is the second: the verifier denies any
# --- .terraform/modules/modules.json entry whose Source is not a registry
# --- source, so reading this tree tells an agent what exists but copying it in
# --- is not a solution. That deny lands with the pilot policies in phase 5.
# ---
# --- NO MODULE BYTES ARE FETCHED HERE. ./modules/ is committed in this build
# --- context (scripts/vendor_modules.py writes it; the owner re-runs that on a
# --- version bump), so this COPY is the only way a module reaches the image
# --- and `docker build --network none` would still produce this layer.
# ---
# --- ./vendor_modules.py is a byte copy of scripts/vendor_modules.py, present
# --- because a Docker build context cannot reach above itself;
# --- generator/tests/test_hcl_modules_image.py fails if the two drift. Only
# --- `--verify` runs here, and it is stdlib-only and offline by construction.
# --- It re-hashes every file against manifest.json and fails on a changed
# --- byte, a missing file, an extra file or an extra directory, so a tree that
# --- was edited in place — or a manifest that no longer describes it — stops
# --- the build instead of shipping.
COPY modules/ /opt/terraform-modules/
COPY vendor_modules.py /opt/vendor_modules.py
RUN python3 /opt/vendor_modules.py --verify --root /opt/terraform-modules

# --- the loopback module-registry responder. Stdlib Python, no outbound
# --- socket anywhere in it. It ships in the AGENT image and not only in the
# --- sidecar because they are the same image run with different commands
# --- (Amendment 46 (a)): one digest in the equipping hash covers both.
COPY tf-registry/responder.py /opt/tf-registry/responder.py

# --- CLI config: filesystem_mirror for providers (no direct{} fallback, so a
# --- provider missing from the mirror fails loudly) plus the forced
# --- registry.terraform.io host block that points `modules.v1` at the sidecar.
# --- TF_CLI_CONFIG_FILE makes this the default for every `terraform`
# --- invocation in the container, agent trials included. See ./terraformrc.
COPY terraformrc /etc/terraform.d/cli.tfrc
ENV TF_CLI_CONFIG_FILE=/etc/terraform.d/cli.tfrc \
    TF_IN_AUTOMATION=true \
    TF_INPUT=false \
    CHECKPOINT_DISABLE=1

# --- preflight fixtures + script, baked into the image so `preflight.sh` runs
# --- standalone with no extra mounts. It starts the responder on loopback and
# --- writes its own CLI config pointing there, because the config above names
# --- the compose service and a single `docker run` has no such name.
WORKDIR /opt/preflight
COPY fixtures/ ./fixtures/
COPY preflight.sh ./preflight.sh
RUN chmod +x ./preflight.sh

# Agent working directory — matches arms/hcl-raw's, arms/awscdk's and
# arms/terraconstructs' /app/project convention (see ../../DECISIONS.md
# "Agent-container baseline contract").
#
# --- Workspace scaffold ---------------------------------------------------
# provider.tf is COPY'd as its own file, separately from main.tf, because
# main.tf is output_contract.entry_file — the file a normal agent solution
# fully rewrites from scratch. Keeping the bootstrap in a file the generator
# never treats as entry_file makes it structurally impossible for such a
# rewrite to delete the provider block — see ../../hcl-raw/README.md
# "Generated-task workspace split".
WORKDIR /app/project
COPY workspace/provider.tf ./provider.tf
COPY workspace/main.tf ./main.tf
CMD ["/bin/bash"]
