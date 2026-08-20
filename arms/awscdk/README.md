# arms/awscdk

Primary arm: hand-written **AWS CDK (TypeScript)** using `aws-cdk-lib` L2 constructs.
Gate = `tsc --noEmit` + `cdk synth` (no deploy, no AWS credentials required for
synth-only oracle tiers). See `../../DECISIONS.md` Amendment 2 for why this arm
is primary (not the sole arm).

## Layout

```
arms/awscdk/
    README.md              this file
    preflight.sh            host-side entry point: build + run the in-container check
    environment/
        Dockerfile           the arm's agent container image
        preflight.sh         COPY'd into the image at /usr/local/bin/preflight.sh
        workspace/           starting CDK TypeScript project, baked into every image
            package.json      pinned deps (see "Pinned versions" below)
            package-lock.json committed — `npm ci` in the Dockerfile is reproducible
            tsconfig.json
            cdk.json          app entrypoint = chained compile + compiled JS (see "Why not ts-node")
            bin/app.ts         entrypoint; instantiates ExampleStack
            lib/example-stack.ts  one-construct (S3 bucket) smoke-test stack
```

`environment/` is deliberately the whole self-contained build context — it mirrors
the aws-bench-datasets convention (`docs/aws-bench-guide.md` §5-7,
`docs/aws-bench-datasets-guide.md` §2/§6b) where a task's `environment/` directory
*is* the Docker Compose build context. The generator copies `environment/`
verbatim into each generated `tasks/anchor/<scenario>-awscdk/environment/`, adds a
`docker-compose.yaml` (upstream's minimal `services:\n  main: {}` is
sufficient), and overwrites `workspace/lib/` with the scenario-specific stack —
nothing else about this Dockerfile needs to change per task. (This paragraph was
written ahead of the generator, in Slice C's future tense; the mechanism it
describes is what shipped. On a **brownfield** scenario the overwritten content
is a hand-authored `workspace_seed` rather than a skeleton — `specs/SCHEMA.md`
§2.7.)

Because everything under `environment/` is `COPY`'d into the agent image, it is
**prompt surface**: the skeleton header, file names and comments are all read by
the agent from second zero. That is why generator-stamped headers come from
`workspace_title` rather than the scenario `title` on any scenario whose title
could foreshadow (`specs/SCHEMA.md` §0.1, `DECISIONS.md` Amendments 27 §5.1 /
28 §3).

## Image contract

- **Base**: `node:20.20.2-bookworm-slim`, pinned by tag *and* digest
  (`sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0`).
  Node ≥ 20 is CDK 2.x's minimum (`aws-cdk-lib@2.263.0` `engines.node` = `>=20.0.0`).
- **WORKDIR**: `/app/project` — the agent's working directory, a ready CDK
  TypeScript project (`workspace/` baked in via `COPY` + `npm ci` at build time).
  The Slice C generator overwrites `lib/` here per scenario; `bin/app.ts` and
  `tsconfig.json`/`cdk.json` are expected to stay as-is unless a scenario needs
  a different entrypoint.
- **`node_modules` is baked into the image.** `npm ci` runs once at `docker build`
  time (the only point at which the build needs network access); no trial or
  `preflight.sh` run ever calls `npm install`. This is what makes offline synth
  possible — see "No network required" below.
- **`cdk` CLI is on `PATH` globally** (`npm install -g aws-cdk@2.1135.0`), pinned
  to the exact same version as the workspace's local `aws-cdk` devDependency, so
  `cdk ...` and `npx cdk ...` resolve to identical behavior.
- **AWS CLI v2** is installed (`/usr/local/bin/aws`) for parity with the upstream
  aws-bench-datasets agent-container convention and for later task slices whose
  instructions may call it. **Not required** by `preflight.sh`, which proves the
  CDK toolchain (`tsc`, `cdk synth`) works with zero AWS surface area.
- **`CDK_DISABLE_VERSION_CHECK=true`** and `NPM_CONFIG_UPDATE_NOTIFIER=false` /
  `NPM_CONFIG_FUND=false` / `NPM_CONFIG_AUDIT=false` are set so nothing in the
  toolchain tries an update-check network call at synth/build time.
- Utility packages (`ca-certificates curl unzip less groff jq zip git`) match the
  upstream dataset Dockerfile's baseline set.

### Pinned versions

Resolved from the npm registry on 2026-08-06 (`npm view <pkg> dist-tags`); bump by
re-running that and updating both `environment/workspace/package.json` and the
version strings in `environment/Dockerfile`'s header comment + `npm install -g`
line together, then regenerate the lockfile (`npm install --package-lock-only`
inside `environment/workspace/`) and re-run `preflight.sh`.

| Package | Version | Where pinned |
| --- | --- | --- |
| `node` (base image) | `20.20.2` | `environment/Dockerfile` `FROM` (tag + digest) |
| `typescript` | `7.0.2` | `workspace/package.json` devDependencies |
| `aws-cdk-lib` | `2.263.0` | `workspace/package.json` dependencies |
| `constructs` | `10.8.1` | `workspace/package.json` dependencies (satisfies `aws-cdk-lib`'s peer range `^10.5.0`) |
| `aws-cdk` (CLI) | `2.1135.0` | `workspace/package.json` devDependencies **and** global install in `environment/Dockerfile` |
| `@types/node` | `22.15.30` | `workspace/package.json` devDependencies |
| `source-map-support` | `0.5.21` | `workspace/package.json` dependencies (used by `bin/app.ts` for readable stack traces) |

### Why not ts-node

The initial draft used the conventional `cdk init --language typescript` pattern
(`cdk.json` `"app": "npx ts-node bin/app.ts"`). With `typescript@7.0.2`,
`ts-node@10.9.2` (last published version) crashes (`Cannot read properties of
undefined (reading 'fileExists')` in `ts-node/dist/configuration.js`) — `ts-node`
reaches into TypeScript compiler internals that changed in TS 7's rewrite, and
nothing in the `ts-node` line supports it yet. `tsc` itself works fine with TS 7
(only needed one `tsconfig.json` fix: `moduleResolution` can no longer be the
removed `"node"` value — this workspace uses `"bundler"`, which stays compatible
with `"module": "commonjs"`).

Rather than pin `typescript` back to a `ts-node`-compatible 5.x to keep the
ts-node convenience, this workspace **compiles then runs plain `node`**:
`cdk.json` `"app"` is `"npx tsc -p tsconfig.json && node bin/app.js"` (the
compile is *chained into* the app string, not left to a separate step: with a
bare `node bin/app.js`, editing a `.ts` into a type-broken state would still
synth exit-0 off the previously-emitted good JS — `noEmitOnError` semantics mean
a failed build never overwrites it — and a broken solution would score as
correct; see `docs/ts-runtime-spike2-results.md`), and `package.json`'s `synth` script is
`npm run build && cdk synth --no-lookups`. This is a more boring, more robust
pattern anyway (no on-the-fly transpilation magic in the hot path an agent
depends on) — `preflight.sh` runs `npm run build` before every `cdk synth` and
cleans up the compiled `.js`/`.d.ts` afterward so the workspace stays in the
pristine state the Slice C generator expects to find it in.

### Known, unfixable advisory

`npm audit` reports one **high**-severity advisory (`GHSA-rgw5-rvv9-x895`,
`brace-expansion` DoS) nested at
`node_modules/aws-cdk-lib/node_modules/brace-expansion` — a dependency **bundled
inside** the `aws-cdk-lib@2.263.0` package itself, not something this workspace's
`package.json` can override. `npm audit fix` confirms: "It cannot be fixed
automatically... Check for updates to the aws-cdk-lib package" — `2.263.0` is
already the latest published version as of the pin date. Re-check on every
version bump; not a blocker (dev-time-only glob usage, no network-facing surface
in a synth-only container).

### No network required, no AWS credentials required

`preflight.sh` proves both directly: it unsets/blanks every AWS credential
env var, points `AWS_SHARED_CREDENTIALS_FILE`/`AWS_CONFIG_FILE` at nonexistent
paths, and disables the EC2 metadata credential source — then the host wrapper
additionally runs the container with `docker run --network none`. Synth succeeds
because:
- `bin/app.ts` never sets `env: { account, region }` on the stack, so CDK
  synthesizes CloudFormation pseudo-parameters/tokens instead of resolving a
  real account/region;
- `cdk synth --no-lookups` explicitly disables context lookups (this app makes
  none, but the flag is cheap insurance for scenario stacks the generator adds
  later that might);
- all `node_modules` are already on disk from the image build — no npm registry
  call happens at synth time.

## Usage

```bash
# Build the image and run the in-container preflight (no network, no creds):
./preflight.sh

# Just re-run preflight against an already-built image:
SKIP_BUILD=1 ./preflight.sh

# Build with a different tag:
IMAGE_TAG=myorg/awscdk:test ./preflight.sh

# Equivalent to what preflight.sh does, spelled out:
docker build -t cdktn-bench/awscdk:dev -f environment/Dockerfile environment/
docker run --rm --network none --entrypoint /usr/local/bin/preflight.sh \
    cdktn-bench/awscdk:dev
```

### Verified locally (2026-08-06)

- `docker build -t cdktn-bench/awscdk:dev -f environment/Dockerfile environment/` — green.
- `docker run --rm --network none --entrypoint /usr/local/bin/preflight.sh cdktn-bench/awscdk:dev` —
  all 5 checks pass: node/npm versions, `tsc --version` (`7.0.2`), `cdk --version`
  (`2.1135.0 (build 0fa27ff)`), `tsc --noEmit` clean, `cdk synth --no-lookups`
  produces a 9471-byte `ExampleStack.template.json` containing an
  `AWS::S3::Bucket` resource.
- Image size: **~322 MiB** (338,051,072 bytes, measured via `docker save | wc -c`
  — the authoritative single-platform on-disk size; `docker images`'s ~1.3 GB
  figure on this host counts a buildx-generated multi-manifest/attestation
  index, not the runnable image content).
