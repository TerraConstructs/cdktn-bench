# Scenario deploy container: Node 24 + AWS CLI v2 + CDK CLI. Mirrors
# aws-bench-datasets/scenarios/ec2-multiregion/scenario/Dockerfile (the
# upstream smoke-test scenario) — see docs/aws-bench-datasets-guide.md §6a.
# node:24-slim @ 2026-08-06 (digest-pinned per DECISIONS.md "Pinning standard")
FROM --platform=linux/amd64 public.ecr.aws/docker/library/node@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03

WORKDIR /app

# Build-time deps: curl + unzip for the AWS CLI installer; git for CDK asset
# hashing. --no-install-recommends keeps the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 (CDK shells out to it for some asset / bootstrap operations).
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

# CDK CLI globally so deploy.sh / cleanup.sh can call `npx cdk`. Pinned to
# the exact version cdk_app/package-lock.json resolves for the local
# `aws-cdk` devDependency (^2.1112.0 -> 2.1135.0 as of the lockfile's
# generation date), so global `cdk`/`npx cdk` agree — same discipline as
# arms/awscdk/environment/Dockerfile.
RUN npm install -g aws-cdk@2.1135.0

# Copy the CDK app last so edits to TS source don't invalidate the layers
# above. `npm ci` (not `npm install`) so the committed cdk_app/package-lock.json
# is authoritative and a rebuild can't silently drift dependency versions —
# see ../../../DECISIONS.md "Pinning standard". Deviates from the upstream
# aws-bench-datasets/scenarios/ec2-multiregion/scenario/Dockerfile this
# mirrors (which uses `npm install` and an unpinned global `aws-cdk`) on
# purpose, in the stricter direction; upstream itself ships a lockfile this
# scenario previously dropped.
COPY cdk_app/ /app/cdk_app/
# `npm run build` (= `tsc`, outDir ./dist) is REQUIRED here, not an
# optimization: cdk_app/cdk.json's app command is now `node dist/lib/app.js`
# (was `npx ts-node lib/app.ts`), so `dist/` must exist in the image or every
# `cdk synth`/`deploy`/`destroy` — including cleanup.sh paths that run without
# a prior deploy.sh — fails with "Cannot find module". Dropping ts-node from
# the synth path is what retires this container's historical exit-137: the
# in-process ts-node type-check peaked at 1.7 GB tree RSS during `cdk deploy`,
# vs ~0.87 GB precompiled (docs/ts7-spike-results.md, docs/ts-runtime-spike2-results.md).
# deploy.sh still runs `npm run build` itself, which is now a warm no-op
# rebuild rather than a compile whose output was thrown away.
RUN cd /app/cdk_app && npm ci && npm run build
