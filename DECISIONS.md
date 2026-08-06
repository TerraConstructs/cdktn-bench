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

---

## Amendment 4 (2026-08-06) — generator + oracle-evaluator fixes from a second
## benchmark-integrity review

A second review of Slices B/C found 16 findings (6 blockers on the generator's own
correctness, the rest on the two oracle evaluators disagreeing with each other and with
`specs/SCHEMA.md` §4.2's own documented op semantics). All 16 were fixed; the ones that
changed a decision, not just a bug, are recorded here. Every fix below was proven against
a real invocation (real `terraform`/`jq`/`opa`/`cfn-guard`/`docker build`/`npm install`/
`cdktn synth`), not just unit-tested in isolation, per this log's own evidentiary
standard.

### `!`-negation of a compound shell command (generator/gen.py, all toolchain steps)

**Fixed, no decision needed:** `if ! {command}; then` mis-binds `!` to only the first
simple command when `{command}` contains `&&`/`||`/`;` (e.g. hcl_raw's whole
`plan_command`), so bash's `!`-then-`&&`-short-circuit skipped every step after the
first on the SUCCESS path. This made the hcl_raw arm's `plan.json` never get created —
constant 0.0 reward regardless of solution quality. Fixed by wrapping the command in a
subshell (`if ! ( {command} ); then`), which makes `!` negate the compound command's
overall exit status instead. Also applied to `textwrap.dedent(f"""...""")` being called
AFTER f-string interpolation of multi-line blocks (which silently no-ops dedent, since
the interpolated blocks' column-0 lines collapse the common-prefix computation to `""`,
leaving the generated `static_tiers.sh`'s own shebang indented and unexecutable via
direct `execve`) — template is now dedented BEFORE the multi-line blocks are substituted
in (string-token replacement, not f-string interpolation, post-dedent).

### terraconstructs arm now runs a real `terraform init/plan/show` after synth

**Decision:** `generator/gen.py::build_static_tiers_sh` now ALWAYS appends a
`terraform init/plan/show` step (chdir'd into the synthesized stack's own
`cdktf.out/stacks/<id>/`) after this arm's `synth_command`, and the arm's `main.ts`
skeleton (`terraconstructs_main_ts()`) now carries the same `skip_*`/dummy-credential
provider fixture `hcl_raw_main_tf()` already had. Previously the arm's `artifact_path`
was raw `cdktn synth` output (`resource.<type>.<id>` shape), which has no
`planned_values` key at all — every `tf_jsonpath` in `oracle.structural_asserts` (written
in `terraform show -json` PLAN shape, matching hcl_raw) resolved to nothing, so this arm
scored a constant 0.0 for every solution including a perfect one. Proven end-to-end
offline in this repo's own `uv`/npm/terraform toolchain: installed the real
`terraconstructs@0.2.13`/`cdktn@0.23.0` packages, ran `npx cdktn synth` against a correct
hand-written `ScenarioStack`, then `terraform init && terraform plan && terraform show
-json`, and confirmed `.planned_values.root_module.resources[...]` resolves as expected.

**New limitation discovered while proving this (not previously known, not yet fixed —
flagged for Slice D):** `AwsStack`'s generated Terraform JSON unconditionally includes a
`data "aws_caller_identity"` lookup the moment ANY real resource construct is added (even
a bare `StringParameter` with no ARN-formatting policy attached) — confirmed by
comparing a truly-empty `ScenarioStack`'s synth output (no `data` block at all) against
one with a single `StringParameter` (a `data.aws_caller_identity` block appears). Unlike
`hcl_raw`'s dummy-credential fixture, `skip_requesting_account_id` does NOT suppress an
*explicit* `data` resource's STS call the way it suppresses the provider's own implicit
account lookup — so `terraform plan` for that data source needs either real (however
tightly-scoped) AWS credentials, or a mocked STS endpoint (e.g. `AwsProviderConfig`'s
`endpoints` field pointed at a LocalStack-style stub), in a `--network none` container.
This is orthogonal to the artifact-shape fix above (the shape is now correct regardless);
it blocks the *next* problem, "does a real terraconstructs solution's `terraform plan`
succeed offline" — a Slice D concern once real scenarios need IAM policies scoped to
resource ARNs, which is most of them.

### `tests/` layout moved to `tasks/anchor/<spec.id>-<arm>/`

**Decision:** `generator/gen.py::task_dir()` now emits
`tasks/anchor/<spec.id>-<arm-dirname>/` instead of `tasks/<spec.id>/<arm>/`. The old
layout made every generated `spec.id` look like its own scenario with no `scenarios/`
directory to aws-bench-datasets' own registry generator
(`aws_bench/scripts/update_registry.py` derives "scenario" from the `tasks/` PARENT
directory name), even though every generated task's own `task.toml` declares
`scenario_id = "anchor"`. The new layout matches that derivation AND the north-star
example (`aws-bench-datasets/tasks/compute-and-data/create-eks-cluster/`). Non-toy specs
(`specs/_toy/` is explicitly exempt, per its own file header) now also get a real
`local-registry.json` entry (`generator/gen.py::update_local_registry`), idempotent by
task name, so generated tasks are reachable in registry/dataset mode, not just
`-p tasks/anchor/<id>-<arm>` local-path mode.

### Single writer for `oracles/rego/<id>/policy.rego` + `oracles/cfn-guard/<id>/policy.guard`

**Decision:** `generator/gen.py::generate_oracles` now calls `oracles.emit.emit_oracles`
instead of maintaining its own, second `build_rego_stub`/`build_cfn_guard_stub`. Both
used to write the same paths behind the same `if not exists` guard, unaware of each
other — whichever ran first against a given scenario "won" permanently, including which
one's stub-detection marker ended up on disk. This was live, not theoretical:
`oracles/rego/toy-ssm-parameter/policy.rego` and `.../policy.guard` on disk were
`emit.py`'s content (no `GENERATOR-STUB` marker), so `is_stub_policy()` (which greps for
that literal string) mis-detected them as hand-authored. `emit.py`'s skeletons now also
carry the `GENERATOR-STUB` marker (plus a `TODO(Slice D)` belt-and-suspenders fallback in
`is_stub_policy()` itself), and `emit.py` is the sole writer going forward.

### Tier-1 grading tools installed in every arm image; a missing tool is now a hard failure

**Decision:** `arms/awscdk/environment/Dockerfile` now installs `cfn-guard 3.2.0`
(sha256-pinned prebuilt binary); `arms/hcl-raw/environment/Dockerfile` and
`arms/terraconstructs/environment/Dockerfile` now install `opa 1.19.0` (sha256-pinned
static binary) — the tools `generator/gen.py`'s generated `tests/static_tiers.sh`
actually invokes for tier-1. Verified: `docker build` succeeded for all three arms
(`cfn-guard --version` / `opa version` run and print the pinned version during the build
itself, hard-failing the build on a checksum mismatch), and the awscdk arm's PATCHED
per-task `preflight.sh` (see below) passes `--network none` against a freshly-built
`tasks/anchor/toy-ssm-parameter-awscdk` image.

Independently of installing the tools, `generator/gen.py`'s generated
`tests/static_tiers.sh` no longer treats "tool missing" the same as "nothing to check
here": `tier1_status` is now one of `SKIPPED_NO_ASSERTS` (no tier-1 asserts declared —
still non-gating), `SKIPPED_STUB` (tool present, but the policy is still an unauthored
generator scaffold — still non-gating, an intentional Slice D deferral), `TOOL_MISSING`
(tier-1 asserts ARE declared but the tool isn't on PATH — now a HARD reward-0.0 failure,
plus a `/logs/verifier/tier1-unavailable` marker), or `PASS`/`FAIL` (the tool actually
ran). Previously all four of the first three collapsed into one `SKIPPED` status the
final reward gate always treated as non-blocking, so a scenario with real tier-1 asserts
and a genuinely broken/incomplete arm image (tool never installed) scored full reward for
any solution, tier-1 policy violations included. Verified locally: temporarily removed
`opa` from `PATH`, confirmed a tier-0-passing hcl_raw solution now scores `0.0` with
`tier1_status=TOOL_MISSING` (previously: `1.0`).

### Oracle op table gets `set_eq` and a `|fromjson` path extension; jq semantics realigned to SCHEMA.md §4.2

**Decision:** `specs/SCHEMA.md` §4.2's op table is the one authoritative semantics both
evaluators (`generator/gen.py`'s compiled-jq `assert_check`, used by every real trial; and
`oracles/lib/structural.py`, jsonpath-ng-based, used for spec-authoring-time and
oracle-equivalence checks) must match — they didn't, on 3 of 6 ops, confirmed by a new
differential test suite (`oracles/tests/test_op_parity.py`) that runs BOTH evaluators
against shared fixtures:
  - `eq` (jq: any-of-N-matches-equal passed; SCHEMA says "the *(single)* resolved value" —
    jq now requires exactly one match, matching Python and the spec text);
  - `contains` (jq used `test($e;"")`, a REGEX match, for strings — `"."` in `expected`
    silently acted as a wildcard, e.g. `"ec2.amazonaws.com"` matched the string
    `"ec2Xamazonaws.com"` — a real false-PASS on a role-trust check, not academic; jq now
    uses `contains/1`, a literal substring test, matching Python and "contains" in plain
    English);
  - `in` (jq didn't flatten a bare-string-vs-list-of-strings property, e.g. IAM `Action`,
    across matched statements the way Python already did; jq now flattens one level,
    matching both);
  - `not_exists` was ALSO shell-only-broken (not a cross-evaluator disagreement): jq's
    plain field access returns `null` for a key that is simply absent, so a query
    collecting across N matched objects where none has the field resolved to
    `[null, ...]` (length N, not 0) — `not_exists` failed unconditionally, including
    against a known-good, correctly-nested artifact (the ECS-swappiness-shaped
    nested-attribute catch's flagship negative case). Fixed by stripping nulls from the
    jq collection stage (`map(select(. != null))`) before every op's length check.

Two grammar/op-table gaps were also closed, both proven against the toy spec's own
`role-trust-is-ec2-only` assert (re-expressed with both extensions, regenerated, and
verified with a real `terraform plan`: an over-broad trust policy — `ec2.amazonaws.com`
PLUS an unintended `lambda.amazonaws.com` — now correctly drops reward from `1.0` to
`0.0`, where it previously passed under `contains`):
  - **`set_eq` op** — `in`/`contains` can only express "every actual value is allowed" or
    "at least one match," so a correct value plus an extra, unintended one still passes
    both. Every "scoped, not broader"/"trusts ONLY X" catch in the taxonomy needs exact
    set equality, which the six-op table had no member for.
  - **`|fromjson` path segment** — several Terraform plan JSON attributes the taxonomy's
    catches target (`values.container_definitions`, `values.assume_role_policy`,
    `values.policy`) are JSON-encoded STRINGS, not nested structure. Without a way to
    decode into them, any TF-side assert targeting inside one of those blobs silently
    resolves against the raw string and finds nothing — this was true of the toy spec's
    OWN `role-trust-is-ec2-only` `tf_jsonpath` (it "worked" only by `contains`-substring-
    matching the raw undecoded string, the same accidental mechanism that let the regex
    bug above hide). Implemented in both evaluators identically (`generator/jsonpath_jq.py`
    compiles it to jq's `fromjson`; `oracles/lib/structural.py::resolve` resolves
    segment-by-segment, `json.loads`-ing between segments) — Rego/cfn-guard need no
    equivalent extension, since native JSON-string decoding is a normal builtin in both.
  - The translator also gained recursive descent (`..Field`) and bare-value filter
    predicates (`[?(@=='V')]`), needed for the sfn-jsonata mode-mixing catch (finding
    JSONPath-mode artifacts like `ResultPath` anywhere inside a JSONata-mode machine, at
    unknown depth) and for wildcard-value checks respectively — not yet consumed by any
    real spec (no Slice D scenario exists yet), but no longer blocked when one needs them.

### Tier-0.5 runs host-side, non-gating (not wired into any arm's `static_tiers.sh`)

**Decision:** Tier-0.5 (embedded JSONata-expression evaluation, Amendment №1) is
deliberately NOT executed inside any arm's container. No arm image ships Python or
`jsonata-python`, and installing that dependency into three separate Docker images to
support a check that only applies to ASL-embedded-expression scenarios (not every
scenario) was judged not worth the image-size/build-time cost versus running it
host-side, post-hoc, from this repo's own `uv` environment (which already has
`jsonata-python`, via `oracles/lib/tier05_jsonata.py`'s own test suite). Concretely:
`oracles/lib/tier05_jsonata.py` gained a CLI (`uv run python -m
oracles.lib.tier05_jsonata <artifact.json> <spec.yaml>`), and `generator/gen.py` now
emits a `tests/TIER05.md` note (only for scenarios whose spec declares
`oracle.tier05_jsonata`) documenting that exact command — mirroring `tests/live_check.py`'s
existing non-gating precedent (`/logs/verifier/tier05-result.json`, never
`/logs/verifier/reward.txt`). Verified: the CLI exits 0 against a correct fixture and 1
(with a legible per-case diagnostic) against a fixture with a real JSONata syntax error.

Separately, `run_tier05`'s cartesian-product bug (evaluating EVERY found expression
against EVERY declared sample, rather than each case against the one expression it's
meant to test) is fixed: `oracle.tier05_jsonata.sample_inputs` is now
`oracle.tier05_jsonata.cases: [{expression_path, input, expected_output}, ...]`, keyed to
a specific expression's path. A case whose `expression_path` matches no expression found
in the artifact (a renamed/removed state) now fails loudly instead of being silently
skipped, and an expression with no covering case also fails loudly (previously: silently
ungraded). Regression-tested with a real 2-state, 2-correct-expression fixture
(`oracles/tests/fixtures/mini_asl_cfn_multi_good.json`) that the old cartesian-product
version would have unconditionally rejected.

### Falsifiability gate: a solution must score 1.0 and a broken fixture per catch must score 0.0

**Decision:** added `gates/oracle_falsifiability.py` (`make falsifiability
SPEC=specs/foo.yaml`), making the Phase-2 exit criterion executable now rather than
deferred. For every enabled arm: `solution/solve.sh` must score reward `1.0`, AND every
`spec.catches[].name` must have a `solution/broken/<catch-name>/solve.sh` that scores
`0.0` — or the gate fails, with a distinct `NOT_AUTHORED` (non-gating) status only for a
scenario whose `solve.sh` is still a generator stub (Slice D hasn't gotten to it yet).
This directly targets the finding that a hand-crafted artifact violating every clause of
a scenario's own `oracle.intent` (wrong trust principal set, wildcard-resource inline
policy) scored a clean `1.0` reward. Proven against the toy spec (temporarily, not
committed to the tracked task dir — solution-authoring is Slice D's job): a real hcl_raw
`solve.sh` scores `1.0`; a `broken/policy-scoped-to-parameter/` fixture reproducing the
exact over-broad-trust attack scores `0.0`; the toy's OTHER catch
(`parameter-tier-enum`, explicitly flagged "illustrative only, no real oracle backing" by
the spec's own file header) correctly surfaces as `MISSING` — proving the gate has teeth
and would refuse to let a real scenario register with an uncovered catch.

### `tasks/anchor/*/environment/preflight.sh` is now scenario-shape-aware, not a byte-copy of the arm-dev fixture

**Fixed, no decision needed:** the awscdk and terraconstructs `preflight.sh` scripts are
written for their ARM-LEVEL dev image's fixture stack (`ExampleStack`/S3 bucket;
`cdktn-bench-preflight`/S3+LogGroup) but `generator/gen.py::write_environment` byte-copies
the same script into every generated task while ALSO overwriting the workspace with an
empty `ScenarioStack` skeleton under a different stack id — so the copied preflight
script's hardcoded stack-id/resource-type assertions could never pass on any generated
task's own image. `write_environment` now patches the copied `preflight.sh` per arm
(`patch_awscdk_preflight`/`patch_terraconstructs_preflight`): correct stack id, and a
generic "produced valid, well-formed synth output" check instead of a hardcoded resource
type an empty starting skeleton doesn't have yet (scenario correctness is
`tests/static_tiers.sh`'s job, not preflight's). Verified with a real `docker build` +
`docker run --network none` against `tasks/anchor/toy-ssm-parameter-awscdk`'s own image:
all 5 preflight steps pass, including the previously-impossible step 5.

### terraconstructs offline `terraform plan` needs a mocked STS endpoint

**Decision, closing the limitation flagged above ("New limitation discovered while
proving this... flagged for Slice D"):** confirmed by installing the real toolchain
(`terraconstructs@0.2.13`, `cdktn@0.23.0`, `terraform 1.15.8`) that `AwsStack`'s `account`
getter (`node_modules/terraconstructs/lib/aws/aws-stack.js`) lazily creates an EXPLICIT
`data "aws_caller_identity"` the moment ANY construct references the stack's account —
which most L2s do internally for ARN formatting, so this isn't limited to IAM/ARN-heavy
scenarios: a bare `new Bucket(this, "B", {})` with no IAM at all already triggers it.
`skip_requesting_account_id` only suppresses the AWS provider's own IMPLICIT account
lookup, not this explicit data source's real STS call, so `terraform plan` for any
non-trivial terraconstructs solution 403'd (`InvalidClientTokenId`) against real STS with
no credentials and no network — making the arm ungradeable for any solution that actually
uses the L2 abstraction, while a hand-rolled L1-only escape hatch (bypassing `AwsStack`'s
`account`/`lookup` machinery entirely) planned fine. That inverted the incentive the arm
exists to measure.

**Fix:** `AwsProvider` (and `@cdktn/provider-aws`'s underlying `terraform-provider-aws`)
supports a per-service `endpoints` override block, including `endpoints.sts`. Added
`arms/terraconstructs/environment/app/mock-sts.js` — a dependency-free (`node`'s built-in
`http` only) loopback HTTP responder that answers any request with a fixed, valid
`GetCallerIdentity` XML body, ignoring SigV4-signed headers — byte-copied into every
generated task's `/app/project/mock-sts.js` (`write_environment`'s `shutil.copytree` of
the whole `environment/app/` tree; also explicitly `COPY`'d by the arm `Dockerfile`, which
lists `app/*` files individually rather than copying the directory wholesale).
`terraconstructs_main_ts()`'s generated `providerConfig` now points
`endpoints: [{ sts: "http://127.0.0.1:17771" }]` at it, and
`build_static_tiers_sh`'s terraconstructs tf-plan step starts the mock server
immediately before `terraform init/plan/show` and kills it immediately after (tracking
its PID, not just backgrounding-and-forgetting it) — the kill matters because
`gates/oracle_falsifiability.py` runs `solve.sh` and every `broken/<catch>/solve.sh`
sequentially on the same bare host, and an orphaned server on the same fixed port would
`EADDRINUSE` the second run. `127.0.0.1` works even under `docker run --network none`
since the `lo` interface is always present in a container's own network namespace
regardless of external attachment, so the arm's offline-plan contract is unchanged.

**Proven** end-to-end through the real generated `tests/static_tiers.sh` (not just a
standalone `main.ts`, and not just the artifact-shape fix's earlier proof), using the
installed toolchain: a bare `new Bucket(this, "B", {})` plus
`new Role(this, "R", { assumedBy: new ServicePrincipal("ec2.amazonaws.com") })` —
exactly the idiomatic-L2, no-manual-ARN-plumbing shape a prior review's repro (a)/(a2)
showed failing — now reaches `terraform plan`'s "Plan: 2 to add, 0 to change, 0 to
destroy" and `role-trust-is-ec2-only` PASSes at tier-0, where it previously 403'd before
any tier-0 assert could even run. Not proven with the toy scenario's actual SSM parameter
construct, because terraconstructs has no `src/aws/ssm/` L2 at all (see
`arms/terraconstructs/README.md`'s coverage table and the spec's own
`arms.terraconstructs.reason` disclosure) — this fix unblocks offline `plan` for L2
constructs in general, independent of which service.

**Side fix required to land this:** `build_static_tiers_sh`'s per-step preview echo
(`echo "== {label}: {command} =="`) assumed `command` was always single-line with no
embedded `"` — true of every step until this one, which needs embedded
`"$MOCK_STS_PID"` references and multiple newlines to start/stop the mock server. Left
unescaped, the literal `"` characters inside `command` prematurely closed/reopened the
outer double-quoted echo argument, turning `>`/`>>` text that was meant to stay a literal
label into a REAL shell redirection a few words later — a preview-only line able to
silently diverge from (or corrupt files relative to) the real `if ! ( {command} ); then`
executed immediately after. Now wrapped in `shlex.quote()`, safe for arbitrary embedded
quotes/newlines in any future step's command, not just this one.

### tier-1 `SKIPPED_STUB` is now a hard failure once a scenario declares tier-1 asserts

**Decision:** the same "TOOL_MISSING must be run-invalidating, not scored as a pass"
argument from the section above ("Tier-1 grading tools installed in every arm image...")
applies equally to `SKIPPED_STUB` (a tier-1 policy file that's still a generator scaffold,
`is_stub_policy`), which `build_static_tiers_sh`'s final reward gate did not previously
account for: `[ "$tier0_pass" = "1" ] && [ "$tier1_status" != "FAIL" ] && [ "$tier1_status"
!= "TOOL_MISSING" ]` scored `SKIPPED_STUB` as a pass, so a scenario whose tier-1 policy
hadn't been hand-authored yet (Slice D pending) would award full `1.0` reward to ANY
solution that got past tier-0 — including one that violates every tier-1 clause the
unauthored policy was supposed to check. Reproduced exactly as described: an awscdk
`ScenarioStack` with a correct SSM parameter, a correctly ec2-only-trusted role, and an
inline policy of `Action: ["iam:*","s3:*","ssm:*"], Resource: "*"` (violating both of the
toy spec's tier-1 asserts, `policy-resource-scoped-not-wildcard` and
`policy-actions-read-only`) produced `tier0_pass=1 tier1_status=SKIPPED_STUB` and reward
`1.0` against the pre-fix generated `static_tiers.sh`.

**Fix:** the reward gate now also requires `[ "$tier1_status" != "SKIPPED_STUB" ]`, and
the `SKIPPED_STUB` branch (both the awscdk/cfn-guard and hcl_raw+terraconstructs/OPA
variants) now also writes a `/logs/verifier/tier1-unauthored` marker (mirroring
`TOOL_MISSING`'s `tier1-unavailable`) so an un-authored-policy run is distinguishable in
the logs from both a real policy `FAIL` and a `TOOL_MISSING` run. `SKIPPED_NO_ASSERTS`
(a scenario with zero tier-1 `structural_asserts` at all) is unaffected — still
legitimately non-gating, since there is nothing to have forgotten to author.

**Proven** with the same reproduction above, re-run against the regenerated
`static_tiers.sh`: `tier0_pass=1 tier1_status=SKIPPED_STUB`, reward now `0.0`, with
`/logs/verifier/tier1-unauthored` written. Cross-checked on all three arms (awscdk,
hcl_raw, terraconstructs) with equivalent violating solutions — same result on each.
`gates/oracle_falsifiability.py` and its own test suite are unaffected by this change:
the toy spec's `solve.sh` is still an un-authored Slice D stub on all three arms, so the
gate still (correctly, per its own documented convention) reports `NOT_AUTHORED`
rather than exercising this path — `make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml`
re-run clean after both fixes above.

---

## Amendment 5 (2026-08-06) — generator/schema fixes from a third benchmark-integrity
## review (findings G1-G4)

Four findings from a third review pass, scoped to the generator/schema half of Slice C.
Fixed together; `make gen`/`make test-gates`/`make check` all re-run clean after all four
(164 gates/metrics tests unchanged; `oracles`' own 63-test suite, unaffected by prior
amendments, needed one update for a renamed assert, see G2).

### G1 — offline-plan fixture lived inside the agent-editable `entry_file` on both TF arms

**Finding:** `hcl_raw`'s `main.tf` (entry_file) carried its own `provider "aws" {}` block
+ `skip_*`/dummy-credential fixture inline; `terraconstructs`' `main.ts` (entry_file)
carried both the `App`/`providerConfig` bootstrap (same fixture, plus the mock-STS
`endpoints` pointer) AND the `ScenarioStack` class body in one file. An agent fully
rewriting its own `entry_file` from scratch — ordinary, expected behavior; the
instruction never mentions the fixture at all — silently deleted it, and `terraform
plan` then failed offline with `Error: No valid credential sources found` (hcl_raw) or a
403 against real STS (terraconstructs), scoring an otherwise-CORRECT solution `0.0`.

**Reproduced before the fix:** a bare, oracle-correct `main.tf` (three resources, no
provider block) against the pre-fix single-file `hcl_raw` workspace:
```
$ terraform plan
Error: Invalid provider configuration
Error: No valid credential sources found
```

**Fix:** split each TF-shaped arm's workspace into an agent-owned `entry_file` and a
separate, non-agent-owned bootstrap file the generator never treats as `entry_file`:
- `hcl_raw`: new `arms/hcl-raw/environment/workspace/provider.tf` (the bootstrap, byte-
  copied unmodified per scenario) alongside a `main.tf` that is now resource-blocks-only
  (`generator/gen.py::hcl_raw_main_tf()`).
- `terraconstructs`: `output_contract.entry_file` moved from `main.ts` to
  `lib/scenario-stack.ts` (new `generator/gen.py::terraconstructs_stack_skeleton()`,
  mirroring `awscdk`'s `bin/app.ts`/`lib/scenario-stack.ts` split exactly); `main.ts` is
  now App/`providerConfig`-bootstrap-only, regenerated every run
  (`terraconstructs_main_ts()`), never `entry_file`. `write_environment()` now asserts
  this shape for `terraconstructs` (`entry_rel == "lib/scenario-stack.ts"`), mirroring
  the pre-existing `awscdk` assert. The arm's own dev-image preflight app
  (`arms/terraconstructs/environment/app/`) was moved to the same two-file shape
  (`main.ts` importing `lib/scenario-stack.ts`'s `PreflightStack`) so `make preflight`
  exercises the split for real, not just generated tasks.
- Every generated `instruction.md` now names both files explicitly
  (`generator/gen.py::ownership_note()`, new, threaded into the §2.1 assembly template
  right after the language line): "You own only `<entry_file>`... Do not create, modify,
  or delete `<bootstrap file>`."

**Proven** (both TF arms, `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml` regenerated
output): simulated a full-rewrite agent by overwriting the generated task's own
`main.tf` / `lib/scenario-stack.ts` with a bare, oracle-correct, zero-offline-config
solution and running `terraform init && terraform plan` against the untouched
`provider.tf` / `main.ts`:
- `hcl_raw`: `terraform plan` → `Plan: 3 to add, 0 to change, 0 to destroy` (previously:
  `No valid credential sources found`).
- `terraconstructs`: `cdktn synth` → `terraform init && terraform plan` (against a
  locally-started `mock-sts.js`, matching the untouched `main.ts`'s `endpoints.sts`
  pointer) → `Plan: 3 to add, 0 to change, 0 to destroy` (previously: 403 against real
  STS, no credentials).

### G2 — SCHEMA.md §4.2's "one tf_jsonpath, same shape, both TF arms" claim was false

**Finding:** for a plan-time-UNKNOWN attribute (an `aws_iam_role_policy.policy`
`jsonencode(...)`/equivalent whose `Resource` references another resource's
provider-computed `.arn`), `terraform show -json` plan output's
`.planned_values...values.policy` resolves to nothing at all — not "wrong value", no
node. `specs/_toy/toy-ssm-parameter.yaml`'s `policy-actions-read-only` tier-1 assert
targeted exactly this path; a Rego rule written against it (as the original
`rego_hints`/`oracles/emit.py` scaffold pointed at) could never fire against a correct,
`.arn`-referencing solution — silently as vacuous as `default allow := true` — and
nothing had ever caught this, because tier-1 paths were never resolved against anything
(tier-1 is Rego/cfn-guard-graded, not executed by the jq-based tier-0 evaluator).

**Reproduced** directly against real `terraform show -json` plan output, both TF arms
(a hand-run `hcl_raw` fixture and a hand-run `terraconstructs` L1-provider-construct
fixture, both referencing the created SSM parameter's `.arn`):
```
$ jq '.planned_values.root_module.resources[]
      | select(.type=="aws_iam_role_policy") | .values.policy' plan.json
null
```

**Fix:**
1. `specs/SCHEMA.md` §4.2 gets a new §4.2.1 documenting the mechanism (plan-time-unknown
   contagion through `jsonencode`/equivalent), the fix pattern (graph-edge checks use
   `.configuration...expressions.<attr>.references`, which is populated from HCL source,
   not provider computation, and is plan-time-known regardless of the referenced value's
   own knownness — verified: resolves to the created-resource address for a correct
   fixture, to nothing at all for a hardcoded-wildcard one), and a new authoring rule
   (never mark tier "0" an attribute that can be plan-time-unknown).
2. `specs/_toy/toy-ssm-parameter.yaml`'s `policy-resource-scoped-not-wildcard` split into
   `policy-resource-scoped-not-wildcard-cfn` (`applies_to: [awscdk]`, unchanged literal
   check — CFN synth is always fully static, never has this problem) and
   `-tf` (`applies_to: [hcl_raw, terraconstructs]`, now a references-based graph-edge
   check). `policy-actions-read-only` keeps its `values.policy`-based check (a genuine
   value-content fact with no plan-time-known graph-edge equivalent) but now carries an
   explicit caveat + matching `rego_hints`: it only resolves when the reference solution
   keeps the referenced ARN attribute plan-time-known (e.g. the parameter's own `.name`,
   an agent-supplied literal echo, not its computed `.arn`) — a documented, known v1 scope
   limitation, not something papered over.
3. New generator-time check, `generator/check_reference_paths.py` (`make check-paths
   SPEC=...`): resolves EVERY declared `structural_assert` (tier "0" and "1" alike)
   against a real synthesized/planned artifact, built by running each arm's real
   toolchain against a hand-authored, oracle-correct reference fixture
   (`generator/tests/fixtures/<spec-id>/<arm>/`) — reusing the generated task's own,
   already-generated `tests/_assert_lib.sh`/`assert_check` (the same jq-compiled
   evaluator every trial's tier-0 actually runs), not a second Python-side evaluator.
   Not wired into `make check`/`test-gates` (requires host terraform/node/npm/jq, same
   as `make falsifiability`). Along the way this check also found and fixed two
   PRE-EXISTING, independent bugs in the same two tier-1 `cfn_jsonpath`s (never
   previously resolved against a real template either): `.Properties.Policies[*]` +
   `|| @.Type=='AWS::IAM::Role'` crashed jq (`Cannot iterate over null`) against the
   `AWS::IAM::Policy` shape a real `role.addToPolicy()` solution actually produces
   (narrowed to that shape); and `policy-actions-read-only`'s `tf_jsonpath` was missing
   `|fromjson.Statement[*].Action` (comparing a raw JSON string against a list with
   `op: in`, which can never match).

**Proven:** `make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml` — all 18
applicable (structural_assert × enabled-arm) checks PASS, tier-0 and tier-1 alike,
across all three arms, against hand-authored reference fixtures.

### G3 — mock-sts startup had no readiness probe

**Finding:** `generator/gen.py`'s terraconstructs `tf-plan` step started `mock-sts.js`
in the background and `sleep 0.3`'d, unconditionally. EADDRINUSE (a leftover process
from a prior run in the same container/host — the falsifiability gate's own
solve.sh-then-broken/solve.sh sequence is exactly this scenario) or a slow bind under
load meant `terraform plan` could run before the responder was listening, fail against
nothing (connection refused, same shape as a genuinely-missing fixture), and score
`0.0` — indistinguishable in the logs from a bad SOLUTION, when it was broken TEST
INFRASTRUCTURE.

**Fix:** poll `127.0.0.1:<port>` (bash's own `/dev/tcp`, no extra tool) for up to 5s
(50 × 0.1s) before ever invoking `terraform plan`. On timeout, write
`/logs/verifier/tf-plan-mock-sts-unavailable` (mirroring `tier1-unavailable`'s role for
`TOOL_MISSING`) instead of silently falling through to a plan attempt that can only
fail — `reward.txt` still ends up `0.0` (same mechanism as every other toolchain-step
failure), but the marker makes this run-invalidating, not a genuine bad-solution
signal, in any downstream log analysis.

**Proven:** regenerated `tests/static_tiers.sh` for `toy-ssm-parameter-terraconstructs`
contains the poll loop (`grep -c MOCK_STS_READY` → 2, one in the preview echo + one in
the real command, `bash -n` clean); exercised for real (mock-sts started and ready well
within 5s) as part of every G1/G2 proof run above — the terraconstructs `tf-plan` step
never needed to fall back to the timeout path in any of those runs, confirming the
readiness probe doesn't regress the happy path.

### G4 — `tasks/anchor/smoke/environment` had drifted from `arms/awscdk/environment`

**Finding:** `ci/check-smoke-drift.sh` (`make check`) was red — `arms/awscdk`'s
Dockerfile gained a pinned `cfn-guard` install step (a prior amendment, "Tier-1 grading
tools installed in every arm image") that the hand-maintained
`tasks/anchor/smoke/environment/Dockerfile` byte-copy never picked up.

**Fix:** re-synced the copy — added the same `ARG TARGETARCH` + sha256-verified
`cfn-guard` install `RUN` block (byte-identical body text, since `check-smoke-drift.sh`
only allows the LEADING comment header to diverge, confirmed by re-running the diff
after a first attempt that adjusted an in-body relative path and got correctly flagged)
and the matching `cfn-guard 3.2.0` bullet in the leading header's pinned-toolchain list.

## Amendment 6 (2026-08-06) — grading-half fixes: the falsifiability-gate blocker and
## the constant-zero-reward major (findings F1, F2)

Two findings from a fourth review pass, scoped to whether this benchmark can grade
anything at all end-to-end. Fixed together.

### F1 (blocker) — `gates/oracle_falsifiability.py`'s `_run_solve` never actually ran
### against a real sandbox

**Finding:** `_run_solve` copied `task/environment` (the WHOLE dir — `workspace/` +
`fixtures/` + `mirror-src/` + `preflight.sh` + `terraformrc` for hcl_raw; the analogous
per-arm layout for the others) into the scratch sandbox wholesale, landing the arm's
real entry_file/bootstrap files one directory level too deep
(`<sandbox>/workspace/main.tf` instead of `<sandbox>/main.tf`). The patched
`tests/static_tiers.sh` it then ran (`cd /app/project` rewritten to the sandbox root)
reads `main.tf`/`cdk.out/...`/etc directly at that root — so `terraform init`/`cdk
synth` always ran against a directory with no source files in it, and **no** authored
`solve.sh`, however correct, could ever score above `0.0`. The gate only ever "passed"
via its `NOT_AUTHORED` escape hatch (no scenario had an authored `solve.sh` yet), which
is exactly how this shipped unnoticed.

**Fix:** reused `generator/check_reference_paths.py`'s own already-correct
`_prepare_project` pattern (added in Amendment 5, G2) — copy
`environment/<ARM_WORKSPACE_SUBDIR[arm]>` (re-importing that constant from `gen.py`;
`workspace/` for awscdk/hcl_raw, `app/` for terraconstructs — the exact per-arm mapping
every arm's own Dockerfile's `COPY` lines encode) onto the sandbox ROOT, then overlay
`tests/`/`solution/` as before. Also runs `npm ci` in the sandbox when a `package.json`
lands there (awscdk/terraconstructs ship `node_modules` only inside their Docker image,
built at image-build time — the host sandbox needs it installed for real, same as
`check_reference_paths.py`).

**Self-test added** (`gates/tests/test_oracle_falsifiability.py`, per the finding's own
ask "the gate's own regressions must be visible"): runs the REAL gate against the toy
spec's now hand-authored `hcl_raw` reference solution and asserts reward `1.0`, plus a
second test asserting every `broken/<catch>/` fixture scores `0.0`. A regression back to
copying the whole `environment/` dir turns both tests red immediately.

**Proven:** `make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml` — all 9 outcomes
(3 arms × {good solve.sh, 2 broken/<catch> fixtures}) `PASS`, reward `1.0`/`0.0`/`0.0`
per arm, **no `NOT_AUTHORED` anywhere** — the escape hatch this finding named is no
longer load-bearing for this spec.

### F2 (major) — tier-1 policies were still generator stubs; nothing proved any arm
### GRADEABLE

**Finding:** `oracles/rego/toy-ssm-parameter/policy.rego` and
`oracles/cfn-guard/toy-ssm-parameter/policy.guard` were still `GENERATOR-STUB`
skeletons; the (correct, fail-closed) `SKIPPED_STUB` behavior zeroed every trial's
reward regardless of solution quality. Nothing demonstrated any arm could reach a
nonzero, correct reward.

**Fix:**
- Hand-authored both policies for real. `policy.rego` (package
  `cdktn_bench.toy_ssm_parameter`, one bundle graded against BOTH TF arms' `terraform
  show -json` plan JSON, per spec) encodes the graph-edge check
  (`policy-resource-scoped-not-wildcard-tf`, reading
  `.configuration...expressions.policy.references` per the G2 fix, including one hop
  through a `data.aws_iam_policy_document` indirection) and the action-allowlist check
  (`policy-actions-read-only`, only asserted when `values.policy` is plan-time-known,
  per the spec's own CAVEAT). `policy.guard` encodes the CFN-side equivalents at the
  same strictness (`Resource == "*"` / `Action[*] IN [...]` over
  `AWS::IAM::Policy.Properties.PolicyDocument.Statement`) — had to select-then-`empty`
  rather than `!=` for the wildcard check: cfn-guard's `!=` on a real-shaped `Resource`
  (an `Fn::Join` intrinsic object on the correct fixture) threw `ComparisonError: not
  comparable map, String` and FAILED a correct solution; a filter (`Statement[ Resource
  == "*" ]`) followed by an emptiness check sidesteps the type-mismatch entirely.
  Verified directly with `opa eval`/`cfn-guard validate` against real synth/plan output
  from both a hand-authored correct fixture and a wildcard-policy negative, for every
  arm, before wiring anything.
- **New finding surfaced while authoring this:** the `parameter-tier-enum` catch
  declared `predicted_tier_caught: "0"` for every arm but had **no** corresponding
  `oracle.structural_assert` at all — an unfalsifiable catch by construction (its own
  description even said so: "not used as a real discriminator... exists purely so the
  generator has a typed-value-trap-taxonomy catch to render"). Added the missing
  tier-`"0"` assert (`parameter-tier-standard`, `op: not_exists` on `Properties.Tier` /
  `values.tier` — verified directly that an omitted Tier is genuinely ABSENT from both a
  synthesized CFN template and a `terraform show -json` plan, not a static `"Standard"`
  literal either tool fills in, so `not_exists` — not `eq "Standard"` — is the sound
  check) so this catch is now genuinely gradeable instead of illustrative-only.
- Hand-authored `solution/solve.sh` (oracle-correct) for all three arms, plus
  `solution/broken/<catch>/solve.sh` for both declared catches × three arms (six
  negative fixtures) — required by `gates/oracle_falsifiability.py`'s own per-catch
  contract, now satisfiable end-to-end for the first time.
- New `gates/grading_proof.py` / `make grading-proof SPEC=...`: reuses
  `gates.oracle_falsifiability.check_arm` (the F1-fixed sandbox path) to assert, per
  enabled arm, the correct solution scores `1.0` and the `policy-scoped-to-parameter`
  negative (the exact "wildcard IAM inline_policy
  `Action:['ssm:*','iam:*','s3:*'],Resource:'*'`" case named in the finding) scores
  `0.0` — six outcomes for this 3-arm spec, printed as a compact summary table.

**Proven — all six `grading-proof` outcomes:**
```
[PASS] awscdk           correct solution             reward=1.0
[PASS] awscdk           negative (policy-scoped-to-parameter) reward=0.0
[PASS] hcl_raw          correct solution             reward=1.0
[PASS] hcl_raw          negative (policy-scoped-to-parameter) reward=0.0
[PASS] terraconstructs  correct solution             reward=1.0
[PASS] terraconstructs  negative (policy-scoped-to-parameter) reward=0.0
```

### Final state

- `make test-gates` (`uv run pytest gates metrics -q`) — **166 passed** (164 prior +
  the 2 new `gates/tests/test_oracle_falsifiability.py` self-tests).
- `make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml` — green **for real**, no
  `NOT_AUTHORED` escape; 9/9 outcomes `PASS`.
- `make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml` (new) — 6/6 outcomes
  `PASS`.
- `make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml` — 21/21 green (also updated
  the `hcl_raw` `bad/` reference fixture to add `tier = "Advanced"` alongside its
  existing wildcard policy, so the new `parameter-tier-standard` assert's
  bad-fixture-discriminates informational check stays meaningful rather than passing
  vacuously).
- `make check` — green (schema validation + 166 tests + smoke-drift OK).
- `uv run pytest gates metrics oracles test -q` — **261 passed** (broader suite;
  `oracles/tests/test_structural.py`'s toy-spec integration tests updated for the fifth
  tier-0 assert, same as Amendment 5's precedent for a renamed assert).

**Proven:** `bash ci/check-smoke-drift.sh` → `smoke-drift: OK`; `make check` green.

## Amendment 7 (2026-08-06) — residual-findings fixes

Five findings closed together: two code-level fixes that shipped in the same
round as Amendment 6's F2 (IAM-shape-coverage widening of
`oracles/rego/toy-ssm-parameter/policy.rego`) but were never logged here —
this entry backfills that gap, which is itself the first finding closed
below — plus three follow-on hardening fixes making the `not_verifiable`/
`tier1-not-verifiable` contract those two code fixes introduced actually
documented outside the one hand-authored toy policy, and actually consumed
on the metrics side instead of written-and-ignored.

### R1 — `absent_or_eq`: `parameter-tier-standard` false-negatived a
### semantically-correct explicit-default solution

**Finding:** `parameter-tier-standard` used `op: not_exists` on the SSM
parameter's `Tier` to catch the `parameter-tier-enum` wrong-value catch.
PROVEN on `hcl_raw`: a solution identical to the reference `solve.sh` except
for writing an explicit `tier = "Standard"` (semantically identical to
omitting the field — the instruction never mentions a tier) produced `FAIL
[parameter-tier-standard]: op=not_exists expected=null resolved=["Standard"]`,
`tier0_pass=0`, `reward=0.0` — despite being exactly as correct as the
omitted form. Arm idioms differ in how readily they emit explicit defaults,
so this injected a per-arm scoring bias into the exact cross-arm comparison
this benchmark exists to measure, not just a theoretical edge case.

**Fix:** added a new `op: absent_or_eq` to `specs/SCHEMA.md` §4.2's op
table: passes when the path resolves to 0 nodes (omitted) OR exactly 1 node
equal to `expected` (explicit, semantically-identical value); >1 resolved
nodes fails, same ambiguity rule as `eq`. Implemented identically across
both evaluators (`oracles/lib/structural.py`'s `resolve`/op-dispatch and
`generator/jsonpath_jq.py`-compiled tier-0 jq path via
`generator/gen.py`'s assert-call emission), proven to agree via
`oracles/tests/test_op_parity.py`'s dedicated `absent_or_eq` cases (CFN
omitted-key, CFN explicit-match, CFN explicit-mismatch, TF `null`-filtered).
`specs/_toy/toy-ssm-parameter.yaml`'s `parameter-tier-standard` assert
switched from `not_exists` to `absent_or_eq` (`expected: "Standard"`) —
still correctly rejects the wrong-enum-value catch (`Advanced`/
`IntelligentTiering` resolves to 1 node not equal to `"Standard"` → fails,
unchanged from before) while now also accepting the explicit-default form.
The assert's own `description` was corrected too: the old text claimed this
assert "only rejects the wrong-enum-value catch case", which was never true
of `not_exists` (SCHEMA.md's general `op` contract only ever documented
"0 nodes = pass" for `not_exists`, full stop — there was never a carve-out
for "unless the resolved value happens to equal the default").

**Proven:** the hand-run explicit-`tier = "Standard"` hcl_raw fixture now
scores `tier0_pass=1`/`reward=1.0`; the `parameter-tier-enum` broken fixture
(wrong enum value) still scores `reward=0.0` for all three arms per `make
falsifiability` (below).

### R2 — tier-1 oracle vacuity: IAM shape coverage, and the falsifiability
### gate's `broken/<dir>/` discovery convention that proves it

**Finding:** every `deny` rule in `policy.rego` filtered
`resources[].type == "aws_iam_role_policy"` only. A standalone/managed
`aws_iam_policy` (`Action:"*"`/`Resource:"*"`) attached to the role via a
*separate* `aws_iam_role_policy_attachment` resource — an equally idiomatic
Terraform shape, and the shape `terraconstructs`' own `iam.Role.
addToPolicy()` L2 helper is not the only path to — scored `tier1_status=
PASS` regardless of how wide-open its policy was. PROVEN vacuous directly:
```
$ opa eval -f raw -I -d policy.rego 'data.cdktn_bench.toy_ssm_parameter.deny' \
    < <(terraform show -json against a wildcard aws_iam_policy +
        aws_iam_role_policy_attachment plan)
[]
```

**Fix:** widened the collection every `deny` rule iterates from
`role_policies`/`planned_role_policies` (`aws_iam_role_policy` only) to
`policy_resources`/`planned_policy_resources` (`aws_iam_role_policy` OR
`aws_iam_policy` — both shapes attribute the policy document JSON at the
same `.expressions.policy`/`.values.policy` paths, so every existing rule
body needed zero further changes), plus a new `role_has_no_recognized_policy`
deny that fails closed when an `aws_iam_role` exists but no resource of
either recognized shape does at all (the comprehension-based rules are
vacuously silent on an empty `policy_resources` list — "some rp in [] ..."
can never generate a violation — so that gap needed its own rule, not just a
wider collection). Two new negative fixtures added:
`solution/broken/policy-scoped-to-parameter-alt-shape/` (the exact
`aws_iam_policy` + `aws_iam_role_policy_attachment` shape from the
reproduction) for all three arms — deliberately **not** named after a
declared `catches[].name`, to exercise (and lock in) a convention
`gates/oracle_falsifiability.py::check_arm` already had implicitly but had
never been required to actually prove: any directory under
`solution/broken/` **not** matching a declared catch name is still
discovered (`sorted(broken_dir.iterdir())`, skipping only names already
covered by a catch) and still required to score `reward == 0.0`. This
matters beyond this one fixture: it means catching "an alternate, equally-
idiomatic IAM shape hits the same violation" never depended on inventing a
new named catch in the spec just to get gate coverage — a future scenario's
policy bundle can be proven against as many alternate-shape negatives as its
author writes, with no `catches[]` schema pressure to name each one, and a
future regression that re-narrows the policy bundle back to a single shape
turns this gate red instead of silently losing coverage no catch name names.

**Proven:** `make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml` —
the alt-shape fixture scores `reward=0.0` for all three arms (see the 12/12
transcript in "Final state" below — includes it as a fourth, non-catch-named
outcome per arm alongside `solve.sh` and the two `catches[]`-named
`broken/`s).

### R3 — `not_verifiable`: the tier-1 action-allowlist check silently
### skipped whenever the policy referenced a computed ARN

**Finding:** `policy-actions-read-only`'s `deny` rule only evaluates when
`values.policy` is plan-time-known (`pv.values.policy != null` guard, per
the spec's own CAVEAT and the G2 fix, Amendment 5). PROVEN: an `hcl_raw`
solution with `Resource = aws_ssm_parameter.greeting.arn` and `Action =
["ssm:*", "iam:*", "s3:*"]` — the exact wildcard action set the
`policy-scoped-to-parameter` negative fixture uses, just referencing `.arn`
instead of `.name` — leaves `values.policy` plan-time-unknown
(`specs/SCHEMA.md` §4.2.1). The graph-edge rule (`policy-resource-scoped-
not-wildcard-tf`) still passes (the `.arn` reference IS present, so this is
a legitimately-scoped solution by that check), tier-0 passes, and — before
this fix — nothing anywhere recorded that the action allowlist was never
actually checked for it. `specs/SCHEMA.md` §4.2.1 option 3 mandates this be
"logged, not silently denied OR silently allowed"; the policy already did
the correct *allow* half (an unverifiable fact must not be guessed as a
denial) but was silent about it, which is the part this fix closes.

**Also decided, same finding: §4.2.1 option 1 (narrow the scenario so the
attribute stays fully static) was considered and explicitly NOT pursued for
`policy-actions-read-only`.** `.configuration...expressions.policy` (option
1's plan-time-known alternative source) was checked directly as a possible
Action-list source and verified to not carry one: a `jsonencode(...)` call
collapses to a bare references list in Terraform's own configuration JSON,
nothing else survives:
```
$ jq '.configuration.root_module.resources[]
      | select(.type=="aws_iam_role_policy") | .expressions.policy' plan.json
{"references": ["aws_ssm_parameter.greeting.arn", "aws_ssm_parameter.greeting"]}
```
No nested `Action`/`Statement` structure exists at that path for *any*
`jsonencode`'d policy, correct or not — there is no way to recover "just the
statically-known parts" of an encoded attribute from `.configuration` any
more than from `.planned_values`, so narrowing the scenario further (option
1) would not have helped this specific check, and splitting into two
per-artifact-family asserts (option 2) doesn't apply either since this is a
TF-only check (`applies_to` never includes `awscdk` here — CFN has its own,
always-static `policy-resource-scoped-not-wildcard-cfn` equivalent, and
`awscdk`'s `policy-actions-read-only` copy is graded off the same fully-
static `cfn_jsonpath`, no plan-JSON gap). Option 3 (document + log
non-silently) is therefore the only one of the three that actually closes
this gap for this assert — recorded here so a future contributor doesn't
re-spend the investigation.

**Fix:** added a second, non-`deny` top-level Rego set, `not_verifiable`,
to `oracles/rego/toy-ssm-parameter/policy.rego` — fires exactly when the
graph-edge check already passed but the encoded `policy` value is
plan-time-unknown (`object.get(pv.values, "policy", null) == null`, not
`pv.values.policy == null` — an attribute whose entire value is
plan-time-unknown is *omitted* from real `terraform show -json` output, not
present-with-literal-null; `pv.values.policy == null` would silently never
match an omitted key either, the same silent-skip class of bug this whole
fix exists to close, caught here before shipping by running it against a
real plan.json). `generator/gen.py::build_static_tiers_sh` evaluates
`data.cdktn_bench.<pkg>.not_verifiable` (captured to a variable first, not
piped straight through `jq -e`, since a `policy.rego` that never defines
this optional rule makes `opa eval` print nothing at all — not `"[]"` —
which would otherwise make a naive `jq -e 'length==0'` check FAIL and write
a false marker on every scenario that simply hasn't adopted the rule yet)
and, when non-empty, tees the detail to `/logs/verifier/tier1-not-verifiable`
— mirroring the existing `tier1-unavailable`/`tf-plan-mock-sts-unavailable`
non-silent-marker convention (Amendments 4–6). Non-gating by construction:
does not affect `tier1_status` or `/logs/verifier/reward.txt` either way.

**Proven:** a hand-run `.arn`-referencing wildcard-action fixture (the exact
reproduction above) now fires `not_verifiable` non-empty where it used to be
silent, teed to `/logs/verifier/tier1-not-verifiable`, while `tier1_status`
stays `PASS`/`reward=1.0` for that same fixture (unaffected — the point of
the fix is recording the gap, not gating on it). `policy-actions-read-only`
still correctly `deny`s the plan-time-known wildcard case (the
`policy-scoped-to-parameter` catch, `.name`-referencing) — see the
`grading-proof`/`falsifiability` transcripts below, both green.

### R4 — the `not_verifiable`/`tier1-not-verifiable` contract R3 introduced
### was undocumented outside the one hand-authored toy policy

**Finding:** R3's fix (rule name, marker path, non-gating semantics, the
`opa eval` "prints nothing, not `[]`" gotcha) existed only as inline
comments in `oracles/rego/toy-ssm-parameter/policy.rego` and
`generator/gen.py::build_static_tiers_sh`. `specs/SCHEMA.md` §4.2.1's
option-3 bullet — the exact place a future scenario author would look when
deciding whether their new tier-1 assert needs this — said only "document
the gap ... Slice D's Rego must treat [it] as not independently verifiable",
with no mention of a `not_verifiable` rule, its name, or where its output
lands. A hand-authored `policy.rego` for the next scenario with this same
gap shape had nothing to copy from and no schema-level nudge to define one.

**Fix, three parts:**
- `specs/SCHEMA.md` §4.2.1's option-3 bullet now names the contract
  directly: an optional top-level `not_verifiable` set alongside `deny`, a
  worked Rego snippet, and the exact marker path
  (`/logs/verifier/tier1-not-verifiable`) the generated `static_tiers.sh`
  tees it to — plus an explicit pointer to
  `oracles/rego/toy-ssm-parameter/policy.rego`'s real rule and
  `oracles/emit.py`'s scaffolded placeholder (next bullet) as the two
  worked examples.
- `oracles/emit.py::_render_rego_skeleton` now scaffolds an empty
  `not_verifiable contains msg if { false; msg := "" }` placeholder + a
  `TODO(Slice D, optional)` comment block into every freshly-generated
  `policy.rego`, alongside the existing `allow`/`deny` placeholder — so
  every *new* scenario's policy starts from a file that already has
  somewhere to put this rule, closing the gap going forward without
  touching any already-hand-authored policy (`emit_oracles()` never
  overwrites an existing `policy.rego`, unchanged from Amendment 3/§8.2
  rule 7). Verified the new skeleton is still syntactically valid Rego
  (`opa check`) and that `oracles/tests/test_emit.py`'s existing
  content/idempotency/`opa check` suite stays green unmodified.
- `generator/gen.py` gained `check_not_verifiable_coverage(spec)`, called
  from `generate()` right after oracle emission: for every tier-"1"
  `structural_assert` whose `tf_jsonpath` reads a `.planned_values...
  values.<attr>` shape (`specs/SCHEMA.md` §4.2.1's plan-time-unknown-prone
  pattern), warn on stderr (`make gen`/`make gen-all`, non-fatal — a
  missing rule is not itself proof of a bug, e.g. an `awscdk`-only tier-1
  assert never needs one) if the scenario's `oracles/rego/<id>/policy.rego`
  defines no `not_verifiable` rule at all (regex match on the rule head,
  `contains`/`[`/`:=` forms — a static generation-time heuristic, not a
  substitute for `build_static_tiers_sh`'s own real `opa eval` at trial
  time). Verified against the real toy spec (clean, no warning — its
  `policy.rego` already defines the rule) and against a temporary, restored
  copy of that same `policy.rego` with the rule head renamed to disable the
  match (warning fires, names the exact assert and path).

**Proven:** `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml` regenerates
cleanly with no warning and no on-disk diff outside the three files this fix
touched (`git status --short` showed only `generator/gen.py`,
`oracles/emit.py`, `specs/SCHEMA.md` modified — no generated `tasks/`/
`oracles/toy-ssm-parameter/` drift). `oracles/tests/test_emit.py` — 9/9
green.

### R5 — the `tier1-not-verifiable` marker R3 introduced was consumed by
### nothing, biasing per-arm scoring data

**Finding:** R3 made the tier-1 not-independently-verifiable fact
non-silent *in the trial's own logs*, but nothing downstream ever read
`/logs/verifier/tier1-not-verifiable` back out. Consequence: a trial whose
tier-1 action-allowlist was never actually checkable from plan JSON (an
entirely normal, idiomatic Terraform pattern — referencing another
resource's computed output) is indistinguishable, in the published
`metrics/result_schema.json` row, from one where tier-1 WAS fully evaluated
and passed. Concretely: the identical wildcard-IAM violation
(`Action:["ssm:*","iam:*","s3:*"], Resource: <computed ARN>`) scores
`reward=0.0` on `awscdk` (cfn-guard has no plan-time-unknown concept — CFN
synth is always fully static) but `reward=1.0` on `hcl_raw`/
`terraconstructs`, with nothing in the row itself showing that the TF arms'
`reward=1.0` came with tier-1 unchecked, not tier-1-passed. A downstream
analysis pooling per-arm reward without this signal would read that as
`awscdk` being stricter/worse, not as "the TF arms' tier-1 check for this
trial never ran."

**Fix:** `gates/emit_result.py` gained `read_tier1_not_verifiable(trial_dir)`
— reads the host-side `<trial_dir>/verifier/tier1-not-verifiable` (the
`verifier/` bind-mount is Harbor's own `TrialPaths.verifier_dir`, host
mirror of the in-container `/logs/verifier`, exactly the same host/
container path convention `classify_infra_failure` already relies on for
`/logs/agent`) and returns `(present: bool, detail: str | None)`.
`build_result_record()` now always attaches `tier1_not_verifiable`/
`tier1_not_verifiable_detail` to every record (same "always attached
regardless of validity_class" treatment as `audit`/`infra` — the marker is
a fact about the trial's own logs, independent of whether the toolchain
audited as genuine). `to_result_row()` surfaces `tier1_not_verifiable` as a
**REQUIRED** schema field (default `false` when no marker was found — same
producer-side "always emitted, no JSON-Schema `default` keyword needed"
shape as the existing `censored` field) plus an optional
`tier1_not_verifiable_detail` string when the marker had content.
`metrics/result_schema.json` gained both properties, with
`tier1_not_verifiable` added to `required` and its description stating
downstream analysis must flag/segment `true` rows separately — pooling them
with `tier1_not_verifiable=false` rows silently reintroduces the exact bias
this field exists to surface. `metrics/examples/valid-result.json` and
`metrics/test_validate_result.py`'s `VALID_ROW`/missing-field parametrize
list updated to keep the now-required field present everywhere a row is
asserted valid.

**Tests added** (`gates/tests/test_emit_result.py::TestTier1NotVerifiableMarker`,
11 cases; `metrics/test_validate_result.py`, 3 cases): marker absent (the
untouched checked-in `genuine/` fixtures) → `tier1_not_verifiable is False`,
no detail, on both the raw record and the schema-validated row, for all
three arms. Marker present (a `tmp_path` copy of the `genuine` fixture with
a `verifier/tier1-not-verifiable` file added — the checked-in fixtures
themselves are never mutated) → `True` + detail text, for all three arms,
still schema-valid. Also covers: an empty-but-present marker file → `True`
with no detail; the marker never affects `validity_class`/`reward` either
direction; and a marker present on an otherwise-`invalid-bypass` trial is
still recorded on the record (`read_tier1_not_verifiable` only looks at the
file, independent of audit/validity) even though that row's score fields
stay zeroed.

**Proven:** `gates/tests/test_emit_result.py` — 46/46 green (35 prior + 11
new). `metrics/test_validate_result.py` — all green (schema round-trip
covers `tier1_not_verifiable`'s boolean-type check, the true+detail case,
and detail-without-the-flag staying schema-valid per its own "never
schema-enforced" description). `make check` (`check-result-schema` +
`test-gates`) green end-to-end, including `metrics/emit_fixture_rows.py`'s
real gate-fixture round-trip through the now-required field.

### Final state

- `make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml` — **12/12**
  outcomes `PASS` (3 arms × {good `solve.sh`, `parameter-tier-enum` broken,
  `policy-scoped-to-parameter` broken, `policy-scoped-to-parameter-alt-shape`
  broken} — the fourth, non-catch-named outcome per arm is R2's discovery-
  convention fixture).
- `make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml` — **6/6**
  outcomes `PASS` (unchanged from Amendment 6 — correct solution
  `reward=1.0` + `policy-scoped-to-parameter` negative `reward=0.0`, all
  three arms).
- `make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml` — **21/21**
  green (7 asserts × 3 arms, tier-0 and tier-1 alike, unchanged path shapes
  — none of R1–R5 touched a declared `tf_jsonpath`/`cfn_jsonpath`).
- `uv run pytest gates metrics -q` (`make test-gates`) — **181 passed**
  (166 prior + 15 new: 11 from `TestTier1NotVerifiableMarker`, 3 from
  `metrics/test_validate_result.py`'s new `tier1_not_verifiable` cases, 1
  from the widened missing-required-field parametrize list).
- `uv run pytest gates metrics oracles test -q` — **280 passed** (broader
  suite; 265 prior + the same 15 new — R1–R4 needed no new test-suite
  entries: R1/R2/R3 predate this entry and already had `oracles/tests/
  test_op_parity.py`/`test_structural.py` coverage baked into the 265, and
  R4's `check_not_verifiable_coverage` is proven by the manual `make gen`
  transcript above, the same convention `check_reference_paths.py`/
  `oracle_falsifiability.py` already use for host-toolchain-dependent
  checks that aren't wired into `test-gates`).
- `make check` — green (schema validation, including the now-required
  `tier1_not_verifiable` field, + 181 tests + smoke-drift OK).

**Proven:** `bash ci/check-smoke-drift.sh` → `smoke-drift: OK`; `make check`
green.
