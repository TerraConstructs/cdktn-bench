# Decisions log

Append-only. Each entry: date, what changed, why, who directed it.

---

## Amendment 2 (2026-08-06) — arm set

**Decision:** the benchmark ships three arms, not four:

- `awscdk` — AWS CDK (TypeScript), `aws-cdk-lib` L2 constructs. Primary arm.
- `hcl-raw` — hand-written Terraform HCL, **no modules** (no `terraform-aws-modules`,
  no local module indirection). Primary arm.
- `terraconstructs` — the [terraconstructs](https://github.com/terraconstructs/terraconstructs)
  project: AWSCDK-style L2 constructs generating Terraform via `cdktn` (the community
  fork of `cdktf`; corrected 2026-08-06 — this entry originally said "via `cdktf`",
  which is the tool terraconstructs' fork is *of*, not what the shipped toolchain
  actually is: `arms/terraconstructs/environment/Dockerfile` pins `cdktn@0.23.0` /
  `cdktn-cli@0.23.0`, no `cdktf` package anywhere). **Limited-coverage
  third arm** — scenario selection for this arm is scoped to whatever services
  terraconstructs actually supports; its `Dockerfile` is written only after confirming
  actual npm package names and construct coverage against upstream (see
  `arms/terraconstructs/README.md`).

**Dropped:** the `terraform-aws-modules` arm, planned in the original pre-registration,
is **dropped from the v1 build**. This is a pre-registration deviation, directed by the
user (Vincent), logged here per the pre-reg's own amendment-log requirement.

**Explicitly excluded (unchanged from prereg / build plan):** no Pulumi arm, no chant
arm. `floci` (`ghcr.io/lex00/floci:awsbench`) remains excluded as a validity oracle
(see `docs/iac-abstraction-aws-bench-plan.md` "floci decision (locked)") and is
excluded entirely for v1 — v1's oracle tiers are synth/plan-only and never need an AWS
emulator endpoint, real or emulated.

---

## aws-bench pin

Runner dependency is pinned to commit `6450cb56c4552934a37feff492a6fd4eb84d1108` of
`https://github.com/aws-bench/aws-bench.git` (tag `v0.7.0` at that commit), matching
the trusted local clone at `/Users/vincentsmet/cdk/aws-bench` used to write
`docs/aws-bench-guide.md`.

---

## Packaging notes / fallbacks

- **Upstream package name confirmed as `aws-bench`** (see `aws-bench/pyproject.toml`
  `[project].name`), installed as a PEP 508 name via
  `[tool.uv.sources] aws-bench = { git = "...", rev = "..." }` — no path fallback was
  needed; `uv sync` resolved and installed the git dependency successfully on the
  first attempt.
- **`requires-python` bumped from the requested `>=3.11` to `>=3.12`.** Upstream
  `aws-bench` itself declares `requires-python = ">=3.12"`; uv's universal resolution
  requires the consuming project's `requires-python` range to be a subset of every
  dependency's, so `>=3.11` here is unsatisfiable while depending on `aws-bench`. This
  is a deviation from the literal task instruction, made to keep `uv sync` green — Python
  3.12+ is available locally via `uv python install` / Homebrew (`uv sync` picked
  CPython 3.14.6 automatically).
- **`[tool.uv] package = false`**: this repo has no importable Python package of its
  own yet (content + scripts, not a library), so we skip declaring a `[build-system]`
  / hatchling wheel target rather than fabricate one.
- Dev dependencies added beyond what was explicitly requested: none — `pytest`,
  `pyyaml`, `jsonata-python` (needed for the Tier-0.5 embedded-JSONata-expression
  oracle, `docs/iac-abstraction-aws-bench-plan.md` Phase 1) are exactly the three
  named in the task.

`uv sync` result: **succeeded**, 111 packages resolved, `aws-bench==0.7.0` installed
from the pinned git commit, `uv run aws-bench --help` verified working.

---

## Amendment №1 (undated in the original log — backfilled 2026-08-06) — Tier 0.5 embedded-expression oracle

**Decision:** adopt a new oracle sub-tier, **Tier 0.5 — embedded-expression evaluation**,
that evaluates every `{% ... %}` JSONata expression in a synthesized ASL document with
`jsonata-python` against scenario-defined sample inputs (technique lifted from
`tc-ai-pdlc-coding-features/tests/helpers_asl.py`). Rationale: outer-template structural
assertions can't see bugs *inside* an expression string, so without this tier the
`sfn-jsonata` seed scenario's green would be a false green in all three arms alike.
Applied identically across arms (the ASL JSON is extractable from both CFN and TF plan
output), so it adds no arm asymmetry. See
`docs/iac-abstraction-aws-bench-plan.md` lines 120–127 for the full spec.

**Status as of this amendment:** design-adopted, dependency present
(`jsonata-python` in `pyproject.toml`, confirmed installed via `uv sync`), **not yet
implemented** — no oracle script exists yet; lands with Slice D (seed scenarios +
tiered oracles). This backfill entry exists because the decisions log previously jumped
straight to "Amendment 2" with no record of a numbered Amendment 1, even though the plan
doc explicitly calls this "pre-registration amendment №1, logged" — it wasn't, until now.

This entry is being added retroactively while fixing a benchmark-integrity review
finding (2026-08-06): the log's own append-only contract means this backfill is dated to
when it was actually written, not to when the amendment was originally decided.

---

## Amendment 3 (2026-08-06) — build/repro/integrity fixes from benchmark-integrity review

Six findings surfaced by a benchmark-integrity review of Slice A required either a code
fix or a decision + record here. Logged together since they were fixed together.

### Arm build-context contract

**Decision:** every arm's `environment/Dockerfile` MUST build with `environment/`
itself as the Docker build context — never the arm root — because that is the only
context aws-bench/Harbor's runner ever uses
(`harbor/environments/docker/docker.py` `context_dir=self.environment_dir.resolve()`,
`harbor/environments/docker/docker-compose-build.yaml` `context: ${CONTEXT_DIR}`), and
it's what makes the copy-the-arm-environment-into-a-task pattern
(`tasks/anchor/smoke/environment/` is a byte-copy of `arms/awscdk/environment/`) work at
all. `arms/terraconstructs/environment/Dockerfile` violated this (used
`environment/`-prefixed `COPY` sources, requiring the arm root as context — documented,
uncaught, in its own README) and has been rewritten to be context-relative, matching
`arms/awscdk` and `arms/hcl-raw`. Canonical build command for every arm:
`cd arms/<arm>/environment && docker build -t cdktn-bench/<arm>:dev .`
Verified: `make build-arms` now builds all three arms this way and exits 0.

### Agent-container baseline contract

**Decision:** all three arm images share one minimum contract so arm-vs-arm comparison
isn't confounded by unequal agent tooling:
- **WORKDIR**: `/app/project` for all three (was `/app` for terraconstructs, `/workspace`
  for hcl-raw — both changed to match awscdk, the arm this convention originated in and
  the one downstream docs/generator plans already reference).
- **Baseline utilities**: `bash`, `git`, `curl`, `jq`, `unzip`, AWS CLI v2, present in
  every arm image (hcl-raw and terraconstructs were missing the AWS CLI; terraconstructs
  was additionally missing `jq`, which hcl-raw's own preflight.sh calls "bundled for
  oracle/verifier tooling" — a verifier/oracle script written once and reused across arms
  would have broken on terraconstructs).
Verified per-arm with `docker run --rm --entrypoint sh <image> -c 'command -v bash git
curl jq unzip aws'` against all three images — all resolve.

### TF provider version per arm (not forced to match)

**Decision:** `arms/hcl-raw` mirrors `hashicorp/aws 6.58.0`; `arms/terraconstructs`
mirrors `hashicorp/aws 6.52.0`. These are deliberately **not** unified onto one shared
version. `@cdktn/provider-aws@24.8.0`'s jsii bindings hardcode
`required_providers.aws.version = "6.52.0"` in every synthesized stack — verified by
running the arm's own `cdktn synth` and reading the emitted `cdk.tf.json`; mirroring any
other version would make that arm's own `terraform init` unable to find a matching
package, i.e. forcing a shared version would require either downgrading hcl-raw (losing
its "current stable" pin rationale) or upgrading terraconstructs' provider-aws dependency
past what its own devDependencies were tested against (undermining the "pinned to what
terraconstructs was itself built/tested against" rationale in `arms/terraconstructs/README.md`
§2). Both are within the same major version (6.x); the schema-level `ValidateFunc`
behavior this benchmark's `validate`-tier oracle depends on (see the
s3-lambda-log-retention entry below) is not known to differ between 6.52.0 and 6.58.0 for
any resource type the seed scenarios use. Each TF arm's provider version is therefore
part of that arm's own toolchain pin, not a cross-arm confound requiring reconciliation.

### terraconstructs' own TF oracle tier now runs offline

**Decision / fix:** `arms/terraconstructs/environment/Dockerfile` now runs `terraform
providers mirror` at build time and ships a `filesystem_mirror`-only `terraformrc`
(byte-for-byte the same contract as `arms/hcl-raw`'s), and
`arms/terraconstructs/environment/preflight.sh` now runs `terraform init` +
`terraform validate` on the synthesized `cdk.tf.json`, not just `cdktn synth`. Previously
the image shipped no provider mirror and no CLI config at all, so the arm's own
Dockerfile-documented oracle tier (`terraform validate`/`plan`) was unexercised by
anything green in the repo. Verified offline: `docker run --rm --network none --memory
4g cdktn-bench/terraconstructs:dev` — synth, init, and validate all pass with zero
network reachability.

### Pinning standard (digest-pinned base + lockfile-driven installs)

**Decision:** every Dockerfile in this repo (arms, scenario/deploy containers,
task environments) pins its base image by tag *and* digest, and every npm
install in an arm/scenario Dockerfile uses `npm ci` against a committed
`package-lock.json` — no floating base tags, no un-lockfiled `npm install`. Applied to:
`arms/terraconstructs/environment/Dockerfile` (`node:20-bookworm-slim` → digest-pinned
`node:20.20.2-bookworm-slim@sha256:2cf067...` — same digest awscdk already pins;
`npm install --no-save` → `npm ci` against a newly-generated, committed
`environment/app/package-lock.json`); `arms/hcl-raw/environment/Dockerfile`
(`debian:bookworm-slim` → digest-pinned `@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241`);
`scenarios/anchor/scenario/Dockerfile` (`npm install` → `npm ci` against a newly
generated, committed `cdk_app/package-lock.json`; global `npm install -g aws-cdk` →
pinned `aws-cdk@2.1135.0`, matching what the committed lockfile resolves the local
`^2.1112.0` devDependency to). `arms/awscdk` already met this bar and is unchanged.
Re-pin a digest by `docker pull <image> && docker inspect --format='{{index
.RepoDigests 0}}' <image>`; re-pin a lockfile by re-running the matching
`npm install --package-lock-only`/`npm ci` inside a container using the arm's pinned
base image, then re-running `make build-arms preflight`.

### Memory floor for tsc-heavy arms

**Decision:** any `task.toml [environment]` block using a Dockerfile whose toolchain
runs `tsc`/`ts-node` against a large jsii-generated type surface (confirmed:
terraconstructs' `@cdktn/provider-aws` bindings; likely also `awscdk`'s `aws-cdk-lib`,
per `arms/terraconstructs/README.md` "Memory finding") should set `memory_mb >= 4096`.
Below that floor, treat an OOM (container exit 137) as **infrastructure-invalid, not a
scored failure** — never as "the construct doesn't type-check" — per
`docs/iac-abstraction-aws-bench-plan.md` Phase 0 §3. This floor does **not** retroactively
apply to `tasks/anchor/smoke/task.toml`'s `memory_mb = 2048`: that task's agent never
runs `tsc`/`cdk synth` (it writes a literal marker string — see its own
`difficulty_explanation`), so it isn't exposed to this OOM class. It applies to every
scenario task Slice D generates from `awscdk` or `terraconstructs`.

### Provenance / conflict-of-interest disclosure

**Recorded (not previously in this log, only in `arms/terraconstructs/README.md` §0):**
`terraconstructs` (npm) and its underlying `cdktn`/`cdktn-cli` fork are maintained by npm
user `so0k`, npm-registry email `vincent.drl@gmail.com` — the same account this
benchmark's author (Vincent) uses. This surfaced during Slice A registry research, not
from the task prompt. Handling for analysis: `arms/terraconstructs/README.md`'s
"limited-coverage" framing and its per-scenario coverage verdicts (§3–4) should be read
as **self-reported by the person building both the arm and the library it wraps**, not
independent third-party validation, when the benchmark's results are written up. Flagged
here per the pre-reg's own decision-log requirement; still needs an explicit human
sign-off (tracked in `arms/terraconstructs/README.md` §8 "Open items", item 1) — this
entry documents the disclosure, it does not resolve it.

### Per-arm scenario-set scoping deviation

**Recorded:** `sfn-jsonata` (one of the four seed scenarios) is **excluded from the
terraconstructs arm** — its Step Functions construct has zero JSONata/`QueryLanguage`
support, source-verified by grepping every relevant file under `src/aws/compute/`
(`arms/terraconstructs/README.md` §4). This means the design is **not orthogonal**: the
terraconstructs arm runs 3 of the 4 seed scenarios where `awscdk`/`hcl-raw` run all 4 — a
concrete deviation from the plan doc's implied full-cross-product cell structure, not
previously logged here. Still needs the explicit sign-off tracked in
`arms/terraconstructs/README.md` §8 item 2 (exclude scenario for this arm only, vs. drop
the scenario benchmark-wide, vs. author a JSONPath-only variant).

### s3-lambda-log-retention catch is falsified by the pinned provider

**Recorded:** `docs/iac-abstraction-aws-bench-plan.md` line 115 claimed HCL's
`retention_in_days = 10` "passes `validate`, dies at plan/apply-tier validation" — false
against the pinned `hashicorp/aws 6.58.0`. The provider's schema `ValidateFunc` rejects
it (and other enum-shaped attributes, e.g. `aws_s3_bucket_versioning`'s `status`) at
`terraform validate` itself — the same cheap tier `tsc` catches CDK's equivalent typed
violation at — collapsing the intended cross-arm difficulty gap. Reproduced offline
(`terraform validate` exit 1, exact error text in `arms/hcl-raw/README.md` "What
`terraform validate` actually catches"). Plan doc line 115 has been marked `[NEEDS
REVISION]` inline pointing here. **Action required before Slice D freezes scenario
specs:** re-derive this scenario's headline catch as either (a) a structural/nested
value that's syntactically accepted but semantically ignored (no schema-level
`ValidateFunc` can catch that — the `ecs-swappiness` scenario's silent-drop-unless-
`maxSwap` pattern is the model), or (b) a genuinely runtime-only constraint invisible to
both `validate` and `tsc`.
