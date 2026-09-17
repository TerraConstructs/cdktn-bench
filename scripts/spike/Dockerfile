# Spike image for the M10 engine evaluation (docs/design/m10-one-rego-engine.md
# section 2): one container holding both Rego engines plus jq, so every
# (policy, artifact) pair is evaluated by opa and by regorus on identical bytes.
#
# Not a verifier image and not wired into any arm. Build it as
# cdktn-bench-spike/rego-engines:0.12.0 -- see scripts/spike/README.md.
#
# regorus ships no release binary and no wheel: its CLI is a cargo *example*,
# so the pin is tag + commit and the build stage is the only source.
FROM rust:1-bookworm AS build
ARG REGORUS_TAG=regorus-v0.12.0
ARG REGORUS_COMMIT=c6c679f49b93b05d81bf6fd661931b86fcf416ea
RUN set -eu; \
    git clone --depth 1 --branch "${REGORUS_TAG}" https://github.com/microsoft/regorus /src; \
    cd /src; \
    test "$(git rev-parse HEAD)" = "${REGORUS_COMMIT}"; \
    cargo install --example regorus --path . --root /out; \
    strip /out/bin/regorus; \
    ls -l /out/bin/regorus

FROM debian:bookworm-slim
ARG TARGETARCH=arm64
# opa: the same URL and sha256 the arm images pin
# (arms/hcl-raw/environment/Dockerfile).
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl jq; \
    rm -rf /var/lib/apt/lists/*; \
    case "${TARGETARCH}" in \
      amd64) OPA_SHA256="1dd5c5591ff856f5e20a1d66bafae9511ddf3c5552ed3b5070c70b2b6580ee3f" ;; \
      arm64) OPA_SHA256="06680087ed236c8c6aaa021660d83178db829a2ad30bdb3482481fada6791b2a" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/opa \
      "https://github.com/open-policy-agent/opa/releases/download/v1.19.0/opa_linux_${TARGETARCH}_static"; \
    echo "${OPA_SHA256}  /usr/local/bin/opa" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/opa
COPY --from=build /out/bin/regorus /usr/local/bin/regorus
RUN opa version && regorus --version && jq --version
