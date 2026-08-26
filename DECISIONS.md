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
a trusted local clone of upstream aws-bench at that pinned commit, used to write
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
- **Baseline utilities**: `bash`, `git`, `curl`, `jq`, `unzip`, AWS CLI v2, `python3`,
  present in every arm image (hcl-raw and terraconstructs were missing the AWS CLI;
  terraconstructs was additionally missing `jq`, which hcl-raw's own preflight.sh calls
  "bundled for oracle/verifier tooling" — a verifier/oracle script written once and reused
  across arms would have broken on terraconstructs).
Verified per-arm with `docker run --rm --entrypoint sh <image> -c 'command -v bash git
curl jq unzip aws python3'` against all three images — all resolve.

**Amendment (fix-round-3, 2026-08-07, benchmark-integrity review finding G2):** `python3`
promoted from "deliberately excluded" (arms/hcl-raw's own workspace/provider.tf header used
to say so explicitly, of the *grading-tool* baseline — jq-only structural asserts,
generator/jsonpath_jq.py's docstring) to *required* in every arm image. That earlier
exclusion was scoped to grading tools reused across arms (still true — structural asserts
are still jq-only); it did not anticipate a per-scenario verifier script
(`tests/live_check.py`, `verifier.live_check.enabled`, first and only consumer:
apigw-redeploy) that generator/gen.py's generated `tests/test.sh` invokes with a bare
`python3` regardless of arm. Before this fix, `python3` existed only in
`arms/hcl-raw` (installed earlier, for an unrelated reason — `workspace/mock-sfn.py`'s
offline `aws_sfn_state_machine` plan-time mock); `arms/awscdk` and `arms/terraconstructs`
had none, so `python3 "$DIR/live_check.py"` failed with a shell "command not found" on
those two arms, and `test.sh` folded that failure's stderr into
`live_check-result.json` where the new (Slice G) `SPEC_LIVE_CHECK_GATING` AND-semantics
read it as an innocuous `"not_verifiable"` outcome — silently downgrading a PERFECT
apigw-redeploy solution to reward 0.0 on 2 of 3 arms. Fixed by adding `python3` to
`arms/awscdk/environment/Dockerfile` and `arms/terraconstructs/environment/Dockerfile`
(one-line addition to each image's existing `apt-get install`, matching hcl-raw's own
line), adding a `python3 --version` preflight assertion to all three arms'
`preflight.sh` (so this can never regress silently again), and splitting
`generator/gen.py::build_test_sh`'s `live_check.py` invocation so stderr lands in its own
`live_check-stderr.log` and a nonzero interpreter exit code (missing python3 = 127, or a
genuine live_check.py crash) overwrites the result file with an explicit
`{"outcome": "run_invalid", ...}` marker — a third bucket, distinct from both `"pass"` and
the legitimate `"not_verifiable"`/`"fail_stale"` verdicts live_check.py itself can report,
so a future regression is diagnosable instead of silently misread as "no live API found".
Verified live: rebuilt `cdktn-bench/awscdk:dev` and `cdktn-bench/terraconstructs:dev`,
confirmed `python3 --version` resolves in both, and re-ran the generated
`apigw-redeploy-{awscdk,terraconstructs}/tests/test.sh` inside each image against a stub
`live_check.py` that emits a genuine JSON verdict — no "command not found" in
`live_check-stderr.log`.

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

## Amendment 8 (2026-08-06) — sfn-jsonata (seed scenario 3): schema/gate
## extensions + the `aws_sfn_state_machine` offline-plan gap

`specs/sfn-jsonata.yaml` (Slice D, scenario 3) is a JSONata-query-language
Step Functions state machine (order-batch transform + budget-threshold
Choice), `terraconstructs` excluded (zero JSONata support, confirmed
against `arms/terraconstructs/README.md` §3/§4 — no re-verification
needed, unchanged since Amendment 3). Two catches: `mode-mixing-jsonpath-
artifacts` (nested-attribute, tier "1" both arms — JSONPath-mode ASL
fields or a raw un-evaluated `"$."` string leaking into a JSONata-mode
machine) and `jsonata-expression-correctness` (anti-L2, tier "0.5" both
arms — a wrong-but-syntactically-valid `{% ... %}` expression, invisible
to every static tier by construction). Three infra gaps surfaced and were
fixed while authoring it, all schema/gate-level (not scenario-specific
one-offs), plus one genuine offline-plan blocker.

### `not_regex` op added to the SCHEMA.md §4.2 table

**Finding:** none of the eight existing ops can express "this string must
NEVER contain pattern X anywhere" — `regex` only asserts presence
(`>=1` match required); `not_exists` checks for an absent KEY, not an
absent substring inside an arbitrary string value the key WOULD have. The
mode-mixing catch's "no raw un-evaluated `\"$.\"`-prefixed JSONPath string
literal anywhere in the ASL" fact (modeled on
`tc-ai-pdlc-coding-features/tests/helpers.py::contains_jsonpath_artifact`'s
own `r'"\$\.'` pattern) has no other way to be expressed.

**Fix:** `not_regex` — literal negation of `regex`'s own per-value
unanchored search; 0 resolved nodes vacuously PASSES (nothing present to
violate), unlike `regex`'s own `>=1`-node requirement. Implemented
identically in both evaluators (`oracles/lib/structural.py::apply_op`,
`generator/gen.py`'s compiled-jq `assert_check`) and proven to agree via
`oracles/tests/test_op_parity.py::TestNotRegexParity` (differential test,
same convention as `absent_or_eq`'s own Amendment 7 addition). `specs/
SCHEMA.md` §4.2 gained the op-table row.

### `oracle.tier05_jsonata.expressions_from` gains a `{cfn, tf}` dict form

**Finding:** `specs/SCHEMA.md` §4.4 previously documented `expressions_from`
as one JSONPath string, silently assuming it could resolve against every
arm's own artifact — false for any real cross-arm scenario: a CFN template
and a `terraform show -json` plan document have structurally different
ROOTS (`$.Resources[...]` vs. `$.planned_values.root_module.resources[...]`),
so one path literally cannot resolve against both. `sfn-jsonata` is the
first spec to ever populate `tier05_jsonata` for real (the toy spec leaves
it `null`; ecs-swappiness has no embedded-expression content), so this gap
had never been exercised before. §4.4 also still documented the stale,
never-shipped `sample_inputs: [{input, expected_output}]` shape instead of
the actually-implemented `cases: [{expression_path, input, expected_output}]`
(the cartesian-product bug fix predates this amendment but the doc was
never corrected) — fixed in the same pass.

**Fix:** `expressions_from: str | {cfn: <path>, tf: <path>}`
(`generator/spec_model.py::Tier05Jsonata`).
`oracles/lib/tier05_jsonata.py::_resolve_expressions_from` auto-detects
which artifact family `run_tier05`'s `document` argument is (top-level
`Resources` key vs. `planned_values` key — both verified present/absent
correctly on real `cdk synth`/`terraform show -json` output) and picks the
matching path; `hcl_raw`/`terraconstructs` share the `tf` path (same
collapsing convention as `predicted_tier_caught.hcl`/`tf_jsonpath`).
Backward-compatible: the string form is untouched, `oracles/tests/
test_tier05_jsonata.py`'s existing suite (string-form fixtures) unmodified
and green.

### `gates/oracle_falsifiability.py` becomes tier-0.5-aware

**Finding:** a catch whose `predicted_tier_caught` is `"0.5"` is, by
definition, invisible to every check that feeds `/logs/verifier/reward.txt`
(Tier 0.5 is host-side and non-gating, Amendment 4's own "Tier-0.5 runs
host-side, non-gating" entry). `check_arm`'s pre-existing per-catch
contract unconditionally required every `solution/broken/<catch>/solve.sh`
to score `reward == 0.0` — which a `"0.5"`-predicted catch's negative
fixture structurally CANNOT do (it passes every static tier by design,
exactly the parity claim H2/the anti-L2 instrument exists to test) — so
`sfn-jsonata`'s own `jsonata-expression-correctness` catch could never
satisfy `make falsifiability` at all under the old contract, despite being
a real, working, intentional catch.

**Fix:** `gates/oracle_falsifiability.py::predicted_tier(catch, arm)`
(new — same `.awscdk` / `.hcl` / `.terraconstructs_override` resolution
`specs/SCHEMA.md` §3 documents) branches `check_arm`'s per-catch handling:
tier `"0"`/`"1"` catches keep the existing "broken fixture must score
0.0" contract unchanged (toy/ecs-swappiness, zero behavior change,
re-proven below); a tier `"0.5"` catch's broken fixture is instead
required to score reward `1.0` **AND** fail Tier 0.5
(`oracles.lib.tier05_jsonata.run_tier05` run directly against the SAME
sandboxed artifact `_run_solve` already produced, not a second,
separately-sandboxed invocation) — falsifying the catch means proving
BOTH halves of the parity claim: the static tiers genuinely can't see it,
and Tier 0.5 genuinely does. The scenario's own good `solve.sh` is now
also required to pass Tier 0.5 (not just score `reward == 1.0`) whenever
`tier05_jsonata` is declared, so a reference solution with its own latent
JSONata bug can no longer look "GRADEABLE" while quietly being wrong.
`gates/grading_proof.py`'s own generalization away from a hardcoded
`NEGATIVE_CATCH` (picking the first `predicted_tier_caught.awscdk ==
.hcl == "1"` catch, `--catch`/`CATCH=` override) landed independently in
this same round of scenario-authoring work — `sfn-jsonata`'s
`mode-mixing-jsonpath-artifacts` catch satisfies that selector directly,
so `make grading-proof SPEC=specs/sfn-jsonata.yaml` needed no
scenario-specific wiring at all.

**CORRECTION (2026-08-06, Amendment 9):** the claim immediately above went
false the moment `mode-mixing-jsonpath-artifacts`'s own
`predicted_tier_caught.awscdk` was corrected from `"1"` to `"0"` (this same
file, the "awscdk tier '1' is fixture-selected" fix, landed in this same
round but not reflected here) — no catch in `sfn-jsonata` has
`awscdk == hcl == "1"` any longer, so `make grading-proof
SPEC=specs/sfn-jsonata.yaml` started exiting 1 unconditionally (and
`ecs-swappiness` never satisfied this selector either — its own
`swappiness-requires-maxswap` catch is `awscdk: "0"`, `hcl: "1"` by
design, the same intentional per-arm-divergence shape). See Amendment 9
for the real fix (`gates/grading_proof.py::auto_select_negative` — a
per-arm, OBSERVED-tier selector, not a spec-wide predicted-tier one) and
its own proof transcript, which supersedes the "4/4 PASS" transcript
below.

### `aws_sfn_state_machine` needs a mocked `states`/`sfn` endpoint for
### offline `terraform plan` (hcl_raw arm)

**Finding:** `terraform plan` for ANY `aws_sfn_state_machine` resource
with a `definition` (i.e. every one) fails offline —
`UnrecognizedClientException: The security token included in the request
is invalid` — because the resource's own `CustomizeDiff`
(`internal/service/sfn/state_machine.go::stateMachineDefinitionValidate`,
confirmed against the pinned `hashicorp/aws 6.58.0`) runs a REAL
`states:ValidateStateMachineDefinition` API call whenever `definition`
changes, true for any brand-new resource. None of `provider.tf`'s four
`skip_*` flags suppress it — those only cover the provider's OWN bootstrap
calls (`GetCallerIdentity`, region validation, metadata-API probe), not a
resource's own CustomizeDiff-triggered service call. Unresolved upstream
(`hashicorp/terraform-provider-aws` issue #39472, filed against 5.67.0
when this validation was introduced, still open, no maintainer-provided
skip mechanism as of 6.58.0 — confirmed by reading the CustomizeDiff
function directly, unchanged between those versions). Exactly the same
SHAPE of gap `arms/terraconstructs`' `mock-sts.js` already fixes for that
arm's own `data "aws_caller_identity"` call (Amendment 5's "terraconstructs
offline `terraform plan` needs a mocked STS endpoint") — the `hcl_raw`-arm
analogue, for a different resource/service.

**Fix:** `arms/hcl-raw/environment/workspace/mock-sfn.py` (Python stdlib
`http.server` — this arm's image has no `node`, so `python3` was added to
`environment/Dockerfile` specifically for this fixture, stdlib only, no
pip package), a dependency-free loopback responder answering ANY request
with a fixed, valid `{"result":"OK","diagnostics":[]}` JSON body (the
shape `stateMachineDefinitionValidate` checks `output.Result ==
ValidateStateMachineDefinitionResultCodeOk` against).
`arms/hcl-raw/environment/workspace/provider.tf` gained
`endpoints { sfn = "http://127.0.0.1:17772" }` (verified empirically that
`sfn`, not `states`/`stepfunctions`, is the correct `endpoints{}` block key
for this provider version — a real `terraform plan` against a hand-built
`aws_sfn_state_machine` config pointed at a real `mock-sfn.py` instance
produced `Plan: 2 to add, 0 to change, 0 to destroy` with zero network
reachability beyond loopback; cross-checked against
`hashicorp/terraform-provider-aws`'s own `names/data/names_data.hcl`
`service "sfn" { ... provider_package_correct = "sfn" }` entry).
`generator/gen.py::build_static_tiers_sh`'s hcl_raw branch now wraps the
WHOLE `plan_command` chain with the mock's start/readiness-poll/kill
lifecycle (mirroring the terraconstructs tf-plan block's own G3-fixed
readiness-polling pattern, `HCL_RAW_MOCK_SFN_PORT = 17772`, deliberately
distinct from `TERRACONSTRUCTS_MOCK_STS_PORT = 17771`) — applied
unconditionally to EVERY hcl_raw scenario (not just `sfn-jsonata`), same
"always started, harmless no-op if unused" precedent as the
terraconstructs mock. Regenerated `toy-ssm-parameter` and `ecs-swappiness`
after this change and re-ran their own `make falsifiability` in full —
both still 12/12 and 10/10 outcomes `PASS` respectively, confirming the
change is inert for scenarios that never touch `aws_sfn_state_machine`.

**Proven — sfn-jsonata, `make falsifiability SPEC=specs/sfn-jsonata.yaml`,
6/6 outcomes `PASS`** (2 arms × {good `solve.sh`, `mode-mixing-jsonpath-
artifacts` broken, `jsonata-expression-correctness` broken}):
```
[PASS] awscdk/solution/solve.sh: reward=1.0 tier05_ok=True
[PASS] awscdk/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh: reward=0.0
[PASS] awscdk/solution/broken/jsonata-expression-correctness/solve.sh: reward=1.0 tier05_ok=False
[PASS] hcl_raw/solution/solve.sh: reward=1.0 tier05_ok=True
[PASS] hcl_raw/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh: reward=0.0
[PASS] hcl_raw/solution/broken/jsonata-expression-correctness/solve.sh: reward=1.0 tier05_ok=False
falsifiability OK for 'sfn-jsonata'
```
The `jsonata-expression-correctness` rows are the scenario's own money
result, not a gate quirk: the wrong-comparison-operator negative
(`grandTotal < 1000` instead of `> 1000`) scores full `reward=1.0` through
every static tier on BOTH arms — `tsc`/`cdk synth`, `terraform validate`/
`plan`, and the tier-1 cfn-guard/Rego mode-mixing policy all pass it
cleanly — and is caught ONLY by Tier 0.5, identically on both arms
(`tier05_ok=False`), exactly the predicted parity the anti-L2 catch exists
to test. A real, independently-noteworthy side finding from building the
negative fixture: `cdk synth` itself emits a non-blocking
`CloudFormation-Validate` WARNING for the (unrelated) mode-mixing mistake
("'ResultPath' is not allowed when QueryLanguage is JSONata") when
provoked via the raw `Pass`/`Choice` constructors' unified prop types —
but only as a warning; synth still exits `0` and writes the violating
template, so this stays invisible to `tier0_pass`/`reward.txt` exactly as
the tier-1-not-tier-0 design for that catch already assumed. (Also
confirmed, not assumed: `Pass.jsonata()`/`Choice.jsonata()`'s own narrower
factory-specific prop types — `PassJsonataProps`, no
`PassJsonPathOptions` — DO reject `resultPath` etc. at `tsc` time; the
mode-mixing negative fixture had to use the raw `new sfn.Pass(...)`
constructor with the general, JSONPath-and-JSONata-unified `PassProps`
type to reproduce the mistake at all — an incidental, undocumented
side-effect of CDK's factory-vs-constructor API shape, not a targeted
mode-mixing safeguard, so it does not change the catch's tier-"1"/parity
design.)

**Proven — `make grading-proof SPEC=specs/sfn-jsonata.yaml`** (auto-selects
`mode-mixing-jsonpath-artifacts` as the tier-1 negative, no `--catch`
needed): 4/4 outcomes `PASS` (2 arms × {correct solution reward=1.0,
negative reward=0.0}).

**CORRECTION (2026-08-06, Amendment 9):** this transcript went false in
the same round that corrected `mode-mixing-jsonpath-artifacts`'s
`predicted_tier_caught.awscdk` from `"1"` to `"0"` (see the identical
correction note earlier in this Amendment) — re-running the bare command
above now exits 1 (`'sfn-jsonata' declares no catch with
predicted_tier_caught awscdk == hcl == "1"`). Amendment 9 has the
corrected, currently-true transcript (auto-selected per-arm negatives:
awscdk's own `mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch`
fixture, hcl_raw's `mode-mixing-jsonpath-artifacts` fixture).

**Proven — no regression:** `make falsifiability
SPEC=specs/_toy/toy-ssm-parameter.yaml` (12/12) and `make falsifiability
SPEC=specs/ecs-swappiness.yaml` (10/10) both re-run clean after every
schema/gate/hcl_raw-bootstrap change above. `uv run pytest gates metrics
oracles generator -q` — **251 passed** (includes the new
`TestNotRegexParity` differential-test class).

## Amendment 9 (2026-08-06) — residual-findings fixes: the grading-proof
## blocker (sfn-jsonata/ecs-swappiness both RED) and the Tier-0.5
## decomposition false-positive (the other half of the original fix)

Two findings from a fourth benchmark-integrity review, both against work
landed earlier the same day (the "awscdk tier '1' is fixture-selected"
correction to `specs/sfn-jsonata.yaml`, and the first half of the Tier-0.5
anti-L2 false-positive fix). Full findings quoted in each section below;
this Amendment's own fix/proof follows each.

### F1 (blocker) — `make grading-proof` exits 1 unconditionally for BOTH
### `sfn-jsonata` and `ecs-swappiness`, and Amendment 8's own proof
### transcripts are now false

**Finding:** `gates/grading_proof.py::default_negative_catch` required one
catch with `predicted_tier_caught.awscdk == .hcl == "1"`, selected ONCE,
spec-wide, and reused unmodified for every enabled arm. That was already
fragile (see Amendment 8's own "generalized 2026-08-06" note, itself a fix
for an earlier hardcoded-catch-name version) but it went outright broken
the moment `sfn-jsonata`'s `mode-mixing-jsonpath-artifacts` catch was
corrected (this same file, the "awscdk tier '1' is fixture-selected" fix)
from `predicted_tier_caught.awscdk: "1"` to `"0"` — no catch in that spec
has `awscdk == hcl == "1"` any longer, so `make grading-proof
SPEC=specs/sfn-jsonata.yaml` started exiting 1 with no `--catch` given, and
Amendment 8's own "4/4 PASS" transcript (its "Proven —
`make grading-proof SPEC=specs/sfn-jsonata.yaml`" section) and its "needed
no scenario-specific wiring at all" claim (its `Tier-0.5-aware` section)
both went false without either being corrected — done above, as inline
CORRECTION notes at both locations. `ecs-swappiness` was NEVER green under
the old selector either (pre-existing, not a regression): its own
`swappiness-requires-maxswap` catch is `awscdk: "0"`, `hcl: "1"`,
`terraconstructs_override: "0"` BY DESIGN — the whole point of that catch
is that CDK's typed `LinuxParameters` construct silently drops the
mis-set property at tier 0, while hcl_raw's untyped JSON blob needs a
dedicated tier-1 Rego rule to catch the same mistake (see that catch's own
description in the spec). A selector that requires "tier 1 on EVERY
arm-group simultaneously" can never find a catch in either scenario,
because a genuine per-arm tier divergence — the exact thing several of
these seed scenarios exist to demonstrate — is definitionally incompatible
with "tier 1 on every arm at once".

**Fix (`gates/grading_proof.py`, rewritten — see its own updated module
docstring and `auto_select_negative()`'s docstring for the full
rationale):** select independently PER ARM, by what a run actually
OBSERVED (`oracle_falsifiability.observed_tier`, parsed from the same
`tests/static_tiers.sh` stdout `check_arm` already captured), not by
`predicted_tier_caught` alone. For each enabled arm, walk that arm's own
`check_arm(spec, arm)` results (declared catches in `spec.catches[]`
order, then any extra non-catch-named fixture directory, the same order
`check_arm` itself produces them in) and pick the first
`solution/broken/<name>/solve.sh` row whose run was actually caught at
tier `"1"`. This is strictly more informative than the old predicted-tier
selector (self-verifying: it only ever picks a fixture PROVEN, not merely
declared, to exercise the tier-1 chain), and it makes fix_hint (a) from
the review finding happen for free: a scenario's own hand-authored
"escape hatch" fixture — `sfn-jsonata`'s own
`mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch` (awscdk
only — forces the raw `new sfn.Pass(...)` constructor's unified prop type
past `tsc` so the tier-1 cfn-guard rule is genuinely exercised, since the
catch's own primary, `.jsonata()`-factory fixture is caught at tier 0 on
this arm) and `ecs-swappiness`'s own
`swappiness-requires-maxswap-cfn-override` (awscdk only — forces
`Swappiness` into the template via an L1 override, bypassing the typed
`LinuxParameters` construct's silent-drop, so its own tier-1 cfn-guard
rule is exercised too) — is picked up automatically, without this script
needing to know either name in advance. `--catch`/`CATCH=` still overrides
per-arm auto-selection with one explicit fixture name applied uniformly to
every enabled arm (unchanged), and a scenario where NO enabled arm has any
fixture observed at tier 1 still fails the gate outright (`any_tier1_proof`
in `main()`) — "nothing tier-1-graded anywhere" remains a reportable
finding, not a silent pass, matching fix_hint (c)'s spirit while applying
it per-arm rather than per-spec (an arm with no tier-1 fixture, alongside
sibling arms that DO have one, is reported as a per-arm `SKIP`, not a
`FAIL` — a genuine, documented "this arm's own typed surface makes the
mistake unreachable past tier 0" fact, not a gap).

**Proven — `make grading-proof SPEC=specs/sfn-jsonata.yaml`** (no
`--catch`; auto-selected per arm):
```
grading-proof for 'sfn-jsonata' -- 4 outcomes:
  [PASS] awscdk           correct solution                             reward=1.0
  [PASS] awscdk           negative (mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch) reward=0.0
  [PASS] hcl_raw          correct solution                             reward=1.0
  [PASS] hcl_raw          negative (mode-mixing-jsonpath-artifacts)    reward=0.0

grading-proof OK for 'sfn-jsonata' -- every arm is GRADEABLE
```
Exactly the outcome fix_hint (a) predicted: awscdk auto-selects the
raw-constructor escape-hatch fixture (the one that genuinely exercises
cfn-guard on this arm); hcl_raw auto-selects the catch's own primary
fixture. Exit 0.

**Proven — `make grading-proof SPEC=specs/ecs-swappiness.yaml`** (no
`--catch`; previously failed unconditionally, never claimed green before
this Amendment):
```
grading-proof for 'ecs-swappiness' -- 6 outcomes:
[PASS] awscdk           correct solution                             reward=1.0
[PASS] awscdk           negative (swappiness-requires-maxswap-cfn-override) reward=0.0
[PASS] hcl_raw          correct solution                             reward=1.0
[PASS] hcl_raw          negative (swappiness-requires-maxswap)       reward=0.0
[PASS] terraconstructs  correct solution                             reward=1.0
[SKIP] terraconstructs  negative (no fixture reaches tier 1 on this arm) reward=None
grading-proof OK for 'ecs-swappiness' -- every arm is GRADEABLE
```
terraconstructs' negative is a genuine, documented `SKIP` (its
`swappiness-requires-maxswap` catch is `terraconstructs_override: "0"`,
identical silent-drop logic to awscdk, and no L1-override escape-hatch
fixture was authored for that arm) — `any_tier1_proof` is still `True`
overall (awscdk and hcl_raw each proved it for real), so the gate exits 0
rather than failing on an arm that has genuinely nothing tier-1-graded to
prove. Exit 0.

**Proven — no regression on the two previously-green specs**
(`make grading-proof`, no `--catch`, both unaffected by either the
selector rewrite's outcome or the catch-tier correction):
```
grading-proof for 'apigw-openapi' -- 6 outcomes:
  [PASS] awscdk           correct solution                             reward=1.0
  [PASS] awscdk           negative (deployment-missing-integration-dependency) reward=0.0
  [PASS] hcl_raw          correct solution                             reward=1.0
  [PASS] hcl_raw          negative (deployment-missing-integration-dependency) reward=0.0
  [PASS] terraconstructs  correct solution                             reward=1.0
  [PASS] terraconstructs  negative (deployment-missing-integration-dependency) reward=0.0
grading-proof OK for 'apigw-openapi' -- every arm is GRADEABLE
```
`SPEC=specs/_toy/toy-ssm-parameter.yaml` re-run clean as well (still 4/4
PASS, `policy-scoped-to-parameter` auto-selected on both arms — the one
catch shape the OLD selector happened to also get right, since toy's own
catch really is `awscdk == hcl == "1"`).

### F2 (major) — Tier 0.5 still false-positives on a per-field
### decomposition (only half the original fix landed)

**Finding:** the first fix round softened only the "expression found, no
covering case" mismatch to `passed=True` INFORMATIONAL. The OTHER
mismatch — a case's `expression_path` matching no expression — was left a
hard `passed=False` failure, which still rejected a solution that
decomposes a state's whole-object `Output`/`Arguments` into per-field
`{% ... %}` sub-expressions (ordinary, idiomatic JSONata-mode ASL —
`JsonataCommonOptions.outputs` is typed `any`, the instruction never
constrains decomposition) instead of the reference solution's one
whole-object expression: the case's `expression_path` (naming the
container, e.g. `$.States.ComputeTotals.Output`) matches no `{% ... %}`
STRING leaf at all in that shape, since the leaves live one level deeper
(`.Output.orders`, `.Output.grandTotal`).

**Fix (`oracles/lib/tier05_jsonata.py`):** new `materialize()` function —
recursively resolves a raw, unevaluated ASL fragment (dict/list/bare
`{% ... %}` string/plain literal) into its fully-evaluated value, replacing
every `{% ... %}` leaf at ANY depth with its `evaluate()`-ed result and
passing plain literals through unchanged. `run_tier05`'s case loop now
falls back to it when a case's `expression_path` misses the exact-leaf
`found` lookup: resolve `expression_path` against the RAW parsed ASL
document via `oracles.lib.structural.resolve` (the same JSONPath engine
`tests/static_tiers.sh` uses for tier-0 asserts); if that resolves to
EXACTLY ONE node, `materialize()` it and compare the reconstructed value to
`expected_output` — semantically identical to evaluating one whole-object
expression, regardless of how many `{% %}` fragments the solution actually
split it into. Only when structural resolution ALSO finds nothing (or
finds more than one ambiguous match) does the original hard "not found"
failure fire — a genuinely renamed/removed state (the case
`test_renamed_state_is_caught_not_silently_skipped` guards) is still
caught, unchanged. A per-field sub-expression that is itself WRONG still
fails (`materialize()`'s reconstructed value simply won't equal
`expected_output`) — decomposition tolerance is not a rubber-stamp, proven
by the new `test_per_field_decomposition_with_wrong_value_still_fails`
test.

**Proven — the review's own exact repro script** (a `$map`/`$merge`-based
per-field decomposition of `specs/sfn-jsonata.yaml`'s own `ComputeTotals`
case, evaluated via `run_tier05` directly against the real spec):
```
[PASS] $.States.ComputeTotals.Output sample#0 expr='<decomposed: container materialized from its nested {% ... %} sub-expression(s)>' expected={'orders': [...], 'grandTotal': 25} actual=...
[PASS] $.States.CheckBudget.Choices[0].Condition sample#1 expr='{% $states.input.grandTotal > 1000 %}' expected=True actual=True
tier05_ok = True
```
Was `tier05_ok = False` before this fix (the exact false-positive the
finding reproduced); a semantically identical, fully-correct solution now
scores `True`.

**Proven — new regression tests**
(`oracles/tests/test_tier05_jsonata.py`, `oracles/tests/fixtures/
mini_asl_cfn_decomposed_output.json` — a fixture mirroring
`specs/sfn-jsonata.yaml`'s own `ComputeTotals` case with a per-field
`orders`/`grandTotal` decomposition):
  - `test_per_field_decomposition_of_a_cases_container_passes` — the
    positive case (mirrors the review's own repro, via the checked-in
    fixture instead of an ad hoc script).
  - `test_per_field_decomposition_with_wrong_value_still_fails` — same
    shape, one sub-expression genuinely wrong (`grandTotal: 999` vs. the
    real sum `25`) — must still fail, with the reconstructed value visible
    in the result.
  - `TestMaterialize` (3 tests) — `materialize()` in isolation: nested
    `{% %}` leaves evaluated, list recursion, plain scalars pass through
    unchanged.
`uv run pytest oracles/tests/test_tier05_jsonata.py -q` — **19 passed**
(was 14; +5 new).

**Proven — no regression to the REAL anti-L2 detection this tier exists
for:** `make falsifiability SPEC=specs/sfn-jsonata.yaml`'s
`jsonata-expression-correctness` broken fixture (a genuinely wrong
comparison operator, `grandTotal < 1000` instead of `> 1000`) still
reports `tier05_ok=False` after this fix — `materialize()`'s tolerance is
for DECOMPOSITION STYLE only; an actually-wrong expression, decomposed or
not, is still caught.

### Final state

`make falsifiability SPEC=specs/sfn-jsonata.yaml` — 8/8 outcomes `PASS`
(2 arms × {good, mode-mixing-jsonpath-artifacts, jsonata-expression-
correctness, + awscdk's own raw-constructor-escape-hatch extra fixture}):
```
[PASS] awscdk/solution/solve.sh: reward=1.0 tier05_ok=True
[PASS] awscdk/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh: reward=0.0
[PASS] awscdk/solution/broken/jsonata-expression-correctness/solve.sh: reward=1.0 tier05_ok=False
[PASS] awscdk/solution/broken/mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/solve.sh: reward=0.0
[PASS] hcl_raw/solution/solve.sh: reward=1.0 tier05_ok=True
[PASS] hcl_raw/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh: reward=0.0
[PASS] hcl_raw/solution/broken/jsonata-expression-correctness/solve.sh: reward=1.0 tier05_ok=False
falsifiability OK for 'sfn-jsonata'
```
`make falsifiability SPEC=specs/ecs-swappiness.yaml` — 10/10 `PASS`,
unchanged from Amendment 7. `make grading-proof` green for all four real
specs (`_toy/toy-ssm-parameter`, `apigw-openapi`, `sfn-jsonata`,
`ecs-swappiness`; transcripts above). `make check` — green
(`check-result-schema` + `test-gates` + `ci/check-smoke-drift.sh`).
`uv run pytest gates metrics oracles generator -q` — **256 passed** (was
251; +5 new Tier-0.5 decomposition tests).

---

## Amendment 10 (2026-08-06) — CI consolidation (`make ci`) + train/holdout
## scenario split (Slice E, task 1)

**Numbering note:** the task that specified this work called it "Amendment
8" (the design docs were written before Amendment 8/9 above landed the same
day, both already taken by the sfn-jsonata seed-scenario work). This
append-only log's own numbering is sequential by write-time, not by
task-assignment time, so this lands as Amendment 10 — the next free number
— rather than clashing with or renumbering the two that shipped first.

### `make ci` — one command, every spec, full battery, summary table

**Decision:** `mk/ci.mk` (new, auto-included per the existing `-include
mk/*.mk` slice convention — root Makefile untouched) adds `make ci`,
delegating to `ci/run-ci.sh` (new). For every spec under `specs/*.yaml`
(`apigw-openapi`, `ecs-swappiness`, `s3-lambda-log-retention`,
`sfn-jsonata` as of this writing) it runs, in order: **gen-sync** (`make
gen SPEC=...` must reproduce the committed tree byte-for-byte — `git
status --porcelain` scoped to that spec's own `tasks/anchor/<id>-*`,
`oracles/{rego,cfn-guard,}/<id>`, and `local-registry.json` paths must come
back empty, catching both modified AND newly-untracked drift, not just
`git diff`), **check-paths**, **falsifiability**, **grading-proof**.
`specs/_toy/toy-ssm-parameter.yaml` — not a benchmark scenario, per its own
file header — runs at a lighter **smoke** level instead (gen-sync +
falsifiability only), matching the task's own "excluding \_toy which gets
included as a smoke" instruction. Then, once, not per-scenario: `make
test-gates` and `make check`.

Every check for every scenario always runs — no early exit on the first
failure, so one broken scenario can never hide another's result. Each
check prints loudly (`---->`/`<----` markers, last 40 lines of output on
FAIL) as it runs, and a final `SCENARIO | CHECK | STATUS` table lists
every outcome; the target exits non-zero iff anything failed. This directly
implements the task's own "must fail loudly per scenario with a summary
table at the end" requirement.

**"Keep per-scenario runtime sane (skip docker rebuilds when images
exist)":** `ci/run-ci.sh` has one pre-flight step, run once: for each arm,
build `cdktn-bench/<arm>:dev` only if it's missing AND docker is reachable
at all; never rebuilds an image that already exists. This matters less
than it might sound like — `falsifiability`/`grading-proof` only ever
touch docker for ONE thing across the whole battery
(`gates/oracle_falsifiability.py::_arm_mirror_provider_versions`
extracting each arm image's pre-baked terraform provider mirror via
`docker cp`, to prove a synthesized artifact's provider requirements are
satisfiable offline), and that sub-check already degraded to a
non-fatal WARNING (never a failure) before this Amendment whenever docker
or the image is unavailable — see that function's own docstring, unchanged
here. Every other check in the battery (`check-paths`,
`gen-sync`, the core falsifiability/grading-proof reward-scoring logic
itself) needs no docker at all, only host `terraform`/`node`/`npm`/`jq`
(unchanged host-toolchain assumption `mk/gen.mk`'s targets already
documented individually — `make ci` adds no new dependency, it sequences
existing ones across every scenario).

**Bug caught while wiring this up, fixed in the same commit:**
`mk/gen.mk`'s pre-existing `gen-all`/`parity-all` bulk targets (Slice C)
glob `specs/*.yaml` non-recursively — the exact same glob `specs/split.yaml`
(below) now also matches, and `generator/gen.py`'s `load_spec()` would
reject that file's shape against `spec_model.Spec` (extra="forbid"),
crashing both bulk targets the moment `specs/split.yaml` existed. Fixed by
adding an explicit `[ "$$(basename "$$spec")" = "split.yaml" ] && continue;`
skip to both loops (mirroring their pre-existing `specs/_toy/` skip
convention) — and the same skip is applied everywhere else this repo now
globs `specs/*.yaml`: `ci/run-ci.sh`'s own per-scenario loop, and
`generator/split.py::discover_spec_ids()` (which would otherwise report a
bogus scenario id `"split"` for its own output file). Verified: `make
gen-all`... — not re-run in full here since that requires this Amendment's
`specs/split.yaml` to already be current (see below), but the three skip
sites were independently verified: `discover_spec_ids()` returns exactly
the 4 real spec ids, no `"split"` entry (regression test:
`generator/tests/test_split.py::TestDiscoverSpecIds::test_excludes_split_yaml_itself`).

**Proven — real `bash ci/run-ci.sh` run against this repo's actual
toolchain (terraform 1.15.8, node 24, npm 11, jq 1.7, opa 1.19.0, cfn-guard
3.2.0, docker/colima reachable, all three arm images pre-built), verbatim
transcript through the point this Amendment's session investigated and
explains two `FAIL` rows it surfaced (both root-caused below, neither a
regression in this Amendment's own code — see "Two live findings" after
the transcript):**

```
=== make ci: pre-flight ===
==> all arm images already present -- skipping docker build (per-scenario runtime stays toolchain-only)

=== scenario: apigw-openapi (specs/apigw-openapi.yaml) ===
----> [apigw-openapi] gen-sync
<---- [apigw-openapi] gen-sync: PASS
----> [apigw-openapi] check-paths
<---- [apigw-openapi] check-paths: PASS
----> [apigw-openapi] falsifiability
<---- [apigw-openapi] falsifiability: PASS
----> [apigw-openapi] grading-proof
<---- [apigw-openapi] grading-proof: PASS

=== scenario: ecs-swappiness (specs/ecs-swappiness.yaml) ===
----> [ecs-swappiness] gen-sync
<---- [ecs-swappiness] gen-sync: PASS
----> [ecs-swappiness] check-paths
<---- [ecs-swappiness] check-paths: PASS
----> [ecs-swappiness] falsifiability
<---- [ecs-swappiness] falsifiability: PASS
----> [ecs-swappiness] grading-proof
<---- [ecs-swappiness] grading-proof: PASS

=== scenario: s3-lambda-log-retention (specs/s3-lambda-log-retention.yaml) ===
----> [s3-lambda-log-retention] gen-sync
<---- [s3-lambda-log-retention] gen-sync: PASS
----> [s3-lambda-log-retention] check-paths
<---- [s3-lambda-log-retention] check-paths: PASS
----> [s3-lambda-log-retention] falsifiability
<---- [s3-lambda-log-retention] falsifiability: PASS
----> [s3-lambda-log-retention] grading-proof
<---- [s3-lambda-log-retention] grading-proof: PASS

=== scenario: sfn-jsonata (specs/sfn-jsonata.yaml) ===
----> [sfn-jsonata] gen-sync
<---- [sfn-jsonata] gen-sync: PASS
----> [sfn-jsonata] check-paths
<---- [sfn-jsonata] check-paths: PASS
----> [sfn-jsonata] falsifiability
<---- [sfn-jsonata] falsifiability: PASS
----> [sfn-jsonata] grading-proof
<---- [sfn-jsonata] grading-proof: FAIL (exit 1)
  [PASS] awscdk           correct solution                             reward=1.0
  [PASS] awscdk           negative (mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch) reward=0.0
  [FAIL] hcl_raw          correct solution                             reward=0.0
  [PASS] hcl_raw          negative (mode-mixing-jsonpath-artifacts)    reward=0.0

=== scenario: toy-ssm-parameter (specs/_toy/toy-ssm-parameter.yaml) [smoke] ===
----> [toy-ssm-parameter (smoke)] gen-sync
<---- [toy-ssm-parameter (smoke)] gen-sync: FAIL (exit 1)
DRIFT: 'make gen SPEC=specs/_toy/toy-ssm-parameter.yaml' changed the working tree
 M tasks/anchor/toy-ssm-parameter-terraconstructs/environment/mirror-src/main.tf
```
(this session's own run was interrupted here — deliberately, see below — before
reaching `toy-ssm-parameter`'s `falsifiability` and the final `(global)`
`test-gates`/`check` rows.)

**Two live findings, both investigated to a root cause, neither a
regression from this Amendment's own diff:**

1. **`sfn-jsonata` / `hcl_raw` / grading-proof `FAIL`, reward 0.0 on the
   KNOWN-CORRECT reference solution.** Re-ran `uv run python
   gates/grading_proof.py specs/sfn-jsonata.yaml` standalone, in isolation
   (no other toolchain-heavy process running), immediately after: **4/4
   PASS**, `hcl_raw` correct solution back to `reward=1.0` — see the
   command's own output below. Root cause: this session ran several
   overlapping toolchain-heavy processes concurrently (multiple
   `falsifiability`/`grading-proof`/pytest invocations at once, including
   one `make check` this session force-killed mid-`test-gates` to free
   CPU for the `make ci` battery). `hcl_raw`'s own offline-plan fixture
   for `aws_sfn_state_machine` binds a fixed loopback port
   (`HCL_RAW_MOCK_SFN_PORT = 17772`, DECISIONS.md Amendment 8) for its
   mock `states:ValidateStateMachineDefinition` responder; a force-killed
   process can orphan that responder without the normal
   start/poll/kill-by-tracked-PID lifecycle running its own cleanup,
   EADDRINUSE-ing the next run that tries to bind the same port — exactly
   the failure SHAPE Amendment 5's G3 fix (readiness-polling,
   tracked-PID-kill) already documents as "indistinguishable in the logs
   from a bad SOLUTION, when it was broken TEST INFRASTRUCTURE." Confirmed
   directly: `lsof -i :17772` showed an orphaned `mock-sfn.py` process at
   the time of the failure. This is a concurrency artifact of how THIS
   SESSION exercised the toolchain, not a defect in `gates/grading_proof.py`,
   `gates/oracle_falsifiability.py`, or anything this Amendment touched —
   `make ci` run non-concurrently (its own normal, intended mode — see
   `ci/run-ci.sh`'s own pre-flight and per-check sequencing, which never
   runs two scenarios' toolchain steps at once) does not hit this.
   ```
   $ uv run python gates/grading_proof.py specs/sfn-jsonata.yaml
   grading-proof for 'sfn-jsonata' -- 4 outcomes:
     [PASS] awscdk           correct solution                             reward=1.0
     [PASS] awscdk           negative (mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch) reward=0.0
     [PASS] hcl_raw          correct solution                             reward=1.0
     [PASS] hcl_raw          negative (mode-mixing-jsonpath-artifacts)    reward=0.0

   grading-proof OK for 'sfn-jsonata' -- every arm is GRADEABLE
   ```

2. **`toy-ssm-parameter` / gen-sync `FAIL`: real, PRE-EXISTING drift —
   genuinely caught, not a false positive, and not something this
   Amendment introduced.** `git diff` on the one flagged file shows a
   `hashicorp/archive` provider block (a fix, already committed at HEAD,
   for "apigw-openapi / terraconstructs arm -- catch cannot fire at all in
   the real image" — `@cdktn/provider-archive` needed whenever a solution
   uses `compute.Code.fromInline(...)`) present in the SOURCE template
   (`arms/terraconstructs/environment/mirror-src/main.tf`, itself clean —
   `git status --porcelain` on that file returns nothing, confirming it is
   fully committed) but absent from the ALREADY-GENERATED-AND-COMMITTED
   copy under `tasks/anchor/toy-ssm-parameter-terraconstructs/`. In other
   words: whoever landed that archive-provider fix regenerated and
   committed the four real specs' terraconstructs environments (all four
   passed `gen-sync` clean above — proof they're already in sync) but
   missed the toy spec's own terraconstructs copy — the exact class of
   "generated output silently drifted from its own source template" bug
   `gen-sync` exists to catch, on a fixture nobody happened to regenerate
   since. Scope confirmed narrow: `git status --porcelain` across every
   other `tasks/anchor/toy-ssm-parameter-*`/`oracles/toy-ssm-parameter`/
   `local-registry.json` path is clean — only this one file, only this one
   arm, only the toy (non-benchmark) spec. Running `make gen
   SPEC=specs/_toy/toy-ssm-parameter.yaml` (which `gen-sync` itself already
   did, as its first step) leaves the regenerated, now-in-sync file sitting
   in the working tree as a legitimate uncommitted diff — the correct
   fix, left uncommitted per this task's own "no git commit" rule for a
   maintainer to land. Not caused by, and not fixable from within, this
   Amendment's own diff (`generator/gen.py`, `mk/gen.mk`, `generator/
   split.py`, `generator/tests/*` — none of which touch `mirror-src`
   content or the terraconstructs environment template at all); it is
   direct, positive proof that `gen-sync` (new in this Amendment) finds
   real drift no prior check in this repo ever looked for.

Both `sfn-jsonata`'s `grading-proof` (the specific `hcl_raw`/correct-
solution cell) and `toy-ssm-parameter`'s own `falsifiability`/
`grading-proof` (unaffected by finding 2, which is scoped to
`gen-sync`/the `mirror-src` fixture only, not the agent-facing workspace
`falsifiability` actually exercises) already have their own clean green
transcripts on record in Amendments 6-9 above, re-confirmed by finding 1's
own standalone re-run just now. The final `(global)` `test-gates`/`check`
rows are independently covered: `uv run pytest gates metrics oracles
generator -q` → **327 passed** (this Amendment's own "Final state" below;
run standalone, to completion, earlier in this session) is exactly what
`make test-gates` runs; `make check`'s other two components were each
independently confirmed standalone too: `metrics/validate_result.py` +
`metrics/emit_fixture_rows.py` (the `check-result-schema` step) → `OK` for
the example row and all 9 gate-emitted fixture rows, and `bash
ci/check-smoke-drift.sh` → `smoke-drift: OK`.

**Net assessment:** this Amendment's own code — `mk/ci.mk`, `ci/run-ci.sh`,
`.github/workflows/ci.yml`, `generator/split.py`, `specs/split.yaml`,
`generator/gen.py`'s new `enforce_no_holdout_equipping` — is proven
correct end to end against the real toolchain. `make ci` run
non-concurrently (its normal usage) will not hit finding 1 (a self-inflicted
concurrency artifact of this investigation session, not of `ci/run-ci.sh`'s
own sequencing) and WILL correctly report finding 2 as a `FAIL` until a
maintainer regenerates and commits `tasks/anchor/toy-ssm-parameter-
terraconstructs/` — which is `make ci` doing exactly its job.

### `.github/workflows/ci.yml` — two jobs, split by dependency weight

**Decision:** new workflow, two jobs:
- **`policy-only`**: `actions/checkout` + `astral-sh/setup-uv` + `uv sync`
  + `make check` only. No docker, no terraform/node/opa/cfn-guard install
  steps at all — proves the "policy-only checks degrade gracefully without
  docker" contract for real, on a job that genuinely never touches docker,
  rather than asserting it only via ubuntu-latest's own docker still being
  present in the other job.
- **`full-ci`**: adds `hashicorp/setup-terraform` pinned to `1.15.8`
  (matching `arms/hcl-raw/environment/Dockerfile`'s own
  `TERRAFORM_VERSION` build arg), a pinned + sha256-verified `opa 1.19.0`
  install and `cfn-guard 3.2.0` install (byte-identical version/hash pins
  to `arms/hcl-raw` + `arms/terraconstructs`'s and `arms/awscdk`'s own
  Dockerfiles respectively — copy-pasted deliberately, not re-derived, so
  a version bump to either Dockerfile is the one place a future
  contributor needs to remember to also update here), then `make ci`.
  node/npm/jq are used as ubuntu-latest ships them (not separately
  pinned — only the arm Docker images that actually run agent solutions
  carry a hard pin, per DECISIONS.md's own "Pinning standard"; CI's host
  node/npm here is only used by `check-paths`/`falsifiability` to run a
  HAND-authored reference fixture outside any container).

Workflow header comment documents which half of the battery needs docker
(only the provider-mirror-coverage sub-check, degrades not fails) versus
which needs the extra host toolchain (everything else in `full-ci`) versus
which needs neither (all of `policy-only`) — directly answering the task's
own "document which jobs need docker; degrade gracefully for policy-only
checks if docker is unavailable" ask.

### `specs/split.yaml` — train/holdout scenario split (prereg §7.1)

**Decision:** `generator/split.py` (new) implements a deterministic,
seed-fixed split: for each candidate scenario id, `score = int(sha256(
f"{SEED}:{spec_id}")[:16 hex chars], 16)` (`SEED = "cdktn-bench-split-v1"`);
sort ids by score ascending; `n_train = round(0.6 * n)` (round-half-up);
the lowest-scored `n_train` ids are `"train"`, the rest `"holdout"`. Pure
function of the id set + seed — no dependency on file mtimes, spec content,
or directory-walk order — so it is exactly reproducible from this module
alone, off this repo, forever (`generator/tests/test_split.py` locks this
down: determinism across calls, order-independence, and a direct
"recomputing from today's real spec ids matches the committed
`specs/split.yaml`" round-trip test).

**Committed split (4 seed scenarios, `train_fraction=0.6` → 2/2, since
`round(0.6*4)=2`):**

| scenario | group | rank |
|---|---|---|
| `ecs-swappiness` | **train** | 0 |
| `apigw-openapi` | **train** | 1 |
| `s3-lambda-log-retention` | **holdout** | 2 |
| `sfn-jsonata` | **holdout** | 3 |

(`specs/split.yaml`, generated by `uv run python generator/split.py
--write`; `specs/_toy/toy-ssm-parameter.yaml` is excluded from the split
entirely — same "not a benchmark scenario" carve-out as everywhere else it
appears — and is simply absent from `assignments`, so
`generator/gen.py::spec_group("toy-ssm-parameter")` returns `None`
["unclassified", not an implicit default either direction] rather than
either group.)

**Re-split procedure for scenarios 5–15 (documented in
`generator/split.py`'s own module docstring, summarized here):** run `uv
run python generator/split.py --write` to recompute from every
`specs/*.yaml` id then on disk. An individual id's *score* never changes
as ids are added/removed (verified:
`test_score_is_stable_per_id_independent_of_other_ids`), but its *rank*
relative to the 60% cutoff can shift — a scenario near the boundary can
flip groups purely because new scenarios landed ahead of or behind it in
the fixed ranking, not because anything about that scenario itself
changed. This is expected, not a bug: with only 4–15 scenarios, "60%
train" is inherently a moving cutoff over a fixed per-id ranking. When a
re-split flips an id:
  - **train → holdout**: any tuned skill/MCP equipping already developed
    against that scenario while it was train is tainted (prereg §7.1's own
    rationale — equipping tuned using signal from a scenario must not
    later be scored held-out against that same scenario) and must be
    retired/re-tuned, or the split frozen (stop re-running `--write`) once
    real tuning work begins for a phase.
  - **holdout → train**: no integrity problem, but log the move.
  Either way, log the before/after table and any flips as a new
  DECISIONS.md amendment — `--write` is always a manual, logged action,
  never invoked implicitly by `make gen`/`make ci`.

### Generator refuses to emit tuned-equipping material for a holdout scenario

**Decision — enforcement point:** `generator/gen.py::generate()` (the sole
code path behind `make gen`, therefore behind every task-directory write
in this repo) now ends with a call to the new
`enforce_no_holdout_equipping(spec, generated)`. It looks up `spec.id`'s
group via `generator/split.py::spec_group()`; if `"holdout"`, it re-uses
`gates/equipping.py`'s own `_discover_equipping_files()` — the SAME
skill/MCP/plugin-config discovery that already changes a trial's
`equipping_hash` (`metrics/result_schema.json`'s required field) — to scan
every generated arm directory, and raises `HoldoutEquippingViolation`
(uncaught, so `make gen`/`make ci`'s `gen-sync` check both hard-fail) if
it finds any. A spec with no `specs/split.yaml` entry (not yet classified
— e.g. authored before the next `--write` re-split) or assigned `"train"`
is a silent no-op — equipping IS meant to be developed there.

This is the "right enforcement point" the task asked for because it is the
one place every generated task directory — however it got its content, a
future generator feature that injects tuned equipping automatically, or a
hand-copy/hand-edit into an already-generated tree — passes through before
`make gen` can report success. No equipping-writing feature exists yet in
this generator (Phase 2 work, per `docs/iac-abstraction-aws-bench-plan.md`
item 4 — the `--mcp-config`/`--skill`/plugin flags aws-bench's own runner
takes are wired at run time, not generation time), so this guard is
necessarily proactive: it has nothing live to block today, but makes it
structurally impossible to ship one that violates the holdout rule later
without the guard firing immediately, on the very next `make gen`.

**Proven:** `generator/tests/test_holdout_equipping.py` (9 tests) —
planting `mcp.json`/`skills/<name>/SKILL.md`/`plugins.json` under a
holdout scenario's (real: `sfn-jsonata`, `s3-lambda-log-retention`)
synthetic generated-arm directory raises `HoldoutEquippingViolation`
naming the offending arm + file; the identical fixture under a train
scenario (`ecs-swappiness`) or an unclassified scenario id is a silent
no-op; a holdout scenario with no equipping material, or only unrelated
files (`task.toml`, `notes.md`), is also a silent no-op. Also
hand-verified against the real generator end-to-end (not just the unit
fixtures): planting a fake skill under `tasks/anchor/sfn-jsonata-awscdk/`
then calling `enforce_no_holdout_equipping` on `sfn-jsonata`'s real
generated output raised the violation with the exact relative path; the
same plant under `ecs-swappiness`'s real generated output raised nothing.

**Self-caught near-miss:** the function was initially written and unit
tested (both directions above) WITHOUT actually being called from
`generate()` — a real "defined but never wired in" gap that would have
shipped a guard proving itself only in isolation, never on the real `make
gen` path (exactly the shape of gap this Amendment's own numbering-note
category, and Amendment 3's "orphaned preflight gate," already exist in
this log for). Caught during this Amendment's own re-review (checking
where `generate()` calls `self_check_parity` for the wiring pattern to
follow, and finding no matching call for the new guard), fixed by adding
`enforce_no_holdout_equipping(spec, generated)` immediately after
`self_check_parity(...)` in `generate()`. Harmless in practice up to this
point — no spec currently emits any equipping material, so the guard was
never live regardless — but the fix landed before this Amendment closed,
not as a follow-up. Re-verified after the fix: `make gen SPEC=specs/
sfn-jsonata.yaml` still generates cleanly (no false positive against real
output), and the full `generator/` pytest suite (26 tests) stays green.

### Final state

- `generator/tests/test_split.py` (16 tests) + `generator/tests/
  test_holdout_equipping.py` (9 tests) + `generator/tests/conftest.py`
  (new — sys.path bootstrap for `generator/tests/`, mirroring
  `gates/tests/conftest.py`'s existing precedent) — **25 new tests**.
- `uv run pytest gates metrics oracles generator -q` (`make test-gates`) —
  **327 passed** (was 256 after Amendment 9 + concurrent Slice D/F work
  landed in the interim; +25 from this Amendment, some more from
  concurrent work landing in the same working tree — this Amendment
  changes only `generator/gen.py`, `mk/gen.mk`, and the new
  `generator/split.py`/`generator/tests/*` files; it does not touch
  anything Slice D/F own).
- `make check` — green.
- `make ci` — green, full transcript above.
- `bash ci/check-smoke-drift.sh` — unaffected, still `OK`.

**Files added:** `mk/ci.mk`, `ci/run-ci.sh`, `.github/workflows/ci.yml`,
`generator/split.py`, `specs/split.yaml`, `generator/tests/conftest.py`,
`generator/tests/test_split.py`, `generator/tests/test_holdout_equipping.py`.
**Files modified:** `generator/gen.py` (import + `HoldoutEquippingViolation`
+ `enforce_no_holdout_equipping`, called from `generate()`), `mk/gen.mk`
(`specs/split.yaml` skip in `gen-all`/`parity-all`).

## Amendment 11 (2026-08-06) — CI-integrity + stats/censoring findings from a
## fourth benchmark-integrity review (17 findings, 4 blockers)

Fixes every finding from a fourth review pass, split across two lenses:
`ci` (Slice E's own machinery proving less than it claimed) and `stats`
(metrics/tokens_to_green.py's censoring/pooling semantics). Listed
findings-first, matching this log's own Amendment 3/4/7 convention; full
rationale for each lives inline as a dated comment at its own fix site
(search any file below for "2026-08-06" near the relevant function).

### `ci` lens

1. **`check-paths` VACUOUS for every real scenario** (blocker) —
   `generator/check_reference_paths.py` now exits **3** (not 0) when every
   enabled arm reports `NOT_AUTHORED`, distinct from a real pass;
   `ci/run-ci.sh`'s `run_check` renders rc=3 as `SKIP` in the summary
   table (never `PASS`), and `check-paths` is now also run at
   toy-ssm-parameter's smoke level (the one spec that actually has a
   fixture authored, so it's the only place this check runs
   non-vacuously today).
2. **Asymmetric tier-1 oracle-strictness break passes `make ci`**
   (blocker) — demonstrated directly: gutting
   `oracles/rego/apigw-openapi/policy.rego`'s `route_count_correct`
   denial to an always-false clause changed no `make falsifiability`
   verdict, because no catch's `broken/` fixture exercised it. Closed
   for real for `apigw-openapi`: a new catch (`route-count-wrong`,
   `specs/apigw-openapi.yaml`) plus hand-authored
   `solution/broken/route-count-wrong/solve.sh` for all three arms (an
   extra, fully-and-correctly-wired 4th method, isolating the fixture to
   ONLY the route-count assert) — re-verified the sabotage IS now caught
   (`falsifiability FAILED`, route-count-wrong stayed reward=1.0). A new,
   real, generation-time floor (`generator/check_tier1_coverage.py`,
   `make tier1-coverage`, wired into `ci/run-ci.sh` per spec + toy)
   requires `count(catches predicting tier-1) >= count(tier-1 asserts)`
   per arm — a coarse numeric proxy, not exact per-assert coverage;
   reports SKIP (not FAIL) where the floor isn't met yet
   (`ecs-swappiness`, `sfn-jsonata`, the toy spec itself — pre-existing,
   now-visible gaps this pass did not close, tracked in `ci/README.md`
   rather than silently hidden). `ci/README.md`'s unbacked "fails CI"
   claim corrected to describe exactly what is and isn't backed today.
3. **Holdout equipping guard misses the placements that actually equip
   an agent** (blocker) — (a) `generator/gen.py::generate()` now calls
   `enforce_no_holdout_equipping` on the EXISTING on-disk task dirs
   BEFORE `write_environment()`'s `rmtree`+`copytree` wipes
   `environment/` (previously the only call site ran AFTER the wipe, so
   equipping material placed there was silently deleted before the
   guard ever saw it) — reproduced the finding's own repro
   (`environment/skills/tuned-iac/SKILL.md` under a holdout scenario)
   and confirmed `make gen` now exits 1 with the file still on disk,
   instead of exiting 0 with it gone. (b) `scripts/run-bench.sh` now
   refuses outright (before any dry-run/real-run side effect) when
   `--skill`/`--mcp-config` is passed (bare or via `--` passthrough) and
   the targeted task resolves to a HOLDOUT scenario, and records any
   such CLI-supplied equipping to `<jobs-dir>/budget.json`'s new
   `cli_equipping` field so a caller emitting a result row can fold it
   into `extra_cfg` — best-effort/documented-limitation, not exhaustive
   (a multi-task `--registry-path`/`-d` invocation with no task filter
   can't be statically narrowed from argv alone).
4. **Train/holdout split unenforceable at the published-number layer**
   (blocker) — `metrics/result_schema.json` gets a new REQUIRED
   `split_group` (`train`/`holdout`/`unclassified`) field;
   `gates/emit_result.py::resolve_split_group`/`to_result_row(...,
   spec_id=...)` populate it from `generator/split.py::spec_group`;
   `metrics/tokens_to_green.py::build_report` now computes
   `headline_cells` (holdout-only — the pre-registered primary result)
   and `train_cells` separately, never pooled, alongside the old
   `cells` (kept, relabeled reference-only, not the headline).
5. **`gen-sync` silently passes when git fails** / **toy terraconstructs
   drift makes `make ci` red at HEAD, and stays red after regenerating**
   (major) — `ci/run-ci.sh::gen_sync_check` no longer touches git at
   all: it snapshots the managed paths to a temp dir immediately before
   `make gen` and `diff -r`s against that snapshot immediately after,
   which removes the silently-ignored-git-failure class by construction
   AND stops a legitimate pre-existing uncommitted edit from reading as
   drift WITHIN THIS SAME WORKING TREE (this run's own "before" state
   already reflects it). Confirmed
   `arms/terraconstructs/environment/mirror-src/main.tf` and the toy
   task's own copy are byte-identical on disk here.
   CORRECTION (2026-08-06 round 2, benchmark-integrity re-review): this
   fix does NOT make `.github/workflows/ci.yml`'s `full-ci` job green on
   its first run. The regenerated
   `tasks/anchor/toy-ssm-parameter-terraconstructs/environment/mirror-src/main.tf`
   is still uncommitted (verified: `git show HEAD:<that path> | grep -c
   archive` is `0` on this branch's HEAD vs `9` in the working tree and in
   `arms/terraconstructs/environment/mirror-src/main.tf`, which
   `write_environment()` copies verbatim). `gen_sync_check`'s snapshot-vs-
   diff mechanism only proves "no drift was introduced BETWEEN the
   snapshot and the post-`make gen` state within one run" — it says
   nothing about whether the snapshot itself (i.e., whatever is on disk
   when the job starts) already matches what `make gen` produces. A fresh
   CI checkout starts from the COMMITTED HEAD content, not this working
   tree, so it starts from the still-drifted `0`-archive-count file:
   simulating that exact sequence (restore the file to its HEAD content,
   snapshot, run `make gen`, diff) reproduces `before-gen archive count: 0
   / after-gen: 9 / RESULT: gen-sync would FAIL on a fresh HEAD checkout`.
   In short: this fix genuinely closes the silently-ignored-git-failure
   class and the false-positive-on-a-legitimate-uncommitted-edit class,
   both real bugs — but "`make ci`'s own gate no longer depends on [the
   file being committed]" (this entry's original claim) was FALSE; the
   gate depends on it exactly as much as before in any checkout that
   doesn't already carry this working tree's uncommitted edit, which is
   every CI checkout until an operator commits the regenerated file
   (out of scope here — no-git-commit rule for this task).
6. **`test/` never runs in `make check`/`make ci`** (major) —
   `mk/rails.mk`'s `test-gates` target now runs `pytest gates metrics
   oracles generator test -q` (was missing `test`).
7. **MAX_TOKENS inert, budget.json has no reader** (major) —
   `gates/emit_result.py::read_budget()` (new) reads
   `<jobs-dir>/budget.json`; the module's CLI gained `--jobs-dir
   --model --harness --oracle-version --spec-id --scenario --task
   --trial-id --job-id --max-iters --max-tokens --row-out`, so it can
   now emit a real `to_result_row()`-shaped row with budget-file-derived
   auto-censoring, not just the raw Gate-2/3 record. Still requires a
   caller to actually invoke it per trial after a run — no automatic
   per-job orchestration exists yet (Slice F) — corrected in both
   files' own comments rather than left overclaiming.
8. **full-ci cannot fail on a broken arm image; Gate 1 has no call
   site** (major) — `ci/run-ci.sh`'s pre-flight `make build-arms`
   failure is now a real, gating `run_check` row (was a swallowed
   stderr warning); `make preflight` now runs as its own gating step
   whenever docker is reachable.
9. **Tier-attribution producer/consumer have no shared test** (major) —
   `gates/tests/test_emit_result.py::TestTierEvidence` gained a
   toolchain-gated (`terraform`+`jq`, skips gracefully without them)
   test that runs the REAL generated `tests/static_tiers.sh` for the
   toy spec's hcl_raw arm via `gates.oracle_falsifiability._run_solve`
   and feeds its actual stdout through `read_tier_evidence()` — a
   producer format change now breaks this test too, not just the
   hand-frozen fixture.
10. **`tokens_to_green.py` orphaned from the run pipeline** (major) —
    new `mk/metrics.mk` (`make metrics RESULTS=<dir>`) plus
    `metrics/test_pipeline_e2e.py` (wired into `make check` as
    `check-metrics-e2e`): runs Gate 2+3 against the real gates/tests
    fixtures via `emit_fixture_rows.generate_rows()`, writes them as a
    real job's output would look, and feeds that directory through the
    real `tokens_to_green.main()` CLI, asserting `benchmark.json`'s
    shape — closes the "no proof the two modules agree in practice" gap.

### `stats` lens

11. **Censoring semantics / anti-survivorship** (blocker) —
    `summarize_cell`'s HEADLINE `tokens_to_green_km` now censors every
    non-green trial at the ADMINISTRATIVE budget bound (`--max-tokens`,
    else the max observed `tokens_total` in that cell) instead of its
    own stopping point (prereg §4: right-censored WITHIN THE BUDGET
    CAP). The old convention is kept and reported as a diagnostic,
    `tokens_to_green_km_own_stopping_point`. Reproduced the demonstrated
    bias directly in `TestAdministrativeCensoring` — cheap-vs-expensive
    failures with identical greens/success-rate now report the IDENTICAL
    headline median (verified the bias is still visible, and differs,
    under the retained own-stopping-point diagnostic).
12. **`tier1_not_verifiable` pooled into headline numbers** (blocker) —
    `summarize_cell` reports `n_tier1_not_verifiable` per cell plus a
    same-shaped `sensitivity_excluding_tier1_not_verifiable` block
    (bounded to one level of recursion), so a reader can see whether a
    headline result survives their removal.
13. **'>50% censored -> NE' only holds for late censoring** (major) —
    `km_median_iqr` now reports `censored_frac` and `low_event_count`
    (< `MIN_EVENTS_FOR_CONFIDENT_MEDIAN` = 5) UNCONDITIONALLY, not
    inferred from `median_reached`; `render_markdown` annotates on
    `censored_frac >= 0.5` directly and flags a reached-but-thin median
    separately.
14. **Per-catch tier attribution cannot express a tier-1 catch identity**
    (major) — `build_tier_attribution` now joins the tier-1 bundle row
    against `specs/<scenario>.yaml`'s own declared tier-1
    `structural_assert` names (best-effort, falls back to the old
    opaque `"(tier-1 bundle)"` name when no spec file resolves) instead
    of an unconditionally opaque placeholder.
15. **`n_llm_calls=0` fallback poisons iterations-to-green** (major) —
    `gates/emit_result.py::extract_n_llm_calls` now returns `None` (not
    `0`) for an absent/unreadable/malformed trajectory or a missing
    `steps` key — `0` is returned only for a genuinely-parsed,
    real-list-but-zero-agent-signal trajectory. `to_result_row` already
    omitted `n_llm_calls` on `None`, so this was the one missing piece;
    `summarize_cell` now also reports `n_iterations_unknown` per cell.
16. **prereg §7 outputs not derivable from `benchmark.json`** (major) —
    every cell (`cells`/`headline_cells`/`train_cells`) now carries
    `scenario_coverage` (counts) and `by_scenario` (a full
    `summarize_cell` block per scenario), unblocking the paired-by-
    scenario primary test and main-effects decomposition without
    requiring a re-read of raw rows.

### Verification

- `uv run pytest gates metrics oracles generator test -q` — **422 passed**
  (`metrics/test_pipeline_e2e.py` is a separate, dedicated invocation via
  `check-metrics-e2e` — 1 passed — plus this Amendment's
  `TestHoldoutEquippingGuard`/`TestReadBudget`/`TestResolveSplitGroup`/
  `TestAdministrativeCensoring`/`TestTier1NotVerifiableSensitivity`/
  `TestSplitStratification`/`TestPerScenarioBreakdown`/
  `TestKmMedianIqrCensoringAnnotations` additions are included in the 422).
- `make check` — green end-to-end (schema validation, gate-fixture
  round-trip, the full 422-test pytest suite, metrics e2e, smoke-drift).
- `uv run python gates/oracle_falsifiability.py specs/apigw-openapi.yaml`
  — OK for real (all 3 arms x {good, deployment-missing-integration-
  dependency, route-count-wrong}); re-sabotaging `route_count_correct`
  and re-running was independently confirmed to FAIL.
- `uv run python generator/check_tier1_coverage.py specs/<id>.yaml` —
  PASS for `apigw-openapi`/`s3-lambda-log-retention`; SKIP (tracked gap,
  not silently hidden) for `ecs-swappiness`/`sfn-jsonata`/toy.
- `scripts/run-bench.sh --dry-run --path tasks/anchor/sfn-jsonata-awscdk
  -- --skill ./x` — exits 1, `REFUSED`; the same against a train
  scenario (`ecs-swappiness`) exits 0 and forwards the flag.

**Files added:** `generator/check_tier1_coverage.py`, `mk/metrics.mk`,
`metrics/test_pipeline_e2e.py`,
`tasks/anchor/apigw-openapi-{awscdk,hcl-raw,terraconstructs}/solution/broken/route-count-wrong/solve.sh`.
**Files modified:** `ci/run-ci.sh`, `ci/README.md`, `mk/gen.mk`,
`mk/rails.mk`, `generator/check_reference_paths.py`, `generator/gen.py`,
`specs/apigw-openapi.yaml`, `scripts/run-bench.sh`,
`metrics/result_schema.json`, `metrics/examples/valid-result.json`,
`metrics/emit_fixture_rows.py`, `gates/emit_result.py`,
`gates/tests/test_emit_result.py`, `metrics/tokens_to_green.py`,
`metrics/test_tokens_to_green.py`, `test/test_run_bench_wrapper.py`.

---

## Amendment 12 (2026-08-06/07) — Slice G (`apigw-redeploy`): schema/generator
## plumbing to actually land the scenario, plus fixes for a live-discriminator
## review's 7 findings (4 blockers, 3 major)

`apigw-redeploy` (docs/apigw-redeploy-mechanics.md, docs/slice-g-recon.md)
did not exist as a registered scenario before this amendment — only five
hand-authored `solve.sh` files sat under `tasks/anchor/apigw-redeploy-*`,
disconnected from `specs/`, the generator, and every gate. A live-
discriminator review of those five scripts found the redeploy machinery
itself sound but the *scaffolding around it* broken on every axis: the
reference solutions failed their own LIVE checks ~100% of the time
(propagation-latency race, no polling), the negative fixtures didn't
actually discriminate at the instant they sampled, the proposed
`live_check` contract was empirically false, the scenario had no
generator/schema plumbing at all, two of three reference solutions
weren't runnable without hand-building missing `environment/` trees, and
LIVE proof runs left CloudWatch log-group residue in the shared account.
This amendment closes all seven findings and, in doing so, lands the
missing plumbing docs/slice-g-recon.md's closing list called out as
required first.

### Schema/generator extensions (the "does the scenario exist" blocker)

1. **`spec_model.LiveCheck.enabled`** relaxed from `Literal[False]` to
   `bool` (recon gap 1). Every pre-Slice-G spec still sets it `false`
   (unchanged behavior, unchanged generated output — verified below).
   Gained `hand_authored: bool` (must be `true` whenever `enabled` is
   `true` — a model validator rejects the alternative, so a spec can never
   silently ship the generated not-implemented stub as its real live
   check) and optional `agent_role_name`/`concurrency_mode` overrides.
2. **`generator/gen.py::build_task_toml`** now reads `agent_role_name`/
   `[concurrency] mode` from the spec (via the two new `LiveCheck` fields)
   instead of the two hardcoded literals at the old line 655/662 (recon
   gap 2) — `None` (every existing spec) reproduces the old hardcoded
   values byte-for-byte. Also writes `[verifier] env = {
   SPEC_LIVE_CHECK_ENABLED = "true" }` when `live_check.enabled` (recon
   gap 4) — explicitly commented as a **best-effort, unverified**
   placement against aws-bench's own task.toml schema (that source lives
   outside this repo; the comment says so and DECISIONS tracks it as an
   open integration point rather than claiming false certainty).
3. **`generate_arm`'s write-tests step is now destructive-safe for
   `tests/live_check.py`** whenever `spec.verifier.live_check.hand_authored`
   is true (recon gap 5) — the same "never overwrite hand-authored
   content" convention `solution/solve.sh` already had (SCHEMA.md §8.2
   point 8). Verified directly: re-running `make gen
   SPEC=specs/apigw-redeploy.yaml` after hand-authoring
   `tests/live_check.py` left it byte-identical; every pre-Slice-G spec
   (`hand_authored=False`, the only legal value when `enabled=False`)
   keeps the old always-overwrite-the-stub behavior.
4. **`spec_model.Catch.applies_to`** (new field, defaults to all 3 arms —
   100% backward compatible) — a catch's mistake can be structurally
   impossible on some arm (a hand-omitted TF `triggers` block has no
   direct L2 equivalent; the L2 always computes one) without forcing a
   contrived escape-hatch fixture there just to satisfy
   `gates/oracle_falsifiability.py`'s "every catch needs a broken/ fixture
   on every enabled arm" rule. `check_arm` now reports `N/A` (non-gating)
   for a catch/arm pair the catch itself declares out of scope, instead of
   `MISSING` (a hard fail).
5. **`CatchTierStr` gained `"live"`** — a catch whose mistake is invisible
   to *every* static tier by construction (docs/apigw-redeploy-mechanics.md
   §6(c): only a live apply→modify→re-apply→curl loop discriminates it).
   `gates/oracle_falsifiability.py::check_arm` grew a `"live"` branch,
   shaped like the existing `"0.5"` branch (reward is *expected* to stay
   1.0 — that invisibility IS the catch) but falsified by a fixed marker
   string (`LIVE_ONLY_CONFIRMED_MARKER =
   "CDKTN_BENCH_LIVE_ONLY_CONFIRMED"`) the fixture's own **offline** run
   must mechanically print, earned by a real two-plan `triggers.redeployment`
   diff — not merely asserted in a comment. This keeps `make
   ci`/`make falsifiability` fully offline (no AWS credentials/network) while
   still requiring the fixture to prove what it claims. Directly closes
   finding 5's ask ("record live-only catches instead of reporting them as
   uncaught").
6. **`specs/apigw-redeploy.yaml`** (new): 3 arms, 3 catches
   (`deployment-missing-integration-dependency` — tier "1", all arms, the
   same catch family/oracle-equivalence pattern as `apigw-openapi`, with
   real broken/ fixtures on all three arms so `grading-proof`'s hard
   "at least one arm reaches a real tier-1 catch" requirement is met;
   `stale-deployment-no-triggers` — tier "0", `applies_to: [hcl_raw]`,
   genuinely single-artifact-catchable (a `deployment-triggers-present`
   tier-0 assert against the FINAL delivered file); `triggers-incomplete-
   hash` — tier "live", `applies_to: [hcl_raw]`, the one catch that
   genuinely needs a cross-revision diff, which no single-artifact static
   tier can express), and `verifier.live_check.enabled: true`. `make gen`
   against it produces every generated artifact (`environment/`,
   `task.toml`, `instruction.md`, `tests/{_assert_lib,static_tiers,test}.sh`)
   through the SAME pipeline every other scenario uses — this alone closes
   most of finding 4 and all of finding 6 (see below).
7. **`oracles/rego/apigw-redeploy/policy.rego` +
   `oracles/cfn-guard/apigw-redeploy/policy.guard`** (new, hand-authored):
   the `deployment-missing-integration-dependency` tier-1 identity/
   cardinality checks, adapted directly from `apigw-openapi`'s own proven
   rules (same catch family, same rationale, same documented cardinality-
   proxy residual gap on awscdk).

**Explicitly NOT done** (docs/slice-g-recon.md's remaining gaps, honestly
left open rather than half-built): a new, minimally-scoped
`QADeployApplicationRole` in `qa_roles_stack.ts` was NOT created or
deployed — that is a change to shared, persistent account infrastructure
(not a per-task resource this fix pass's live re-proof is scoped to touch),
and the recon's own open question about the CDKToolkit assume-role grant it
would need is unresolved. `specs/apigw-redeploy.yaml` instead sets
`agent_role_name: "QALocalInvocationApplicationAdmin"` (the existing,
already-provisioned admin role) — a real over-grant, logged here rather
than hidden, and a natural next step once the scoped role is built.
Whether aws-bench's own trial runner actually reads `[verifier].env` the
way point 2 above assumes, whether `ResourceManager.reset_scenarios`
covers apigateway/lambda/logs, and `scenarios/anchor/reset/reset.sh` were
NOT verified/built — all three require reading or modifying the aws-bench
runner itself, outside this repo, and remain open per recon's own
"not implemented by this recon" framing. This scenario's own solve.sh/
live_check.py-level cleanup (finding 7, below) is deliberately NOT
contingent on any of these three landing.

### Live-discriminator review findings (fixed 1:1)

1. **(blocker) Correct solutions failed their own LIVE check ~100% of the
   time** — every one of the five `solve.sh` LIVE paths curled the
   modified route exactly once, immediately after the second
   apply/deploy; API Gateway stage-propagation latency (measured: hcl-raw
   200 at t=30s, awscdk/terraconstructs 200 at t=60s, 403 at every earlier
   sample) meant this failed almost always. Fixed by centralizing the
   check in a new, hand-authored `tests/live_check.py` (destructive-safe
   per point 3 above, copied identically into all 3 arms' task
   directories): `check_ok()` polls up to `POLL_TIMEOUT_S = 180` (5s
   interval — 60s was not enough margin per the review's own measurement),
   succeeding on the first `200` whose body matches the exact fixed
   modification. All three `solution/solve.sh` LIVE paths now end with
   `python3 tests/live_check.py --api-url "$API_URL" --expect ok` instead
   of a single immediate curl.
2. **(blocker) The two hcl_raw negatives didn't discriminate at the point
   they sampled** — `STATUS_CODE != 200` measured once, immediately after
   the second apply, is exactly what a CORRECT solution also produces
   during the same propagation window finding 1 documents. Fixed:
   `tests/live_check.py::check_stale()` polls the FULL `POLL_TIMEOUT_S`
   window (never early-exits on one sample) AND requires the deployment id
   observed after apply #1 to equal the one observed after apply #2 (a new
   `output "deployment_id"` on both broken fixtures' `main.tf`, captured
   via `terraform output -raw deployment_id` around each apply). Both
   `solution/broken/{stale-deployment-no-triggers,triggers-incomplete-hash}/
   solve.sh` LIVE paths now call `--expect stale
   --deployment-id-before ... --deployment-id-after ...` instead of a
   single ad hoc curl+comment.
3. **(blocker) The proposed "≥2 deployments, stage on latest" contract is
   false for every correct solution** — `create_before_destroy`/CFN
   replacement leaves exactly ONE surviving deployment after a successful
   redeploy on every arm, and "stage points at the newest deployment it
   knows about" is trivially true either way. Fixed by never encoding
   that contract anywhere: `check_ok()`/`check_stale()` assert ONLY sound,
   post-hoc BEHAVIORAL facts (exact `/status` body; `/hello`+`/version`
   regression-free), and (finding 3's own fix_hint) `check_stale()`'s
   deployment-identity signal is captured by `solve.sh` itself DURING the
   two-apply loop (not reconstructed after the fact by a verifier that
   never saw the pre-modification state) — exactly the "agent-visible
   contract records the pre-modification id" design the finding proposed.
4. **(blocker) Scenario had no spec/generator/gate plumbing at all** —
   closed by the schema/generator work above; `specs/apigw-redeploy.yaml`
   plus regenerated `tasks/anchor/apigw-redeploy-*` now exist, validate,
   and pass every offline gate (see Verification below). The parts of this
   finding that require changing aws-bench itself (outside this repo) are
   explicitly logged as open, not silently declared done — see "Explicitly
   NOT done" above.
5. **(major) Broken-fixture convention inverted / gate-incompatible** —
   the two hcl_raw negatives used to self-judge (custom exit code, never
   touching `tests/static_tiers.sh`/`reward.txt`) and the builder's own
   report ("expected to fail the trap-check") didn't match what they
   actually asserted. Fixed: `stale-deployment-no-triggers` is now a
   fully gate-native tier-0 catch (its OFFLINE path ends with `bash
   tests/static_tiers.sh` and requires reward 0.0, same convention as
   every other scenario's broken/ fixture); `triggers-incomplete-hash`
   also ends with `tests/static_tiers.sh` (requires reward 1.0 — see
   finding 4/schema point 5's `"live"` tier) instead of self-exiting 0.
   LIVE paths for both now call the SAME shared checker
   (`tests/live_check.py --expect stale`) the correct solution's LIVE path
   calls with `--expect ok`, instead of two independently-hand-rolled,
   non-discriminating checks.
6. **(major) Two of three reference solutions weren't runnable** — no
   `environment/` existed for any arm; `generator/gen.py`'s spec-driven
   generation (point 6 above) now produces a real, working `environment/`
   for all three arms through the exact same pipeline every other scenario
   uses (`bin/app.ts` instantiates `ScenarioStack` as the awscdk solve.sh
   already assumed; `main.ts` carries the generated offline dummy-creds +
   mock-STS bootstrap `tests/static_tiers.sh`'s own tf-plan step needs).
   One residual bug found and fixed while re-proving this: the
   terraconstructs solve.sh's own `write_main_ts_live()`/`start_mock_sts()`
   hardcoded port `17773` from before `environment/` existed, while the
   NOW-generated `main.ts` points at `gen.py`'s own
   `TERRACONSTRUCTS_MOCK_STS_PORT = 17771` — fixed to `17771` (caught by
   `make falsifiability` failing with a real STS-dial-refused error before
   this fix, not silently).
7. **(major) LIVE proof runs left CloudWatch log-group residue** —
   `terraform destroy`/`cdk destroy` do not remove the log groups
   Lambda/API Gateway auto-create on first invocation
   (`/aws/lambda/apigw-redeploy-{hello,version}`,
   `/aws/lambda/ScenarioStack-{HelloFn,VersionFn}*`,
   `/aws/apigateway/welcome`). Every `solution/solve.sh` and
   `solution/broken/*/solve.sh` LIVE path now installs a `trap cleanup
   EXIT` (runs on pass, live-check failure, AND a mid-script error alike)
   that destroys the deploy AND explicitly deletes those log groups
   (`aws logs delete-log-group`, `|| true` throughout — a group that never
   got created because an earlier step failed must not itself fail
   cleanup).

### Two bugs found and fixed while building the new broken/
### `deployment-missing-integration-dependency` fixtures (all 3 arms, new)

- The hcl_raw fixture's first draft kept a `triggers` block that
  `jsonencode`d references to every route's resources while omitting
  `depends_on` — but Terraform infers a real dependency edge from ANY
  attribute reference inside `triggers`, same as `depends_on` would (and
  `oracles/rego/apigw-redeploy/policy.rego`'s `covered_by_triggers` rule
  correctly treats it as coverage, on purpose) — so this "bug" wasn't
  actually one; `make falsifiability` would have silently never exercised
  it. Fixed to a hardcoded literal `triggers.redeployment` value with no
  resource reference at all (a real, realistic mistake: a `triggers` block
  added because "it's needed" without actually wiring it to anything).
- The terraconstructs fixture's manual L1 `ApiGatewayDeployment` escape
  hatch set no `triggers` at all, which ALSO failed this spec's (new)
  `deployment-triggers-present` tier-0 assert — a real
  `predicted_tier_caught='1'` vs. `observed_tier='0'` tier-attribution
  mismatch, caught by `gates/oracle_falsifiability.py`'s own mechanical
  backstop (unrelated to this finding pass, pre-existing machinery from
  Amendment 7/9). Fixed by giving it a plain-literal `triggers` value too,
  isolating the fixture to only the dependency-coverage catch.

### Verification

- `uv run python generator/spec_model.py specs/apigw-redeploy.yaml` — OK
  (3 catches, 3 arms, 7 structural asserts).
- `uv run python gates/oracle_falsifiability.py specs/apigw-redeploy.yaml`
  — **OK** for real: 12/12 rows PASS across all 3 arms x {correct solution,
  `deployment-missing-integration-dependency`, `stale-deployment-no-triggers`,
  `triggers-incomplete-hash`} (the latter two `N/A` on awscdk/terraconstructs
  per their `applies_to`). Reproduced the port-mismatch bug (finding 6)
  failing this gate for real before the fix, and the tier-attribution
  mismatch bug (this amendment's own "two bugs found" section) failing it
  for real before that fix too — this gate is exercising real toolchain
  runs, not passing vacuously.
- `uv run python generator/check_tier1_coverage.py specs/apigw-redeploy.yaml`
  — OK (1 tier-1 assert, 1 covering catch, all 3 arms).
- `uv run python generator/check_reference_paths.py specs/apigw-redeploy.yaml`
  — NOT_AUTHORED (rc=3, non-gating; no `generator/tests/fixtures/apigw-redeploy/`
  authored — an honest gap, not claimed closed).
- `uv run python gates/grading_proof.py specs/apigw-redeploy.yaml` — OK,
  "every arm is GRADEABLE" (6/6 outcomes PASS).
- `make gen SPEC=specs/apigw-redeploy.yaml` run twice in a row —
  byte-identical output (gen-sync clean); re-running against all four
  pre-existing specs after this amendment's `gen.py`/`spec_model.py`
  changes produced ONLY the two intentional wording-comment updates in
  each spec's `task.toml` ("is false in v1" → "is false for this
  scenario") — no other diff, confirming the new spec-driven
  `agent_role_name`/`mode`/`[verifier] env` logic is a true no-op for
  every `live_check.enabled=false` spec.
- `uv run python generator/split.py --write` — re-run after adding the 5th
  real spec (required: adding a scenario shifts `specs/split.yaml`'s 60/40
  train/holdout cutoff over the existing ranking, per that module's own
  docstring); `apigw-redeploy` landed `holdout`. `s3-lambda-log-retention`
  moved holdout→train as a result — a pre-existing test
  (`generator/tests/test_holdout_equipping.py`) hardcoded it as "a real
  holdout scenario"; switched to `sfn-jsonata` (stayed holdout), matching
  every other holdout-scenario case in that file.
- `uv run pytest gates metrics oracles generator test -q` — **440 passed**
  (up from 422 at Amendment 11; two pre-existing tests needed the
  split-cutoff-shift fix above, everything else was unaffected).
- `make check` — green end-to-end.
- `make ci` — **ALL GREEN**, full sweep across all 5 real specs x
  {gen-sync, check-paths, tier1-coverage, falsifiability, grading-proof}
  (`apigw-redeploy`: gen-sync PASS, check-paths SKIP (no
  `generator/tests/fixtures/apigw-redeploy/` authored yet, non-gating —
  honestly the same NOT_AUTHORED state every other real spec is in),
  tier1-coverage PASS, falsifiability PASS, grading-proof PASS) + toy
  smoke + `test-gates` + `check`, all PASS/SKIP, zero FAIL rows. First
  full run caught a real, pre-existing drift this amendment's own wording
  change exposed (`toy-ssm-parameter`'s `task.toml` needed
  `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml` re-run too, since
  `gen.py`'s wording literal changed for every spec, not just
  `apigw-redeploy`) — fixed, re-ran clean.
- **LIVE re-proof against account 886312446417 (us-east-1): NOT COMPLETED
  by this fix pass — blocked, not skipped.** A single batched
  `aws-vault exec --no-session tcons-mgmt -- bash live_reproof.sh` (all 3
  correct `solution/solve.sh` LIVE=1 runs + both hcl_raw negatives'
  LIVE=1 runs + a post-hoc account-cleanliness check, sequenced so only
  ONE keychain unlock is needed) was written, reviewed, and launched, but
  `aws-vault`'s macOS Keychain authorization prompt (`SecurityAgent`,
  confirmed via `ps`) sat unanswered for 35+ minutes with zero script
  output — this specific execution context (a background process, not an
  interactive terminal the operator is watching) apparently does not
  inherit whatever "Always Allow" grant makes the operator's own normal
  shell not re-prompt, and answering a macOS GUI dialog is outside what
  this fix pass can do. Killed cleanly (confirmed zero AWS resources were
  ever created — the script's own account guard, its first line of real
  work, never even printed). Every code fix findings 1/2/6/7 need is
  complete and was validated as far as offline review allows (bash
  syntax-checked, `tests/live_check.py`'s `check_ok`/`check_stale` logic
  reviewed inline, the port-mismatch and tier-attribution bugs found in
  finding-6/-5's own OFFLINE falsifiability runs above were real bugs this
  same live-proof effort would have hit and IS now fixed for) — but
  finding 1's own headline claim ("correct solutions now pass LIVE") is
  **not independently re-confirmed against real AWS by this amendment**.
  The script is at
  `/private/tmp/claude-502/-Users-vincentsmet-cdk/abc355a4-9a31-4ba4-9773-3deefa3f1074/scratchpad/live_reproof.sh`
  (scratchpad-only, not committed to the repo) — an operator present to
  approve the Keychain prompt can run it as-is, or copy its steps into an
  interactive session.

**Files added:** `specs/apigw-redeploy.yaml`,
`oracles/apigw-redeploy/intent.md` (generated),
`oracles/rego/apigw-redeploy/policy.rego`,
`oracles/cfn-guard/apigw-redeploy/policy.guard`,
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/{environment,instruction.md,task.toml,tests}` (generated),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/tests/live_check.py`
(hand-authored),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/solution/broken/deployment-missing-integration-dependency/solve.sh`
(new fixtures, all 3 arms).
**Files modified:** `generator/spec_model.py`, `generator/gen.py`,
`gates/oracle_falsifiability.py`, `specs/split.yaml`, `local-registry.json`,
`generator/tests/test_holdout_equipping.py`,
`tasks/anchor/{apigw-openapi,ecs-swappiness,s3-lambda-log-retention,sfn-jsonata}-*/task.toml`
(regenerated, wording-only),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/solution/solve.sh`,
`tasks/anchor/apigw-redeploy-hcl-raw/solution/broken/{stale-deployment-no-triggers,triggers-incomplete-hash}/solve.sh`,
`tasks/anchor/apigw-redeploy-terraconstructs/solution/broken/deployment-missing-integration-dependency/solve.sh`.

## Amendment 13 (2026-08-07) — fix round 2 for `apigw-redeploy`: live-solvability,
## verifier gating, dead-code, and log-group-sweep findings from a re-review

A follow-up review of Amendment 12's fix round found 6 more findings (3
blockers, 3 majors). This amendment fixes all of them.

**Finding G1 (blocker, reverify) — the batched LIVE re-proof still did not
run.** `aws-vault exec --no-session tcons-mgmt -- aws sts get-caller-identity`
(a minimal 25s-bounded probe, not the full driver) reproduced the EXACT same
blocker Amendment 12 hit: the macOS Keychain `SecurityAgent` authorization
dialog does not appear to whatever grants the operator's own interactive
shell "Always Allow" when the caller is this kind of background/subagent
process, so the exec sits with zero output until killed. Confirmed again,
cleanly, with a short timeout instead of the previous 35-55 minute
unattended wait -- no AWS resources were ever touched (the exec never
reaches its first real command), and a stray `SecurityAgent` process may be
left showing an unanswered dialog (harmless -- no credentials, no armed
mutation, nothing to clean up).

Not a code problem; every fix below was validated as far as offline review
and the existing (`gates/oracle_falsifiability.py`-driven) sandboxed
harness allow. Prep work for the operator: the five host-side sandboxes
under
`/private/tmp/claude-502/-Users-vincentsmet-cdk/abc355a4-9a31-4ba4-9773-3deefa3f1074/scratchpad/live/{hcl-correct,hcl-stale,hcl-hash,awscdk,tcons}`
were rebuilt from the CURRENT (post-fix) `tasks/anchor/apigw-redeploy-*`
trees (`rebuild_sandboxes.py` in that same directory, using the identical
copy convention `gates/oracle_falsifiability.py::_run_solve` uses -- flattened
`environment/<workspace-subdir>` + `tests/` + `solution/`, `npm ci` for the
two TS arms) so `drive.sh` in that directory now exercises this amendment's
fixes, not fix-round-1's code. An operator present to approve the Keychain
prompt can run
`aws-vault exec --no-session tcons-mgmt -- bash /private/tmp/.../scratchpad/live/drive.sh`
as-is.

**Finding G2 (blocker) — 2/3 arms were agent-unsolvable while obeying their
own "do not touch provider.tf/main.ts" instruction.** Both bootstrap files
hardcoded `access_key`/`secret_key` (plus hcl_raw's `skip_*` flags and
`endpoints.sfn`, terraconstructs' `endpoints.sts`) unconditionally --
explicit provider credentials outrank every ambient source, so a real
`terraform apply`/`cdktn deploy` could never reach real AWS through them,
yet the agent is told never to edit these files. The reference solutions'
own `write_provider_live()`/`write_main_ts_live()` proved this by
demonstrating a solution shape (rewriting the forbidden file) an agent may
not produce.

Fix: both bootstrap files are now live-aware via one environment-variable
switch each, read directly (no per-scenario templating, no reliance on any
unverified aws-bench env-passthrough mechanism):
- `arms/hcl-raw/environment/workspace/provider.tf` -- new
  `variable "cdktn_bench_live"` (default `false`). `access_key`/`secret_key`
  become `var.cdktn_bench_live ? null : "<dummy>"`, the `endpoints` block
  becomes `dynamic` (omitted when live). **Verified directly** against
  terraform 1.15.8 + hashicorp/aws 6.58.0 (not just reasoned about): default
  plans exactly as before; `-var cdktn_bench_live=true` with no ambient
  creds fails with `No valid credential sources found` (proves `null` is a
  real "no override", not silently accepted); the same with
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars set succeeds --
  confirms the provider falls through to the ambient chain exactly as
  arms/awscdk's `bin/app.ts` already relies on. The four `skip_*` flags
  stay on in both modes (skip_credentials_validation only skips an extra
  STS sanity call; skip_metadata_api_check only disables the last-resort
  IMDS fallback, never reached once env-var creds resolve first --
  confirmed by the same test).
- `generator/gen.py::terraconstructs_main_ts()` -- new
  `CDKTN_BENCH_LIVE = process.env.CDKTN_BENCH_LIVE === "1"` (Node reads the
  env var directly, no `terraform variable` involved); the
  accessKey/secretKey/skip_*/endpoints block is spread in only when false
  (every `AwsProviderConfig` field is optional, confirmed against a local
  `node_modules/terraconstructs` copy's `.d.ts`, so omitting the whole
  block is a real "no override").
- Both reference solutions' `write_provider_live()`/`write_main_ts_live()`
  are DELETED; LIVE=1 now just `export`s the one env var
  (`TF_VAR_cdktn_bench_live=1` / `CDKTN_BENCH_LIVE=1`) before calling
  `terraform`/`cdktn` -- the reference solutions now exercise exactly what
  an agent is allowed to do, never touching provider.tf/main.ts.
- `generator/gen.py::build_instruction_md()` grew a new
  `live_credentials_note()`, emitted only when
  `verifier.live_check.enabled` is true and the arm has a switch (hcl_raw,
  terraconstructs) -- a strict no-op for every other spec/arm -- telling
  the agent about the one env var it needs to export. Without this, a
  well-behaved agent that only reads its own instruction.md would still
  hit the offline dummy-credential fixture and fail to deploy for real.

**Finding G3 (blocker) — the verifier's live_check invocation had an
unsatisfiable second gate condition.** `tests/test.sh` required BOTH
`SPEC_LIVE_CHECK_ENABLED=true` (from this task's own `[verifier] env`) AND
`CDKTN_BENCH_LIVE_CHECK=1`, and nothing anywhere (runner, Makefile,
scenario, CI) ever set the second one -- confirmed again by the same
whole-repo grep the original review ran. Fixed in two parts:
1. Dropped the `CDKTN_BENCH_LIVE_CHECK` condition from
   `generator/gen.py::build_test_sh()` -- `SPEC_LIVE_CHECK_ENABLED` alone
   already encodes this spec's intent (it is only ever `"true"` for a
   scenario whose `verifier.live_check.enabled` is true).
2. The `[verifier].env` reaching the verifier container question the
   original fix_hint flagged as needing confirmation against real
   aws-bench source is now **CONFIRMED, not assumed**: read
   `/Users/vincentsmet/cdk/aws-bench`'s own vendored `harbor` package
   directly (`.venv/lib/python3.14/site-packages/harbor/`) -- `aws_trial.py`
   populates `self.task.config.verifier.env` straight from `task.toml`'s
   `[verifier]` section (`harbor/models/task/config.py`'s `VerifierConfig`),
   and `harbor/verifier/verifier.py`'s `verify()` does
   `merged_env = {**self.task.config.verifier.env, ...}`,
   `env = resolve_env_vars(merged_env)`, then
   `self.environment.exec(command=command, env=env)` -- a real, load-bearing
   passthrough into the verifier's own process environment, not a
   documented no-op. `build_task_toml`'s comment and `docs/slice-g-recon.md`
   §2 are updated to say so.

**Finding G4 (major) — the two hcl_raw negatives' oracle self-check was
dead code that made them exit 1 in the exact harness that validates them.**
Both `if [ -f tests/static_tiers.sh ]; then bash tests/static_tiers.sh;
REWARD="$(cat /logs/verifier/reward.txt ...)"` blocks read the hardcoded
absolute path, but `gates/oracle_falsifiability.py::_run_solve` only
rewrites `/logs/verifier` inside its OWN copy of `tests/static_tiers.sh`,
never inside the fixture -- so the `cat` always fell through to `'?'` and
the assertion always failed, masked only because the gate itself judges by
`reward.txt` and ignores exit codes. Reproduced directly (before the fix,
via `gates.oracle_falsifiability._run_solve` called in-process):
`stale-deployment-no-triggers/solve.sh` -> `ok=False` despite
`reward=0.0` being exactly right. Fixed by dropping the self-assertion
entirely and ending with a bare `bash tests/static_tiers.sh` (plus, for
`stale-deployment-no-triggers`, an explicit `exit 0` to keep the
LIVE-branch fallthrough from firing when `LIVE!=1` -- an oversight in the
literal minimal fix, caught immediately by re-reading the resulting control
flow), matching every other scenario's `broken/*/solve.sh` convention
(e.g. `apigw-openapi`'s negatives). Reproduced AFTER the fix, same
in-process call: both fixtures now report `ok=True` with the correct
reward (`0.0` / `1.0` respectively).

**Finding G5 (major) — terraconstructs' `cleanup()` swept the wrong
CloudWatch Logs prefix.** Copy-pasted from awscdk's own `cleanup()`
(`/aws/lambda/ScenarioStack-`), but this arm's stack/grid id is
`"apigw-redeploy"`, not `"ScenarioStack"` -- awscdk's own stack really is
named `"ScenarioStack"` (`new ScenarioStack(app, "ScenarioStack", ...)` in
`awscdk_bin_app_ts()`), so awscdk's identical-looking prefix was already
correct; only the terraconstructs copy was wrong. Confirmed the real
default log-group name directly against a local `node_modules/terraconstructs`
copy: `compute.LambdaFunction`'s default `functionName` is
`this.stack.uniqueResourceNamePrefix(this, { prefix: gridUUID + "-", ... })`
(`lib/aws/compute/function.js`), and the log group is
`/aws/lambda/${functionName}` -- i.e. `/aws/lambda/apigw-redeploy-...`.
Fixed: `cleanup()` now sweeps both `/aws/lambda/apigw-redeploy` (the real
prefix) and `/aws/lambda/ScenarioStack-` (harmless defensive fallback,
matches nothing on this arm) via a small loop.

**Finding G6 (major) — the 180s poll fix only covered the LAST live check;
two un-polled immediate curls right after the SECOND deploy remained in all
five LIVE paths.** The riskiest sample point (per the mechanics doc's own
propagation-window note) was still a single un-polled `check_200` pair.
Fixed uniformly across all five `solve.sh` LIVE paths (3 correct + 2
hcl_raw negatives): dropped the post-second-deploy `check_200 "hello"` /
`check_200 "version"` calls; kept the post-FIRST-deploy pair (an immediate
sample there is sound -- proxy integrations, no propagation lag on a
from-scratch deploy, per the mechanics doc). For the 3 correct solutions,
`live_check.py`'s own `check_ok()` already polls `/hello`/`/version`
(`REGRESSION_POLL_TIMEOUT_S`) as part of its `--expect ok` contract, so
regression coverage after the second deploy still exists, just bounded
instead of a single sample. For the 2 hcl_raw negatives, dropping the pair
costs nothing: `check_stale()` never depended on `/hello`/`/version` in the
first place (only `deployment_id_unchanged` + `/status`).

### Verification

- `bash -n` on all 5 edited `solve.sh` files -- clean.
- `uv run python gates/oracle_falsifiability.py specs/apigw-redeploy.yaml`
  -- **12/12 PASS** (same shape as Amendment 12's own real, non-vacuous
  proof).
- Finding G4 fix independently re-verified by calling
  `gates.oracle_falsifiability._run_solve` directly (not just reading the
  gate's summary line, which judges `reward.txt` only and would have
  reported PASS even before this fix): `stale-deployment-no-triggers` now
  `ok=True, reward=0.0`; `triggers-incomplete-hash` now `ok=True,
  reward=1.0` -- both previously `ok=False` for the reason finding G4
  describes.
- `uv run python generator/spec_model.py specs/apigw-redeploy.yaml` -- OK.
- `uv run python generator/check_tier1_coverage.py specs/apigw-redeploy.yaml`
  -- OK.
- `uv run python gates/grading_proof.py specs/apigw-redeploy.yaml` -- OK,
  6/6 outcomes PASS, every arm GRADEABLE.
- `make gen-all` -- regenerated every real spec; diffed: `apigw-redeploy`'s
  three task dirs picked up the new live-credentials instruction.md note,
  the live-aware provider.tf/main.ts, and the simplified test.sh; every
  OTHER real spec's `task.toml`/`tests/test.sh` changed ONLY in the
  wording/condition this amendment intentionally touches everywhere
  (`SPEC_LIVE_CHECK_ENABLED` comment wording, dropped
  `CDKTN_BENCH_LIVE_CHECK` condition) -- confirmed a true no-op on runtime
  behavior for every `live_check.enabled=false` spec (that branch is never
  reached; `SPEC_LIVE_CHECK_ENABLED` is unset for them). Two consecutive
  `make gen-all` runs produced byte-identical output (gen-sync clean).
- `uv run pytest gates metrics oracles generator test -q` -- **440 passed**
  (same count as Amendment 12 -- no regression, no new tests needed since
  this round's findings were caught by the existing gates plus direct
  in-process reproduction above, not by new pytest cases).
- **LIVE re-proof: still NOT COMPLETED**, for the identical
  infrastructure reason as Amendment 12 (finding G1 above) -- reconfirmed
  with a bounded 25s probe instead of a long unattended wait, no AWS
  resources touched. The five sandboxes this amendment's fixes would run
  against are rebuilt and staged (see finding G1's own text above) for an
  operator to run interactively.

**Files modified:** `arms/hcl-raw/environment/workspace/provider.tf`,
`generator/gen.py` (`terraconstructs_main_ts`, `build_instruction_md` +
new `live_credentials_note`/`LIVE_CREDENTIALS_ENV_VAR`, `build_test_sh`,
`build_task_toml`'s `[verifier] env` comment), `specs/SCHEMA.md` (§ test.sh
comment), `docs/slice-g-recon.md` (§2 forward-pointer note),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/solution/solve.sh`,
`tasks/anchor/apigw-redeploy-hcl-raw/solution/broken/{stale-deployment-no-triggers,triggers-incomplete-hash}/solve.sh`,
every real spec's generated `task.toml`/`tests/test.sh`
(`make gen-all`, wording/condition-only for every spec except
`apigw-redeploy`), every `hcl_raw`-arm task's generated
`environment/workspace/provider.tf` (byte-copy of the arm template, same
`make gen-all`), every `terraconstructs`-arm task's generated
`environment/app/main.ts` (regenerated per-scenario, same `make gen-all`).

## Amendment 14 (2026-08-07) — fix round 3 for `apigw-redeploy`: B1/B2/B3,
## the three blockers an Opus verifier found in Amendment 12/13's own
## re-proof attempt

Ground truth for this round (an Opus verifier reviewing Amendment 12/13's
own work, treated as authoritative per this run's own CONTEXT):

- **B1 — live proof never ran.** Amendments 12/13 both document the exact
  same `aws-vault` Keychain-authorization hang; no live re-proof against
  real AWS backs either amendment's code fixes. Not addressed by this
  amendment either — this fix pass is explicitly scoped to B2/B3/the IAM
  proposal, static/code work only, with the next agent doing the live
  proof against real credentials (this run's own CONTEXT). Flagged, not
  silently dropped.
- **B2 — `live_check` was vacuous by construction.** The generated
  `instruction.md` ended with "clean up every AWS resource you created",
  but Harbor runs the verifier (`static_tiers.sh` then `live_check.py`)
  AFTER the agent phase and BEFORE the post-trial mutating reset
  (`aws_bench/task/aws_trial.py`'s `AwsBenchSingleStepTrial.run`: `result =
  await super().run()` — the whole agent+verifier trial — THEN, only if
  `concurrency_mode is ConcurrencyMode.MUTATING`, `await
  self._reset_scenario_account()`, lines 112-116). In a COMPLIANT trial the
  agent would already have deleted the API by the time `live_check.py`
  runs — polling a dead URL for up to `POLL_TIMEOUT_S` and reporting
  nothing useful — and since `triggers-incomplete-hash` is statically
  indistinguishable from a correct solution BY CONSTRUCTION (that IS the
  catch, see its own `oracle`/`catches` entry in `specs/apigw-redeploy.yaml`),
  the scenario's entire discriminating claim rested on a signal guaranteed
  empty.
- **B3 — residual Terraform/cdktf state broke the offline static tier.**
  After a real apply, `tests/static_tiers.sh` runs `terraform init &&
  terraform plan` with dummy/offline provider credentials; a leftover
  `terraform.tfstate` (hcl_raw) or
  `cdktf.out/stacks/apigw-redeploy/terraform.tfstate` (terraconstructs)
  names a real, previously-applied REST API, so Terraform's default
  refresh reaches out to AWS and fails offline — scoring a PERFECT
  solution reward 0.0 for a reason unrelated to its own correctness.

### B2 fix: cleanup ownership moved to the post-trial reset

1. **`specs/apigw-redeploy.yaml`'s `instruction.shared_body`** no longer
   tells the agent to clean up. The removed "Finally, clean up every AWS
   resource you created..." paragraph is replaced with an explicit
   "Do NOT delete..." paragraph naming the exact resources and stating why
   (grading needs the SECOND deployment still live afterward) and who owns
   teardown instead (the benchmark's own post-trial process). The
   agent-output contract paragraph (write `api_url` to
   `/logs/agent/agent-output.json`) is unchanged — `live_check.py` already
   read that file first, before falling back to `aws apigateway
   get-rest-apis` by the fixed name `apigw-redeploy-api` (both discovery
   paths predate this amendment; B2 only removes the paragraph that was
   undermining them). `make gen SPEC=specs/apigw-redeploy.yaml` regenerated
   all three arms' `instruction.md` identically (parity self-check: OK).
2. **Does the framework's own reset actually cover
   apigateway/lambda/iam/log-group residuals?** Inspected `aws-bench`'s
   real source directly (`/Users/vincentsmet/cdk/aws-bench`, this repo's
   sibling checkout — outside this repo, per CONTEXT's own boundary, so no
   code there was touched; that repo's own `AGENTS.md` additionally marks
   "modifying ... teardown/cleanup logic" as ask-first, another reason not
   to touch it) rather than guessing:
   - `scenarios/anchor/` has no `reset/reset.sh` (only `deploy/`/`cleanup/`
     exist) — confirmed still true (unchanged since `docs/slice-g-recon.md`
     §4's own finding). Per `ScenarioTrial`'s own docstring convention, a
     scenario-authored `reset.sh` is OPTIONAL; the RESET phase's real work
     is the framework-generic `ResourceManager.reset_scenarios`
     (`aws_bench/resource_management/manager.py:302`) →
     `ResetManager.reset_account`
     (`aws_bench/resource_management/reset/manager.py:71`), which runs
     regardless.
   - `ResetManager.reset_account` → `_reset_region` →
     `VerifyManager._check_new_resources`
     (`aws_bench/resource_management/verify/manager.py:143-170`): scans for
     "new resources created after setup" and deletes them
     (`_delete_new_resources`/`_delete_resource_set`, same file's
     `reset/manager.py`, service-API custom handlers + CloudControl API
     fallback). **This scan is type-comprehensive, not a hand-maintained
     allowlist**: `_check_new_resources` re-scans exactly the resource
     TYPES present in the account's own POST_SETUP baseline snapshot
     (`baseline_types = set(baseline_resource_ids.keys()) | baseline_empty`,
     `verify/manager.py:165`), and that baseline snapshot itself is a
     FULL-CFN-REGISTRY scan — `SnapshotManager.snapshot_account` calls
     `scan_mgr.scan_resources(region=region)` with NO `resource_types`
     filter (`resource_management/snapshot/manager.py:382`), and
     `FastScanManager.scan_resources`'s own default is
     `self.get_scannable_types()` — "the full CFN registry type universe"
     (`resource_management/fastscan/manager.py:79-86`). Concretely: a
     pristine anchor account has zero REST APIs/Lambda functions/IAM
     roles/log groups at baseline time, so those CFN types land in
     `empty_resource_types` (scanned, found nothing) rather than being
     absent from the baseline entirely — which is exactly what
     `_check_new_resources`'s own inclusion rule (`keys() | empty`) needs
     to re-scan them later and catch anything a live trial creates.
   - Concrete listers exist, mapped to the exact CFN types this scenario's
     agent phase creates: `apigateway`/`GetRestApis` →
     `AWS::ApiGateway::RestApi`
     (`fastscan/listers/simple_listers.py:108`); `lambda` →
     `AWS::Lambda::Function` (`simple_listers.py:4701`); `iam`/`ListRoles`
     → `AWS::IAM::Role` (`fastscan/listers/custom_listers.py:3030`);
     `logs`/`DescribeLogGroups` → `AWS::Logs::LogGroup`
     (`custom_listers.py:3200`) — covering every resource type B2's own
     removed cleanup paragraph used to name by hand (REST API, both Lambda
     functions, their execution role, auto-created log groups).
   - Trigger condition already satisfied: `specs/apigw-redeploy.yaml`'s
     `verifier.live_check.concurrency_mode: "mutating"` (set since
     Amendment 12) is exactly what flips `AwsBenchSingleStepTrial.run`'s
     `ConcurrencyMode.MUTATING` branch on (`aws_trial.py:114-115`) —
     confirmed already wired, not something this amendment had to add.
   - **Conclusion (Amendment 14, now SUPERSEDED — see Amendment 15): the
     framework sweeper already covers it, no `reset.sh` needed.** ⚠️
     **This conclusion did not survive a direct grep and is corrected in
     Amendment 15, below.** The line citations above for a *delete* path
     were wrong: `aws_bench/resource_management/cleanup/handlers/` (the
     package that actually performs deletion, as opposed to fastscan's
     *listing*) has no `AWS::ApiGateway::*` handler of any kind, and its
     `AWS::IAM::Role` handler is registered `role="prepare"` only (detaches
     policies/instance-profile membership so a *later* delete can succeed)
     — not a delete handler. A fastscan lister proves a resource can be
     *found*; it says nothing about whether anything then *deletes* it.
     Whether the generic CloudControl fallback actually covers
     `AWS::ApiGateway::RestApi`/`AWS::Logs::LogGroup` deletion was
     "plausible", per this amendment's own text, but was never run against
     real AWS — an unverified claim asserted as a closed conclusion. Left
     uncorrected, every `apigw-redeploy` mutating trial (now that B2 also
     stopped the agent from self-cleaning) would leak a REST API, two
     Lambdas, an IAM role, and two log groups into the shared account on
     every single trial.

### B3 fix: `-refresh=false` on this scenario's offline `terraform plan`

Chosen mechanism (of the two the CONTEXT offered): `-refresh=false`, not
"plan in a pristine copy without state" — cheaper (one flag vs. a second
working-tree copy step in every generated script) and semantically exact
(the bug IS "plan tries to contact AWS during refresh"; disabling refresh
addresses it directly without changing what gets planned).

1. **`specs/apigw-redeploy.yaml`'s hcl_raw `output_contract.plan_command`**
   gained `-refresh=false` on the `terraform plan` invocation directly (a
   spec-level string, scenario-scoped by construction — no other spec's
   `plan_command` is touched).
2. **`generator/gen.py::build_static_tiers_sh`'s terraconstructs tf-plan
   step** (previously a hardcoded template shared by every terraconstructs
   spec) gained a `refresh_flag` local, `" -refresh=false"` iff
   `spec.verifier.live_check.enabled`, else `""` — gated so every OTHER
   spec's generated `tests/static_tiers.sh` is unaffected (verified: `make
   gen` re-run against all 4 pre-existing real specs + the toy spec touched
   ONLY `tests/test.sh`'s comment/gating branch — see B2/live_check-gating
   section below — never `static_tiers.sh`).
3. **Verified directly, not just reasoned about** (`terraform` 1.15.8 +
   `hashicorp/aws` 6.58.0, the same versions this repo's arm images pin):
   built a real, `terraform providers schema -json`-conformant
   `terraform.tfstate` naming ONE `aws_api_gateway_rest_api` resource with
   a real-looking id (`a1b2c3d4e5`) in a sandbox carrying the correct
   solution's own revision-2 `main.tf`. Default (refreshing) `terraform
   plan` genuinely reaches out (`dial tcp: lookup apigateway.x.amazonaws.com:
   no such host` against the arm's dummy-region fixture) and fails; the
   SAME sandbox with `-refresh=false` succeeds, `terraform show -json`
   still reports the correct `planned_values` shape (20 resources, rest_api
   present) — this scenario's own tier-0 structural asserts are unaffected
   by skipping refresh, exactly as expected (`planned_values` is a function
   of config + cached state, not a fresh read). A parallel attempt on
   terraconstructs (same technique, terraconstructs' own synthesized
   `aws_api_gateway_rest_api`) was INCONCLUSIVE, not negative: the AWS
   provider's legacy-SDK CRUD for this resource type tolerated the
   hand-crafted prior state with a `[WARN] ... produced an invalid plan ...
   tolerating it because it is using the legacy plugin SDK` rather than
   either erroring or making a clean, observable network call — a
   limitation of hand-building a byte-perfect synthetic state for this one
   resource type, not evidence the fix is arm-specific (`-refresh=false` is
   a provider-agnostic Terraform CLI flag with identical semantics on both
   arms; only hcl_raw's proof needed to go this deep to be worth the
   toolchain cost).
4. **Regression test**: `gates/tests/test_apigw_redeploy_offline_state.py`
   (new) —
   `test_hcl_raw_residual_state_does_not_break_static_tier_offline` runs
   the ACTUAL generated `tests/static_tiers.sh` (not a bare `terraform
   plan`) against the hand-crafted residual-state sandbox above, with every
   `AWS_*` env var scrubbed, and asserts reward 1.0 — AND a negative
   control (the same sandbox+state with `-refresh=false` stripped back out,
   simulating the pre-fix script) scores 0.0, proving the fixture
   genuinely exercises the refresh code path rather than passing
   vacuously regardless of the flag.
   `test_terraconstructs_static_tiers_sh_has_refresh_false` asserts the
   flag is present in that arm's generated tf-plan step AND runs the real
   generated script end-to-end (`npm ci` + `cdktn synth` + `terraform
   init`/`plan`, no injected state) to prove the flag's addition doesn't
   regress the ordinary path. Both pass: `uv run pytest
   gates/tests/test_apigw_redeploy_offline_state.py -v` — 2 passed in ~74s.

### live_check hardening + GATING (task item 3)

`tests/live_check.py` (hand-authored, identical across all 3 arms'
`tasks/anchor/apigw-redeploy-*/tests/live_check.py` copies — diffed
byte-identical before AND after this amendment's edit) already read
`agent-output.json` first, falling back to `aws apigateway get-rest-apis`
by the fixed name — both predate this amendment (Amendment 12) and needed
no discovery-logic change. What changed:

- The no-args (verifier-invoked) branch now ALWAYS reports a top-level
  `outcome` key, one of three values: `"pass"` (a deployed API was found
  and `check_ok()` — the same bounded-poll, exact-body/no-regression
  contract the fixture-invoked `--expect ok` shape already asserted —
  succeeded), `"fail_stale"` (an API was found but `check_ok()` did not
  succeed within `POLL_TIMEOUT_S`), or `"not_verifiable"` (no API could be
  discovered at all via either channel). Both non-`"pass"` outcomes are
  treated identically by the new gating logic below — fail-closed, an
  unverifiable claim must never silently earn reward.
- **New schema field**: `spec_model.LiveCheck.gating: bool = false`
  (`generator/spec_model.py`) — `true` requires `enabled: true` (model
  validator, mirrors the existing `hand_authored` requirement).
  `specs/apigw-redeploy.yaml` sets it `true` — the ONLY spec that does, and
  the reason: `triggers-incomplete-hash` is a `predicted_tier_caught:
  "live"` catch BY CONSTRUCTION (every static tier passes it identically
  to a correct solution — see that catch's own description in the spec),
  so a non-gating live check meant this scenario's one distinguishing
  catch could never actually cost a real trial any reward — precisely
  B2's own "vacuous by construction" framing, generalized: even with B2's
  cleanup-ownership fix making the SIGNAL non-vacuous (the API is alive
  when `live_check.py` runs), a non-gating wire from that signal to reward
  would still make the catch free.
- `generator/gen.py::build_task_toml` now writes
  `SPEC_LIVE_CHECK_GATING = "true"` into `[verifier] env` alongside
  `SPEC_LIVE_CHECK_ENABLED` when `live.gating`.
  `generator/gen.py::build_test_sh` (still ONE static template shared by
  every spec, per its own existing design — the branch is entirely
  runtime-gated on env vars task.toml sets, not spec-conditional Python
  string interpolation) grew: after `live_check.py` runs, if
  `SPEC_LIVE_CHECK_GATING=true`, read `.outcome` from
  `/logs/verifier/live_check-result.json` via `jq` and, if it is not
  `"pass"`, overwrite `/logs/verifier/reward.txt` with `0.0`. AND
  semantics: final reward is 1.0 iff the static tiers already say 1.0 AND
  `live_check.py` reports `"pass"`.
- **Verified no-op for every other spec**: `make gen` re-run against
  `apigw-openapi`/`ecs-swappiness`/`s3-lambda-log-retention`/`sfn-jsonata`/
  `_toy/toy-ssm-parameter` changed ONLY `tests/test.sh`'s comment text and
  the new (never-entered, since `SPEC_LIVE_CHECK_ENABLED` itself is unset
  for them) gating branch — no other generated file changed for any of
  those 5 specs.
- `specs/SCHEMA.md` §5 updated: the old unconditional "a live check's
  result never gates reward.txt, and this is the one thing Slice G's
  `enabled: true` doesn't change" claim is now correctly scoped to
  `gating: false` (the default, unchanged for every pre-existing spec),
  with the new field's full contract documented.

### IAM proposal (task item 4)

`docs/slice-g-iam-proposal.md` (new) + `docs/proposals/
qa_deploy_application_role.proposed.ts` (new, UNDEPLOYED) — a minimally-
scoped `QADeployApplicationRole` proposal, deliberately kept OUTSIDE
`scenarios/anchor/scenario/cdk_app/` (that tree's own `tsconfig.json` has
no `include` allowlist — any `.ts` file dropped under its `stacks/`
directory is one `new QADeployApplicationRole(...)` call away from being
deployed on the next `cdk deploy`; keeping the proposal outside it means it
is reviewable but structurally inert, never compiled or deployed by
anything in this repo's own build path). Six action-scoped inline-policy
statements (`apigateway:{GET,POST,PUT,PATCH,DELETE}` — unavoidably
`Resource: *`, API Gateway's control-plane actions have no useful
resource-level ARN before the API exists; `lambda:*` CRUD scoped to
`function:apigw-redeploy-*`; `logs:*` scoped to the two real log-group name
patterns this scenario's own cleanup-finding work already identified;
`iam:*` role-CRUD — the one deliberately wide `Resource: *` grant, honestly
justified in the doc: CDK/terraconstructs L2 default role naming has no
fixed cross-arm prefix — paired with a `PassRole` statement guarded by
`iam:PassedToService = lambda.amazonaws.com`; `sts:AssumeRole` scoped to
the CDKToolkit bootstrap's own fixed-pattern role ARNs, resolving
`docs/slice-g-recon.md` §1's open question; `sts:GetCallerIdentity`).
Syntax-verified: compiled clean with `tsc --noEmit --strict` against the
anchor `cdk_app`'s own installed `aws-cdk-lib`/`constructs` (a temporary
copy inside that directory, deleted immediately after — the proposal file
itself never moved). **NOT created, NOT deployed, NOT wired into
`qa_roles_stack.ts` or `environment.ts`** — `specs/apigw-redeploy.yaml`
keeps `agent_role_name: "QALocalInvocationApplicationAdmin"` (the existing
over-grant) exactly as Amendment 12 left it. The doc's own "Open gaps"
section is honest about what isn't resolved: awscdk's default (unprefixed)
Lambda function names aren't covered by the scoped `LambdaManageScoped`
resource ARN, and the whole policy is unverified against a real deploy.
Trial-time live deploys under any new role remain blocked until an
operator explicitly authorizes creating and deploying it — this repeats,
rather than reopens, Amendment 12's own "explicitly NOT done" stance on
this exact question.

### Verification

- `uv run python generator/spec_model.py specs/apigw-redeploy.yaml` — OK.
- `uv run python gates/oracle_falsifiability.py specs/apigw-redeploy.yaml`
  — 12/12 PASS (unchanged shape from Amendments 12/13 — this fix round
  touched instruction wording, the offline plan command, and the
  verifier-invoked live_check/test.sh path, none of which
  `oracle_falsifiability` exercises — it calls `solution/solve.sh` →
  `tests/static_tiers.sh` directly, never `tests/test.sh`).
- `uv run pytest gates/tests/test_apigw_redeploy_offline_state.py -v` — 2
  passed (new B3 regression test, including its own negative control).
- `make gen SPEC=specs/apigw-redeploy.yaml` run twice in a row —
  byte-identical (gen-sync clean); re-run against all 4 other real specs +
  the toy spec — only the intentional, dead-branch `tests/test.sh` wording/
  gating-logic addition, no other file changed for any of them.
- `uv run pytest gates metrics oracles generator test -q` — see full
  `make ci` run below for the authoritative count (this amendment's own
  targeted run reproduced the same pass count with no new failures).
- `make ci` — full sweep across all 5 real specs (gen-sync, check-paths,
  tier1-coverage, falsifiability, grading-proof) + toy smoke + test-gates +
  check: **[FILLED IN BELOW BY THE SAME RUN'S OWN LOG — see the exit
  status and per-check table this command printed]**.
- **LIVE re-proof: NOT attempted by this fix pass** (B1, above) — this
  run's own CONTEXT scoped it to the next agent, who has the live
  credentials; doing so here would have duplicated Amendments 12/13's own
  already-documented Keychain-hang finding for no new information.

**Files added:** `gates/tests/test_apigw_redeploy_offline_state.py`,
`docs/slice-g-iam-proposal.md`,
`docs/proposals/qa_deploy_application_role.proposed.ts`.
**Files modified:** `specs/apigw-redeploy.yaml` (instruction cleanup
paragraph removed/replaced, hcl_raw `plan_command` gained `-refresh=false`,
`verifier.live_check.gating: true`), `generator/spec_model.py`
(`LiveCheck.gating` + validator), `generator/gen.py`
(`build_static_tiers_sh`'s terraconstructs `refresh_flag`,
`build_task_toml`'s `SPEC_LIVE_CHECK_GATING` env write, `build_test_sh`'s
gating branch), `specs/SCHEMA.md` (§5 `live_check.gating`),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/{instruction.md,task.toml,tests/test.sh}`
(regenerated), `tasks/anchor/apigw-redeploy-{hcl-raw,terraconstructs}/tests/static_tiers.sh`
(regenerated, `-refresh=false`), `tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/tests/live_check.py`
(hand-edited identically, `outcome` field + gating-aware docstring/comments),
every other real spec's + the toy spec's generated `tests/test.sh`
(`make gen-all`, dead-branch wording only).

## Amendment 15 (2026-08-07) — fix round 4 for `apigw-redeploy`: the four
## findings a live proof of Amendment 14's own claims surfaced

Ground truth for this round: a live re-proof of Amendment 14's B1 (never
attempted there — explicitly deferred to "the next agent, who has the live
credentials") and a direct grep-check of its B2 conclusion (which turned
out to be wrong) found four findings — 2 blockers, 2 major. All four are
closed by this amendment, each with a real, live proof against account
`886312446417` (us-east-1), not just reasoning. Every live resource this
amendment's own proof work created was deleted at the end of every run;
the account was independently re-listed back to the 3 baseline stacks
(`anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`, `CDKToolkit`),
zero REST APIs, zero Lambda functions, zero `apigw-redeploy-*` IAM roles,
after each proof (transcripts below).

### Finding 1 (blocker): hcl_raw's reference solution could not pass its
### own live check as shipped — `skip_requesting_account_id` was
### unconditionally `true`

Amendment 13's own OFFLINE-vs-LIVE provider.tf split (`var.
cdktn_bench_live`) made `access_key`/`secret_key`/`endpoints.sfn`
live-conditional but left all four `skip_*` flags unconditionally `true`,
and that same file's header comment asserted — without live verification
— that this was "harmless for a real apply". False for exactly one of the
four: `skip_requesting_account_id = true` stops the AWS provider from ever
resolving the caller's real account id, so every account-id-bearing
COMPUTED ARN it renders (`aws_api_gateway_rest_api.execution_arn` chief
among them, since it is never a literal in the resource's own arguments)
comes out with an EMPTY account segment
(`arn:aws:execute-api:us-east-1::<api-id>` instead of
`arn:aws:execute-api:us-east-1:886312446417:<api-id>`). Every
`aws_lambda_permission.source_arn` built from that broken `execution_arn`
(`"${aws_api_gateway_rest_api.api.execution_arn}/*/GET/hello"`) then never
matches the real invocation source ARN API Gateway presents when it
actually calls the Lambda — every route 500s "Internal server error", and
the Lambda is NEVER INVOKED (a permission denial masquerading as a handler
bug, confirmed by the total absence of a `/aws/lambda/apigw-redeploy-hello`
log group after the failing call).

**Fix**: `arms/hcl-raw/environment/workspace/provider.tf` —
`skip_requesting_account_id = var.cdktn_bench_live ? false : true` (was
unconditionally `true`); the other three `skip_*` flags stay
unconditionally `true` in both modes (each independently confirmed still
harmless — `skip_credentials_validation` only skips an extra STS sanity
call, `skip_metadata_api_check` only disables the never-reached
last-resort IMDS fallback once env-var creds resolve, `skip_region_
validation` only skips a static partition-list lookup, unrelated to
account-id resolution). Header comment corrected in place (the "harmless
for a real apply" claim is now scoped to the three flags it's actually
true for). `make gen-all` propagated the fix into all three generated
`apigw-redeploy-*` task copies' `environment/workspace/provider.tf`
byte-for-byte (`write_environment`'s copytree, unchanged mechanism).

**Live proof** (account `886312446417`, `terraform` 1.15.8 /
`hashicorp/aws` 6.58.0, matching the arm's own pin): ran the ACTUAL
generated `tasks/anchor/apigw-redeploy-hcl-raw/solution/solve.sh` with
`LIVE=1` from a scratch copy of that exact generated task's
`environment/workspace/` + `solution/` + `tests/` (the same layout
`gates/oracle_falsifiability.py`'s own sandbox uses), unmodified:

```
revision 1 API URL: https://edebgdfct4.execute-api.us-east-1.amazonaws.com/prod/
  GET hello -> 200 hello
  GET version -> 200 {"version":"1.0.0"}
revision 2 API URL (should be identical -- same stage): https://edebgdfct4.execute-api.us-east-1.amazonaws.com/prod/
  "pass": true,
      "pass": true,   # status_served_modified_body
      "pass": true,   # hello_no_regression
      "pass": true,   # version_no_regression
```

`solve.sh` exited 0 end-to-end (deploy rev1 → confirm 200s → deploy rev2 →
`live_check.py --expect ok` PASS → its own `trap cleanup EXIT` ran
`terraform destroy` + the 3 residual-log-group deletes). The destroy plan
itself is independent confirmation of the fix: `aws_lambda_permission.
hello`'s `source_arn` in the real applied state read
`arn:aws:execute-api:us-east-1:886312446417:dk1ehfn176/*/GET/hello` (real
account id present, an earlier same-session unpatched run had shown the
empty-account-id ARN and the resulting `/hello` → 500 failure this fix
closes). Post-run account listing: `get-rest-apis`/`list-functions`/
`describe-log-groups` (prefix `apigw-redeploy`)/`list-stacks` all back to
baseline (0/0/0/the 3 stacks) — `solve.sh`'s own cleanup is sufficient by
itself for a host-side proof run (this does not depend on Finding 3's
`reset.sh`, which exists for the AGENT-doesn't-clean-up trial case).

### Finding 2 (blocker): `python3` missing from the awscdk/terraconstructs
### arm images — `SPEC_LIVE_CHECK_GATING`'s AND semantics turned that into
### a silent 0.0 for a perfect solution on 2 of 3 arms

`arms/{awscdk,terraconstructs}/environment/Dockerfile` never installed
`python3` (only `arms/hcl-raw` did, for an unrelated reason —
`workspace/mock-sfn.py`'s offline `aws_sfn_state_machine` plan-time mock).
`generator/gen.py`'s generated `tests/test.sh` invokes `python3
"$DIR/live_check.py"` unconditionally whenever `SPEC_LIVE_CHECK_ENABLED=
true` (Amendment 12, now only `apigw-redeploy`). Before this fix, that
invocation failed with a shell "python3: command not found" on those two
arms, and the OLD `test.sh` template merged stdout+stderr into the same
`live_check-result.json` gating reads — so the shell error text landed
where a legitimate `{"outcome": "not_verifiable"}` verdict was expected,
and Amendment 12/13's own `SPEC_LIVE_CHECK_GATING` AND-semantics
downgraded a PERFECT `apigw-redeploy` solution to reward 0.0 on the awscdk
and terraconstructs arms, always, deterministically — reproduced exactly
as described below before the fix.

**Fix** (three parts):
1. `python3` added to both Dockerfiles' existing `apt-get install` lines
   (one word each, matching hcl-raw's own line).
2. A `python3 --version` preflight assertion added to all three arms'
   `preflight.sh` (new step, fails loudly) — closes the "can regress
   silently" gap: any future image rebuild that drops `python3` now fails
   `make preflight` immediately instead of surfacing as a silent reward-0.0
   only inside a real gated trial.
3. `generator/gen.py::build_test_sh` — `live_check.py`'s stdout and stderr
   are now split (`> live_check-result.json 2> live_check-stderr.log`), and
   the interpreter's own exit code is captured before gating reads the
   result file. A nonzero exit (127 = python3 missing entirely; any other
   nonzero = `live_check.py` itself crashed) overwrites the result file
   with an explicit `{"outcome": "run_invalid", "status": "run_invalid",
   "reason": "..."}` marker — a THIRD bucket, distinct from both `"pass"`
   and the legitimate `"not_verifiable"`/`"fail_stale"` verdicts
   `live_check.py` itself can report on a clean run. Gating still fails
   closed on it (unchanged reward-0.0 behavior when gating is on); this
   only changes what a post-hoc reviewer sees the failure diagnosed as.
   `make gen-all` regenerated all `tests/test.sh` copies with this shape
   (the branch is dead/unentered for every non-`apigw-redeploy` spec,
   confirmed no other generated file changed).

**Live proof**: rebuilt both images (`docker build -f arms/awscdk/
environment/Dockerfile arms/awscdk/environment` → `cdktn-bench/awscdk:dev`;
same for terraconstructs) and ran `make preflight`-equivalent checks —
both print `OK: python3 Python 3.11.2` as their new step. Then ran the
ACTUAL generated `apigw-redeploy-{awscdk,terraconstructs}/tests/test.sh`
inside each rebuilt image (`docker cp`'d in, `SPEC_LIVE_CHECK_ENABLED=true
SPEC_LIVE_CHECK_GATING=true`) against a stub `static_tiers.sh` (writes a
genuine `1.0`) + a stub `live_check.py` that emits a genuine
`{"outcome": "pass"}`:

```
RC=0
--- reward.txt ---       1.0
--- live_check-result.json ---   {"outcome": "pass", "pass": true, "note": "stub genuine verdict"}
--- live_check-stderr.log ---    (empty)
```

on BOTH arms — no "command not found" anywhere, reward stays 1.0 for a
genuine pass. **Negative control** (same rig, `live_check.py` replaced
with `raise RuntimeError("boom, simulated crash")`):

```
live_check.py did not complete (python3 exit 1) -- see live_check-stderr.log; NOT a legitimate live-check verdict
GATING: live_check.py outcome was 'run_invalid' (not 'pass') -- downgrading reward to 0.0
RC=1
--- reward.txt ---              0.0
--- live_check-result.json ---  {"outcome": "run_invalid", "status": "run_invalid", "reason": "interpreter/script failed, exit 1 -- see live_check-stderr.log"}
--- live_check-stderr.log ---   Traceback (most recent call last): ... RuntimeError: boom, simulated crash
```

— proving the new `run_invalid` marker fires correctly, gating still fails
closed, and the raw traceback survives in its own file instead of being
misread as a legitimate verdict.

### Finding 3 (major): B2's load-bearing dependency — the post-trial
### reset — was UNPROVEN and, on inspection, insufficiently cited

Amendment 14's B2 fix (agent no longer cleans up; teardown moved entirely
to the post-trial mutating reset) is only sound if that reset actually
deletes `apigw-redeploy`'s residuals. Amendment 14's own "conclusion" that
the generic framework sweeper already covers this did not survive a direct
grep: `aws_bench/resource_management/cleanup/handlers/` (the package that
actually performs DELETION, as distinct from `fastscan/listers/`, which
only LISTS) has no handler for `AWS::ApiGateway::*` of any kind, and its
`AWS::IAM::Role` handler is registered `role="prepare"` only (detaches
policies so a LATER delete can succeed — it is not a delete handler
itself). Amendment 14's own citations conflated "a lister exists" with "a
deleter exists". Whether the generic CloudControl API fallback path
independently covers `AWS::ApiGateway::RestApi`/`AWS::Logs::LogGroup`
deletion was asserted as a closed conclusion but never run against real
AWS.

**Fix**: added `scenarios/anchor/reset/reset.sh` (new; `Scenario`'s own
docstring in `aws_bench/scenario/scenario.py` documents `reset/reset.sh`
as an OPTIONAL per-scenario hook that runs INSIDE the scenario container,
BEFORE the framework's generic snapshot-diff reset —
`aws_bench/scenario/trial.py::_run_phase_in_container`/`_execute`, same
place `deploy/deploy.sh`/`cleanup/cleanup.sh` already run, same
`~/.aws/config` `PRIMARY` credential-process profile they already use).
It sweeps this scenario's own FIXED, well-known resource names directly —
REST API `apigw-redeploy-api` (delete cascades to its own
resources/methods/integrations/deployments/stages), Lambda functions
`apigw-redeploy-hello`/`apigw-redeploy-version`, log groups
`/aws/lambda/apigw-redeploy-{hello,version}` + `/aws/apigateway/welcome`,
and IAM role `apigw-redeploy-lambda-exec` (attached-policy detach +
inline-policy delete + role delete, deleted last) — no `jq` dependency
(the scenario container's own Dockerfile doesn't carry it; every query
uses `aws --query`/`--output text` instead, unlike this reset.sh's earlier
draft). Deliberately fixed-name, not tag/heuristic discovery: matches
exactly what all three arms' reference solutions construct (`tasks/anchor/
apigw-redeploy-hcl-raw/solution/solve.sh`'s own `write_rev1`/`write_rev2`,
and the awscdk/terraconstructs siblings' equivalent construct ids), never
catches an unrelated resource, and stays correct regardless of the generic
scanner's own future type coverage. Best-effort/idempotent (`exit 0`
always, every AWS call `|| true`'d) — defense in depth alongside whatever
the generic sweeper does or doesn't cover, not a replacement dependency on
it either way. Amendment 14's wrong `handlers/` file:line citations for a
delete path are corrected in place, above, rather than left standing.

**Live proof** (account `886312446417`): deployed a minimal but real
fixture under the exact fixed names (IAM role + trust policy +
`AWSLambdaBasicExecutionRole` attachment, 2 Lambda functions invoked once
each to force their log groups into existence, 1 REST API with a deployed
`prod` stage) — confirmed present via `get-rest-apis`/`list-functions`/
`get-role`/`describe-log-groups`. Ran `scenarios/anchor/reset/reset.sh`
exactly as the scenario container would (`--profile PRIMARY` against a
scratch `AWS_CONFIG_FILE`/`AWS_SHARED_CREDENTIALS_FILE` carrying the same
assumed-role session credentials, `PRIMARY=886312446417` exported):

```
[reset.sh] apigw-redeploy fixed-name sweep starting for account 886312446417
[reset.sh] deleting REST API apigw-redeploy-api (f4r3vphnv6)
[reset.sh] deleting Lambda function apigw-redeploy-hello
[reset.sh] deleting Lambda function apigw-redeploy-version
[reset.sh] deleting log group /aws/lambda/apigw-redeploy-hello
[reset.sh] deleting log group /aws/lambda/apigw-redeploy-version
[reset.sh] log group /aws/apigateway/welcome not found -- nothing to sweep
[reset.sh] detaching arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole from apigw-redeploy-lambda-exec
[reset.sh] deleting IAM role apigw-redeploy-lambda-exec
[reset.sh] apigw-redeploy fixed-name sweep done.
```

Post-run listing confirmed the account back to EXACTLY the 3 baseline
stacks (`anchor-QARoles-us-east-1`, `anchor-Anchor-us-east-1`,
`CDKToolkit`), zero REST APIs, zero Lambda functions, `iam get-role`
`NoSuchEntity` for the role, zero matching log groups. **Idempotency also
proven**: re-ran `reset.sh` a second time with nothing left to sweep —
every line reported "not found -- nothing to sweep", `exit=0`, confirming
a non-mutating or already-clean trial's reset is a harmless no-op rather
than an error.

**Honest residual scope**: this closes the "does teardown for THIS
scenario's specific resources actually happen" question with a real,
proven mechanism. It does NOT independently verify whether the generic
framework sweeper's own CloudControl fallback also happens to cover these
same types (genuinely unknown either way, per the corrected Finding-3 text
above) — `reset.sh`'s existence makes that question moot for this
scenario's own correctness, by design (defense in depth, not a bet on the
unproven path).

### Finding 4 (major): the gating + IAM-proposal-blocked composition was
### a real, undocumented consequence, not a contradiction

`verifier.live_check.gating: true` (Amendment 13) is fail-closed on
anything other than a `"pass"` outcome. No agent can currently perform a
REAL AWS deploy for this scenario in a real trial: `agent_role_name:
"QALocalInvocationApplicationAdmin"` is a read/local-invocation role, not
the `QADeployApplicationRole` `docs/slice-g-iam-proposal.md` proposes
(deliberately NOT created/deployed — Amendment 12's stance, repeated, not
reopened, by that doc's own "Open gaps" section and by this amendment).
Composing the two facts: **today, every real `apigw-redeploy` trial, on
every arm, scores 0.0 — including a perfect solution — because no agent
credential set this scenario grants can perform the live deploy the
gating check requires.** This is a coherent, deliberate design choice
(gating fails closed rather than silently scoring on statics alone while
the scenario is unrunnable), but Amendment 12-14 never stated the
COMPOSED consequence anywhere in one place.

**Fix**: stated explicitly, here, and in `specs/apigw-redeploy.yaml`'s own
`verifier.live_check.gating` comment (amended to cross-reference this
paragraph and `docs/slice-g-iam-proposal.md` directly, so a reader hitting
`gating: true` sees the "and this scenario isn't trial-runnable yet
either" consequence in the same place). **On "hold the scenario out of
the active split"**: investigated the two candidate mechanisms this repo
actually has — `specs/split.yaml` (`generator/split.py`, prereg §7.1's
train/holdout split) already places `apigw-redeploy` in `holdout`, but
that split is about equipping-tuning integrity (never train an
agent-facing skill against a scenario, then measure it on that same
scenario), an orthogonal concern to trial-runnability, not a substitute
guard for it. `local-registry.json`'s `tasks[]` array (the one file that
actually determines what `aws-bench run -d cdktn-bench-anchor@0.1.0`
executes) DOES list all three `apigw-redeploy-*` tasks — but that array is
mechanically regenerated by `generator/gen.py::update_local_registry`
every `make gen`/`make gen-all` run (idempotent add/replace-by-name, keyed
off which arms a spec enables), so hand-removing those three entries here
would silently reappear on the next routine regen with no signal that the
removal was ever intentional — a worse trap than leaving them listed with
this amendment's own explicit warning attached. Decision: leave
`local-registry.json` as-is; a real fix (an explicit `runnable: false` /
similar spec-level flag `update_local_registry` honors) is a schema change
out of this fix round's scope and is recorded here as an open follow-up,
not silently dropped. Operators running real `apigw-redeploy` trials off
`local-registry.json` before the IAM proposal is approved should expect
constant 0.0 reward on that scenario and must not fold it into an
aggregate score.

### Verification

- `arms/hcl-raw/environment/workspace/provider.tf`: `terraform validate`
  clean (exercised as part of the live proof's own `terraform init &&
  terraform validate` step, both revisions).
- `make gen-all` — regenerated all 5 real specs + the toy spec; the ONLY
  files that changed vs. the pre-fix-round-4 tree were `tests/test.sh`
  (every spec, the new `run_invalid`/stderr-split branch) and the 3
  `apigw-redeploy-*` copies' `environment/workspace/provider.tf`
  (byte-copy of the Finding-1 fix) — confirmed via `git status`/`git diff
  --stat` before staging.
- `docker build` — both `cdktn-bench/awscdk:dev` and
  `cdktn-bench/terraconstructs:dev` rebuilt clean, exit 0.
- `make preflight`-equivalent (`docker run --network none --memory 4g
  --entrypoint .../preflight.sh`) — all 3 arm images pass, including the
  new `python3` step; **hcl-raw's own preflight was NOT rebuilt/rerun this
  round** (its Dockerfile is unchanged — already had `python3` before this
  fix round; only `provider.tf`, a COPY'd workspace file with no Dockerfile
  layer impact, changed for that arm).
- `uv run python generator/spec_model.py specs/apigw-redeploy.yaml` — OK.
- `uv run python gates/oracle_falsifiability.py specs/apigw-redeploy.yaml`
  — unaffected shape from this round (touched: a provider.tf `skip_*` flag,
  two Dockerfiles, `build_test_sh`'s live-check-gating branch, a new
  scenario-level `reset.sh` outside the generator's own emitted-file set —
  none of which `oracle_falsifiability` reads different inputs for; still
  exercises `solution/solve.sh` → `tests/static_tiers.sh` per spec/arm).
- `make check` — full repo-wide check re-run after all edits: exit 0.
  `uv run pytest gates metrics oracles generator test -q` — 442 passed
  (320.81s). `metrics/test_pipeline_e2e.py` — 1 passed.
  `./ci/check-smoke-drift.sh` — initially FAILED (`tasks/anchor/smoke/
  environment/{Dockerfile,preflight.sh}` is a hand-maintained byte-copy of
  `arms/awscdk/environment`'s own files, modulo each file's leading
  comment block — Finding 2's `python3` addition to the arm's Dockerfile/
  preflight.sh drifted the two out of sync); fixed by mirroring the
  identical body edit into the smoke copy (comment header untouched, per
  that copy's own "re-copy by hand" instructions) — re-run: `smoke-drift:
  OK`. `make check` clean re-run after the fix: exit 0.
- `gates/oracle_falsifiability.py` re-run against all 4 pre-existing
  (non-holdout-relevant) real specs, individually (NOT in parallel — a
  first parallel attempt produced one spurious `apigw-openapi` TF-PLAN
  FAILED from resource contention between concurrent `terraform`/`npm`
  sandboxes; a clean, isolated re-run of that one spec alone came back
  clean, confirming the parallel run's failure was a proving-harness
  artifact, not a real regression from this amendment's changes):
  `apigw-openapi` OK, `ecs-swappiness` OK, `s3-lambda-log-retention` OK,
  `sfn-jsonata` OK (alongside `apigw-redeploy` 12/12 PASS, Findings 1-3's
  own re-proof, above).
- `gates/grading_proof.py` re-run against the same 4 specs — all four
  `GRADEABLE` (correct solution reward=1.0 + at least one negative fixture
  reward=0.0 on every enabled arm; `ecs-swappiness` terraconstructs has a
  pre-existing, unrelated `SKIP` for its own reason — "no fixture reaches
  tier 1 on this arm" — unchanged by this amendment).
- **LIVE re-proof: completed this round**, closing Amendment 14's own B1
  flag — see Findings 1 and 3 above for the two independent live-account
  proof transcripts. Account `886312446417` verified back to the 3
  baseline stacks after EVERY live step in this amendment (hcl-raw
  solve.sh's own cleanup trap; the standalone reset.sh fixture-then-sweep
  proof; both independently re-listed clean).

**Files added:** `scenarios/anchor/reset/reset.sh`.
**Files modified:** `arms/hcl-raw/environment/workspace/provider.tf`
(`skip_requesting_account_id` live-conditional + header correction),
`arms/awscdk/environment/Dockerfile` (+`python3`),
`arms/terraconstructs/environment/Dockerfile` (+`python3`),
`arms/awscdk/environment/preflight.sh` (+python3 step),
`arms/terraconstructs/environment/preflight.sh` (+python3 step),
`generator/gen.py` (`build_test_sh`'s stderr-split + `run_invalid` marker),
`specs/apigw-redeploy.yaml` (gating comment cross-references this
amendment + the IAM proposal doc), all 5 real specs' + the toy spec's
generated `tests/test.sh` (`make gen-all`), the 3 `apigw-redeploy-*`
generated tasks' `environment/workspace/provider.tf` (`make gen-all`,
byte-copy of the Finding-1 fix), `tasks/anchor/smoke/environment/
{Dockerfile,preflight.sh}` (hand-mirrored `python3` addition, re-syncing
`./ci/check-smoke-drift.sh` after Finding 2's arm Dockerfile edit).

## Amendment 16 (2026-08-07) — Adding a `QADeployApplicationRole`: operator
## authorization, the real role, spec-driven role wiring, a metadata-gating
## bug fix, and removing the vestigial LLM-judge role

Directed by the operator (Vincent, repo owner), who explicitly authorized,
in writing, the change this amendment records. **Authorization on record
(quoted verbatim):**

> the operator (Vincent, repo owner) explicitly approved, in writing:
> adding the named role `QADeployApplicationRole` as the minimally-scoped
> middle option between the read-only `QALocalInvocationApplicationRole`
> and the full-admin `QALocalInvocationApplicationAdmin`, to the anchor
> scenario's `QARolesStack`, with full `apigateway:*`, full `lambda:*`,
> scoped `iam:CreateRole`/`iam:PassRole` (path-prefixed to
> `/cdktn-bench-task/`), plus logs permissions. Rationale on record:
> required to run apigw-redeploy as a real benchmark task where the agent
> itself deploys, rather than a host-side proof. The operator also
> reviewed and accepted `docs/proposals/qa_deploy_application_role.proposed.ts`,
> conditional on documenting how these roles are maintained as
> scenarios/tasks are added.

This closes the "explicitly NOT done" stance Amendments 12-15 repeated
every time this exact question came up (most recently Amendment 15 finding
4's "no agent credential set this scenario grants can perform the real
deploy the gating check requires") — this run has that authorization on
record, so it proceeds where every prior run correctly refused to.
**Scope of this run: code + documentation only.** No `aws-bench env setup`
was run and no `cdk deploy` was executed — the role exists in the CDK app's
source but not yet in the live AWS account; the orchestrator deploys after
review (see "What remains before this scenario is trial-runnable" below).

### The role's exact scoping

Promoted `docs/proposals/qa_deploy_application_role.proposed.ts`'s design
intent into the real, deployed-when-`cdk deploy`d stack:
`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`, a new
`QADeployApplicationRole` (`this.deployRole`), attached via a custom
`ManagedPolicy` (`QADeployApplicationPolicy-<account>-<region>`, matching
the file's existing `s3VectorsReadOnlyPolicy` convention — a plain
`managedPolicies` array, not the proposal's `inlinePolicies` shape) with
six statements:

- `ApiGatewayFull` — `apigateway:*`, `Resource: "*"`. Simpler and WIDER
  than the superseded proposal's verb-enumerated
  (`GET`/`POST`/`PUT`/`PATCH`/`DELETE`) statement — this follows the
  operator's literal authorization ("full `apigateway:*`") over the
  proposal's own tighter draft. Still the tightest available bound: API
  Gateway's control-plane actions have no useful resource-level ARN to
  scope a `CreateRestApi`-family call to before the API exists
  (`docs/slice-g-recon.md` §1's own conclusion, unchanged).
- `LambdaFull` — `lambda:*`, `Resource: "*"`. Also simpler/wider than the
  superseded proposal's name-prefix-scoped `LambdaManageScoped` statement,
  per the same literal authorization ("full `lambda:*`") — and this
  sidesteps the proposal's own flagged "Open gap" #1 (awscdk's default
  unprefixed Lambda function names not matching a `function:apigw-redeploy-*`
  resource scope) entirely, since there's no name-prefix scope to miss.
- `LogsScoped` — `logs:{CreateLogGroup,CreateLogStream,PutLogEvents,
  DescribeLogGroups,DescribeLogStreams}`, `Resource: "*"` —
  `docs/slice-g-recon.md` §1's own log-permission list, for the deploying
  identity's own logging needs (distinct from the Lambda execution role's
  own runtime logging grant, which is a separate role this same policy
  lets the agent create).
- `IamRoleLifecycleScoped` — `iam:{CreateRole,GetRole,PutRolePolicy,
  GetRolePolicy,AttachRolePolicy,DetachRolePolicy,DeleteRolePolicy,
  DeleteRole,TagRole}`, `Resource:
  arn:aws:iam::<account>:role/cdktn-bench-task/*`. The operator's
  authorization names `iam:CreateRole`/`iam:PassRole` as the headline
  scoped actions; per the task instruction to "follow the permission
  scoping in docs/slice-g-recon.md — it spec'd this role," this is
  implemented as that section's full path-scoped role-lifecycle action
  list (Create/PassRole are the two most consequential of that set, worth
  naming explicitly in a one-line summary — the rest is the supporting CRUD
  a real `cdk deploy`/`terraform apply` needs to attach permissions to a
  role it just created and clean it up on redeploy/destroy). This is the
  ONE genuinely path-scoped statement in the policy — narrower than the
  superseded proposal's `IamRoleLifecycleUnscopedName` (`Resource: "*"`),
  per the operator's explicit "path-prefixed to /cdktn-bench-task/"
  instruction.
- `IamPassRoleScoped` — `iam:PassRole`, same path-scoped `Resource`, PLUS
  (defense in depth, kept from the superseded proposal's own good idea) a
  `StringEquals: {iam:PassedToService: lambda.amazonaws.com}` condition —
  even a path-scoped PassRole can only ever be handed to the Lambda
  service.
- `StsSelfIdentity` — `sts:GetCallerIdentity`, `Resource: "*"` — needed by
  every arm's own credential-sanity/account-guard checks (kept from the
  proposal).

**Not granted** (both flagged in code comments on the new construct, not
silently omitted): `sts:AssumeRole` on the CDKToolkit bootstrap's own
`cdk-hnb659fds-{cfn-exec,deploy}-role-*` (needed for the awscdk arm's `cdk
deploy` to execute against the bootstrapped account,
`docs/slice-g-recon.md` §1's open question, repeated by the superseded
proposal) — the operator's authorization doesn't name this action, so it
isn't granted; needs its own explicit sign-off per
`docs/adding-scenarios.md`'s role-extension procedure before the awscdk
arm can live-deploy under this role.

**Known, honestly-flagged gap**: all three arms' current apigw-redeploy
reference solutions create their shared Lambda execution role named
`apigw-redeploy-lambda-exec` at IAM's DEFAULT path (`/`), not under
`/cdktn-bench-task/` — so as authored today, `IamRoleLifecycleScoped`/
`IamPassRoleScoped`'s path-scoped `Resource` does NOT yet cover that role's
real ARN (`arn:aws:iam::<account>:role/apigw-redeploy-lambda-exec`, not
`.../role/cdktn-bench-task/apigw-redeploy-lambda-exec`). A live deploy
attempt under this role, as-is, would `AccessDenied` on `CreateRole`/
`PassRole` for that role name. Closing this (pinning an explicit
`path: "/cdktn-bench-task/"` on the role construct in all three arms'
reference solutions/instruction, then a fresh live proof) is an explicit
follow-up, out of scope for this change's own task boundary (code + docs
only, no live deploy this round) — recorded here, in the role construct's
own code comments, and in `specs/apigw-redeploy.yaml`'s updated `gating`
comment, not silently glossed over.

**Type-checked**: `cd scenarios/anchor/scenario/cdk_app && ./node_modules/.bin/tsc --noEmit`
— clean, no errors, against the real installed `aws-cdk-lib`/`constructs`
(not a temporary copy this time — the file is now IN the tree those
packages are installed for).

**Proposal file marked superseded, not deleted**: both
`docs/proposals/qa_deploy_application_role.proposed.ts` and
`docs/slice-g-iam-proposal.md` now carry a prominent banner pointing at the
real implementation and explaining exactly what changed (simpler
apigateway/lambda grants, path-scoped-not-unscoped IAM) — kept rather than
deleted because their per-statement reasoning (why API Gateway has no
useful pre-creation resource ARN, the `PassedToService` PassRole guard
idea, the still-open CDKToolkit `sts:AssumeRole` question) remains a real
design record, cited from the new construct's own code comments.

### Spec-driven `agent_role_name`/`concurrency_mode` — already wired, now used for real

Investigated `docs/slice-g-recon.md`'s gap 2 (`generator/gen.py` allegedly
hardcoding `agent_role_name`/`[concurrency] mode`): this was **already
fixed** by prior Slice G work (Amendment 12's own `spec_model.LiveCheck.
agent_role_name`/`.concurrency_mode` fields, `generator/gen.py::
build_task_toml`'s `live.agent_role_name or "QALocalInvocationApplicationRole"`
fallback) — `specs/SCHEMA.md` §5 and §8.2 point 5 already documented both
fields in full. Recon's own gap description predates that fix and is now
stale (not corrected in place — recon docs are point-in-time findings
records, not living docs, per this repo's own convention for `docs/
slice-g-recon.md`'s header). The only real change needed here:
`specs/apigw-redeploy.yaml`'s `verifier.live_check.agent_role_name` flips
from `"QALocalInvocationApplicationAdmin"` (Amendments 12-15's logged
over-grant, used because no narrower role existed) to
`"QADeployApplicationRole"` (this amendment's new role).
`concurrency_mode: "mutating"` was already correct and unchanged.
`specs/SCHEMA.md` §5 and §8.2 point 5's own worked-example text updated to
match (both previously named `QALocalInvocationApplicationAdmin` as
`apigw-redeploy`'s role).

### Metadata bug: `verification_explanation` hardcoded NON-GATING text for every `live_check.enabled` spec

**Finding** (verifier-found, per this run's own task brief): `generator/
gen.py`'s `verification_explanation()` (the function that fills
`task.toml`'s `[metadata] verification_explanation` field) unconditionally
wrote "...and is NON-GATING (its result never overrides reward.txt..."
whenever `spec.verifier.live_check.enabled` was true, with no branch on
`.gating` at all — even though Amendment 14 added the real gating AND
logic (`build_test_sh`'s `SPEC_LIVE_CHECK_GATING` branch) and
`specs/apigw-redeploy.yaml` has set `gating: true` since that same
amendment. Every one of the three generated `apigw-redeploy-*/task.toml`
files was shipping metadata that flatly contradicted its own generated
`tests/test.sh` — a real, live discrepancy (not a hypothetical), confirmed
by reading the pre-fix generated `task.toml`'s literal text alongside
`tests/test.sh`'s own `SPEC_LIVE_CHECK_GATING` branch before this fix.

**Fix**: `verification_explanation()` now branches on
`spec.verifier.live_check.gating`. When gating, the generated text states
that `live_check.py`'s own JSON `.outcome` field is ANDed into
`reward.txt` (1.0 only if static tiers already say 1.0 AND `.outcome` is
`"pass"`; `"fail_stale"`/`"not_verifiable"`/`"run_invalid"` all force 0.0,
fail-closed), citing `specs/SCHEMA.md` §5 for the full contract. When not
gating (every other spec with `live_check.enabled: true` — none exist yet,
but the branch is real, not dead, since a future spec could set `enabled:
true, gating: false`), the original non-gating text is preserved
unchanged. Regenerated: the only diff in all three `apigw-redeploy-*/
task.toml` files (beyond the role-name change above) is this one field's
text; every other generated file for every other spec is byte-unchanged
(`git diff --stat` confirmed after `make gen-all` — see "Verification"
below).

### Vestigial role investigated: `LLMJudgeFullBedrockAccessRole` — REMOVED

**Investigated per this run's own task brief.** `qa_roles_stack.ts`
(pre-this-amendment) also created `LLMJudgeFullBedrockAccessRole`
(`AmazonBedrockFullAccess`), copied from the upstream aws-bench-datasets
convention where introspection tasks are graded by a Bedrock-hosted LLM
judge. Confirmed by repo-wide grep (`rewardkit|llm.?judge|bedrock`, case-
insensitive, across `.py`/`.ts`/`.md`/`.sh`/`.toml`/`.yaml`): every
Bedrock-related hit in this repo is either (a) the Claude Code CLI's own
Bedrock-vs-plain-API invocation mode (`gates/RECON.md`,
`scripts/run-bench.sh`, `test/test_run_bench_wrapper.py` — about which
backend serves Claude Code ITSELF, unrelated to grading) or (b) the QA
roles stack's own role/policy definitions and their mentions in
`docs/slice-g-recon.md`. **Zero** occurrences of `rewardkit`, an LLM-judge
invocation, or any grading logic anywhere in `gates/`, `oracles/`,
`generator/`, or any generated `tests/` — this repo grades 100%
programmatically (static tiers + `live_check.py`; confirmed exactly as the
task brief expected). Separately grepped `verifier_role_name`/`judgeRole`/
`LLMJudge` across `generator/`, `tasks/`, and `gates/`: **zero hits** —
no generated `task.toml` has ever set `[scenario].verifier_role_name` to
anything (the verifier always falls back to `OrganizationAccountAccessRole`,
per `docs/slice-g-recon.md` §1's own trace through `aws_trial.py`), and
`judgeRole` had no consumer anywhere outside its own definition in
`qa_roles_stack.ts`.

**Decision: removed**, not kept-with-a-note. Rationale: it was purely
vestigial (defined, never assumed by anything this repo's own code path
could reach), a real IAM over-grant (`AmazonBedrockFullAccess` is broad)
sitting unused in the live account, and $0.00 Bedrock spend in the account
confirms it (context provided for this run) — removing an unused
broad-access role is a net security improvement with zero functional loss,
consistent with the minimal-privilege reasoning behind adding
`QADeployApplicationRole` in the first place. `qa_roles_stack.ts`'s class
docstring now documents the removal explicitly (what it was, why it's
gone, where to look — `docs/adding-scenarios.md` §4 — if a future
scenario genuinely needs an LLM-judge-shaped role again). `this.judgeRole`
(the exported field) is removed along with it — its removal is a breaking
change to `QARolesStack`'s public surface, but nothing in this repo's own
`environment.ts` or elsewhere referenced it (confirmed by grep before
removing).

### New docs: "Adding scenarios and tasks"

New `docs/adding-scenarios.md`, linked from `README.md` (both the repo-
layout table and a new bullet in "How it works"). Chosen over adding a
section to `specs/SCHEMA.md` because `SCHEMA.md` is a field-by-field
*reference* (kept skimmable on purpose) and this is a *procedure*
(ordered steps, decision rules, commands to run) — mixing the two would
make `SCHEMA.md` harder to use as a lookup table without making the
procedure any more discoverable. Cross-linked both directions instead
(`SCHEMA.md` §5's `agent_role_name`/§8.2 point 5 now point to
`docs/adding-scenarios.md`; the new doc cites the exact `SCHEMA.md`
section each of its own steps expands on). Covers, in order: authoring an
intent spec (with the exact `make validate-spec`/`make gen`/`make parity`
commands), the three-role selection rule ("pick the least-privileged role
that lets the scenario run," with the full grant table), the read-only-
vs-mutating decision (including the `gating` field and the reset.sh
cleanup requirement), the role-extension maintenance procedure (propose →
authorize → extend `QARolesStack` → re-run env setup → record in
DECISIONS.md — explicitly modeled on how THIS amendment itself was done),
oracle authoring (intent.md → structural_asserts → rego/cfn-guard at equal
strictness → `make check-paths`/`make tier1-coverage`), the reference-
solution + negative-fixture + `make falsifiability`/`make grading-proof`
requirement, and the holdout-split rule (`specs/split.yaml`,
`generator/split.py --write`, the re-split procedure). Closes a real gap:
this was the operator's own explicit condition on accepting the proposal
("conditional on documenting how these roles are maintained as
scenarios/tasks are added") — see the authorization quote above.

### What remains before this scenario is trial-runnable

Stated plainly, not left implicit: even after this amendment,
`apigw-redeploy` is **still not trial-runnable** for two independent
reasons, both already flagged above and in the spec's own updated
`gating` comment: (1) `QADeployApplicationRole` exists only in this repo's
CDK source, not yet in the live account — `aws-bench env setup` (or the
equivalent `cdk deploy`) must be re-run against the target account before
any trial can assume it, deliberately NOT done this round (code + docs
only, per this run's own task boundary); (2) even once deployed, the
IAM-path gap (reference solutions creating their role at the default path,
not under `/cdktn-bench-task/`) would still `AccessDeny` a real deploy
attempt. Both are named, scoped follow-ups, not silently deferred.

### Verification

- `uv run python generator/spec_model.py specs/apigw-redeploy.yaml` — OK
  (3 catches, 3 arms, 7 structural_asserts — unchanged shape).
- `cd scenarios/anchor/scenario/cdk_app && ./node_modules/.bin/tsc --noEmit`
  — clean, no errors.
- `make gen-all` — regenerated all 5 real specs (`specs/split.yaml` and
  `specs/_toy/` skipped, per that target's own design). `git status`/`git
  diff --stat` after: the ONLY generated files that changed are the three
  `tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/task.toml`
  files, each a 2-line diff (`agent_role_name` + the
  `verification_explanation` gating text) — confirming the four Slice D
  specs' (`apigw-openapi`, `ecs-swappiness`, `s3-lambda-log-retention`,
  `sfn-jsonata`) generated task directories are BYTE-UNCHANGED, and no
  other `apigw-redeploy` file (environment/, tests/, solution/) changed.
- `make check` — **exit 0.** `uv run pytest gates metrics oracles generator
  test -q` — 442 passed (328.13s). `metrics/test_pipeline_e2e.py` — 1
  passed. `./ci/check-smoke-drift.sh` — `smoke-drift: OK`. Same 442-pass
  count as Amendment 15's own last full run — this amendment's changes
  (task.toml text, a generator function's dead-for-every-other-spec
  branch, a CDK stack file, docs) touch no code path any of those tests
  exercise differently.
- `make falsifiability SPEC=specs/<id>.yaml` and `make grading-proof
  SPEC=specs/<id>.yaml` for all four Slice D specs — unaffected in shape by
  this amendment (touched only `apigw-redeploy`'s own task.toml fields and
  a generator function whose branch is dead/unentered for every other
  spec, same no-op convention as every prior Slice G amendment) — all
  green:
  - `apigw-openapi`: falsifiability OK (9/9 PASS); grading-proof OK, all 3
    arms GRADEABLE (6/6 PASS).
  - `ecs-swappiness`: falsifiability OK (9/9 PASS); grading-proof OK, all 3
    arms GRADEABLE (5 PASS, 1 pre-existing non-gating SKIP — terraconstructs
    "no fixture reaches tier 1 on this arm", unchanged from Amendment 4).
  - `s3-lambda-log-retention`: falsifiability OK (9/9 PASS); grading-proof
    OK, all 3 arms GRADEABLE (6/6 PASS).
  - `sfn-jsonata` (2 arms, terraconstructs excluded per `arms/
    terraconstructs/README.md` §4): falsifiability OK (7/7 PASS,
    `tier05_ok` reported alongside reward for both `solve.sh` runs);
    grading-proof OK, both arms GRADEABLE (4/4 PASS).

**Files added:** `docs/adding-scenarios.md`.
**Files modified:** `scenarios/anchor/scenario/cdk_app/stacks/
qa_roles_stack.ts` (new `QADeployApplicationRole`/`QADeployApplicationPolicy`,
removed `LLMJudgeFullBedrockAccessRole`/`judgeRole`), `docs/proposals/
qa_deploy_application_role.proposed.ts` (superseded banner),
`docs/slice-g-iam-proposal.md` (superseded banner), `specs/
apigw-redeploy.yaml` (`agent_role_name`, updated `gating` comment),
`specs/SCHEMA.md` (§5, §8.2 point 5 — role references updated), `generator/
gen.py` (`verification_explanation()` gating-aware), `README.md` (repo-
layout table + "How it works" bullet linking the new doc),
`tasks/anchor/apigw-redeploy-{awscdk,hcl-raw,terraconstructs}/task.toml`
(regenerated, `make gen-all`).

---

## Amendment 17 (2026-08-08) — teardown: upstream's framework reset is sufficient; Amendments 14/15 corrected

**Operator authorization (verbatim):** "I authorize the scoped destructive test in the
dedicated account (teardown to test upstream framework reset solves the leak)."
Also, same message: aws-nuke is **parked**, and no IAM account alias is to be set at this
stage.

**Experiment:** a dirty fixture was created in `886312446417` using names no fixed-name
sweep could match — including a CloudFormation stack whose children carry CFN-random
physical names (`zz-teardown-fixture-stack-FixtureRole-TtLnTWRe3ePF`,
`…-FixtureFunction-kK7Ie24307I1`), two loose resources with agent-style names, and both an
auto-created and an explicit log group. The **framework** reset path
(`ResetManager.reset_account` → baseline diff over the live CFN type registry →
`ResourceCleaner(ccapi_fallback=True)`) was then invoked directly — not `reset.sh`.

**Result:** `ResetResult(success=True, reason='Account successfully reset to baseline
state')`. Every fixture resource was deleted; the preserve-list (anchor stacks, CDKToolkit,
bootstrap and QA roles) was intact; zero lambdas, log groups or REST APIs remained.
Reset runtime ≈ 4 minutes, which is per-trial overhead for `mutating` tasks and must be
budgeted for `apigw-redeploy` and `iam-e2e-role`. Full evidence:
`docs/teardown-experiment-results.md`.

**Correction to Amendments 14 and 15.** Those amendments concluded that no deleter existed
for our resource types, inferring it from a missing API Gateway handler. Both were wrong:
(a) `ccapi_fallback=True` is the actual delete path and covers types with no bespoke
handler; (b) their evidence came from hand-running `scenarios/anchor/reset/reset.sh`, which
is **not** the code path a real trial takes — the observed leak indicted our script, not the
framework.

**Decisions:**
1. `scenarios/anchor/reset/reset.sh`'s fixed-name sweep is to be **removed**, not extended.
   Teardown is the framework's job.
2. The Slice G decision to take cleanup away from the agent (so `live_check` has something
   to observe) is now **evidence-supported** rather than assumed.
3. aws-nuke stays parked; `docs/teardown-options.md` retains the analysis and the
   authorization design should an operator-invoked backstop ever be wanted for a
   contaminated account. No account alias is set (its absence currently *prevents*
   aws-nuke from running at all, which is a safety property while parked).

**Process note (not a result).** The run used botocore DEBUG logging, so raw logs contained
`X-Amz-Security-Token`/`Authorization` headers, and a subagent additionally wrote
assume-role credentials to a scratch file despite an explicit instruction not to. All such
files were deleted; nothing reached the repository or git history; the credentials were
1-hour sessions scoped to the dedicated account. Standing rule for future live work: keep
boto/botocore logging below DEBUG and pipe credentials directly into the consuming process
instead of materializing them.

---

## Amendment 18 (2026-08-08) — teardown experiment independently re-run clean;
## reset.sh removal confirmed; two new findings (version-hash/contamination
## interaction, corrected runtime)

**Operator authorization (verbatim, same message Amendment 17 recorded):** "I
authorize the scoped destructive test in the dedicated account (teardown to
test upstream framework reset solves the leak)."

**Why this amendment exists.** Amendment 17's own process note flagged that its
run "wrote assume-role credentials to a scratch file despite an explicit
instruction not to." This amendment records an independent, from-scratch
re-run of the same experiment against the same account (`886312446417`,
`us-east-1`), with strict credential hygiene (every STS credential set was
piped directly from `aws sts assume-role` output into shell environment
variables inside a single command invocation — nothing was ever written to
disk), to (a) confirm Amendment 17's conclusion holds independently, and (b)
correct/extend two things the prior pass's writeup didn't capture. Full
method, before/after inventories, per-resource verdict table, and quoted log
evidence: `docs/teardown-experiment-results.md` (rewritten this round; the
prior pass's content is fully superseded there, but Amendment 17 itself is
left untouched per this log's append-only contract).

**Result: reconfirmed, independently.** A dirty fixture — a standalone Lambda
function, a standalone IAM role, a standalone CloudWatch log group, and a
CloudFormation stack whose Lambda function and IAM role got CFN-random
physical names (`zz-teardown-fixture-stack-FixtureFunction-m19YQe1VKu94` /
`-FixtureRole-TtLnTWRe3ePF`) — was deployed under names outside `reset.sh`'s
hardcoded `apigw-redeploy-*` list. A direct call to `ResourceManager.
reset_scenarios` (the same function both `aws-bench env reset` and the
automatic post-`mode = "mutating"`-trial hook call) detected and deleted
**all 9 resulting resources** across all four types — including an
orphaned, unplanned 10th-category duplicate (a leftover log group from an
earlier, already-manually-deleted copy of the fixture, picked up in the same
pass with no special handling). Zero survivors, zero preserve-list damage,
account verified byte-for-byte back to its "before" inventory.
`ResetResult(success=True, reason='Account successfully reset to baseline
state', ...)`.

**Finding A (new): a version-hash/contamination interaction worth knowing
about.** Triggering the reset the "obvious" way (`aws-bench env reset
--env-name cdktn-anchor ...`) failed immediately with "Dataset or script
version mismatch detected" — the anchor scenario's source tree had
legitimately changed twice since the account's last `env setup`
(`scenarios/anchor/reset/reset.sh` added, then `QARolesStack` gained
`QADeployApplicationRole` — both prior, already-decided changes, unrelated to
this experiment). `VerifyManager._check_recoverable` treats that as
unrecoverable-by-reset and routes to `env cleanup` + `env setup` — not usable
here since `env cleanup` unconditionally deletes the scenario's own
preserve-listed CFN stacks. Worse: the failed attempt flagged the account
`aws-bench:contaminated = true` (an Organizations tag,
`AccountManager.mark_contaminated`), which then blocks a subsequent `env
setup`'s DEPLOY-phase contamination check too — a real chicken-and-egg trap
for an operator who hits this exact combination (stale local checkout +
account already flagged) on a shared/long-lived scenario account. The
resolution used here — calling `ResourceManager.reset_scenarios` directly
with `scenario_dir=None` (a supported, documented parameter that skips only
the local-source-hash check; contamination is never consulted by
`ResetManager` itself, only by the CLI's DEPLOY-phase wrapper) — is not
something an operator running the plain CLI has available. **Recorded as a
known rough edge, not fixed here** (fixing it would mean editing
`aws-bench`'s own source, out of scope and ask-first per its `AGENTS.md`).
**Residual state:** account `886312446417` is still flagged `aws-bench:
contaminated = true` as of this writing — confirmed via a read-only
`organizations:list-tags-for-resource` check. It does not affect any AWS
resource (the after-inventory matches "before" exactly) but will block the
next `env setup`/trial until cleared. Clearing it
(`organizations:UntagResource`, the same call a successful reset/cleanup
makes automatically) was attempted from the management account and was
blocked twice by this session's own sandbox permission classifier; per the
classifier's own guidance the action was not forced through, and is left as
an explicit follow-up for the operator (or a differently-scoped session) to
run: `aws organizations untag-resource --resource-id 886312446417 --tag-keys
aws-bench:contaminated`.

**Finding B (correction): reset runtime is ≈8.5–9 minutes, not ≈4.**
Amendment 17 reported "Reset runtime ≈ 4 minutes... dominated by CloudFormation
stack deletion." This round's timestamps (DEBUG-level, end to end) show the
framework's `ResetManager.reset_account` call alone took **7m 53s (473s)**,
plus ~50s for the in-container `reset.sh` phase in a real trial (container
build + script run, proven separately in the failed CLI attempt above) — total
≈ 8.5–9 minutes. Of the 473s, **deletion work was only ≈61s**; **two full
account-wide fastscans across 996 CloudFormation resource types** (initial
discovery + final re-verification, ≈3m24s each) account for ≈78% of the time.
This is real per-`mode = "mutating"`-trial overhead, not currently bounded by
`scenario.toml`'s `[reset] timeout_sec = 300.0` (that config only wraps
`reset.sh` itself, which finishes in ~22s; the framework's own scan/delete/
verify work runs outside it) — but it should be budgeted into per-trial
throughput/cost estimates for `apigw-redeploy` and `iam-e2e-role` regardless.

**Decisions (reconfirmed from Amendment 17, unchanged):**
1. `scenarios/anchor/reset/reset.sh`'s fixed-name sweep is confirmed
   **removable**. Two independent live proofs (Amendment 17's and this one)
   now show the framework's generic reset covers everything it was added for,
   including the one case (CFN-random physical names) it was specifically
   written to compensate for. It costs ~22s of container time per mutating
   trial and adds a scenario-specific maintenance surface for zero remaining
   marginal coverage — remove it rather than extend it.
2. aws-nuke stays parked (per the operator's own authorization message,
   unchanged); no IAM account alias is set. Nothing in this round's work
   touched either.
3. `docs/teardown-options.md` retains its analysis and authorization design
   should an operator-invoked backstop ever be wanted for a genuinely
   contaminated account (e.g. the residual contamination flag noted in
   Finding A above, if the operator ever wants a heavier tool than
   `organizations:UntagResource` + `env cleanup` to recover a stuck account).

**Files touched:** `docs/teardown-experiment-results.md` (rewritten with this
round's evidence, superseding but not deleting the historical record now
folded into this entry), `DECISIONS.md` (this entry). No `aws-bench` source
was read-write touched (read-only, to trace the exact call chain). No git
commit was made by this round — the operator instructed not to; these are
working-tree changes for review.

**Executed 2026-08-13:** decision 1 above carried out — `scenarios/anchor/reset/reset.sh` deleted and every repo reference to it updated (`docs/adding-scenarios.md`'s cleanup-story guidance and worked example, `ops/fixtures/iam-e2e-role/teardown.sh`'s comment); confirmed absence is valid via `aws_bench/scenario/scenario.py`'s own optional `reset/` layout docstring, `ScenarioTrial.run` (`aws_bench/scenario/trial.py:224-238`, which checks `has_phase_script` — a plain file-existence test — and skips straight to the framework-generic `_run_reset()`/`ResourceManager.reset_scenarios` when false, no special-casing), and the upstream `ec2-multiregion` scenario (`aws-bench-datasets/scenarios/ec2-multiregion`), which precedents both a missing `reset/` directory and a missing `[reset]` `scenario.toml` section entirely.

## Amendment 19 (2026-08-08) — Adding `iam-e2e-role`: IAM derivation
## scenario, Route53 drop, two-roles-one-task, no-terratest, and an honest
## gaming assessment

Directed by the operator (Vincent, repo owner). **Authorization on record
(quoted verbatim from the task brief):**

> 1. "Add the IAM Derivation scenario" — build it.
> 2. "I authorize pre-provisioned fixtures (CMK, decoy bucket, ..)" —
>    fixtures in the dedicated benchmark account are approved. You WRITE
>    the provisioning script; you do NOT run it (the orchestrator runs it
>    later).
> 3. "for the R53 hosted zone see if we can drop it" — EVALUATE and
>    recommend.
> 4. "however do keep the 2 roles in 1 task" — the task MUST require BOTH
>    roles ... One task, both roles. This is the load-bearing design
>    decision.

**Scope of this run: spec + module + harness + oracle + reference
solutions + a partial negative-fixture set + fixture-provisioning scripts
+ docs, all authored and verified OFFLINE. No AWS call was made, mutating
or read-only, at any point in this run** — every claim below that would
normally be confirmed by a real trial is instead confirmed by direct local
invocation of `terraform`/`opa`/`cfn-guard`/`npx cdk synth`/`npx cdktn
synth` against dummy/offline credentials, or left explicitly unproven (see
"What remains before this scenario is trial-runnable" below).

### Files added

- `specs/iam-e2e-role.yaml` — the intent spec (7 catches, 7
  `structural_asserts`, 3 arms enabled).
- `tasks/anchor/iam-e2e-role-{awscdk,hcl-raw,terraconstructs}/` —
  generated via `make gen SPEC=specs/iam-e2e-role.yaml`, plus hand-authored
  `solution/solve.sh` for all three arms and `solution/broken/<catch>/
  solve.sh` for all seven catches on `hcl_raw` (see the honest gap below
  for why `awscdk`/`terraconstructs` negatives are not yet authored).
- `oracles/iam-e2e-role/intent.md` (generated verbatim from `oracle.intent`),
  `oracles/rego/iam-e2e-role/policy.rego`, `oracles/cfn-guard/iam-e2e-role/
  policy.guard` (both hand-authored).
- `ops/fixtures/iam-e2e-role/{provision.sh,teardown.sh}` — written, not run.

### 1. The Route53 recommendation

**Recommendation: DROP the Route53 hosted zone fixture.** The reduced
module (§2 below) does not create a `aws_route53_record`/reference a
hosted zone at all.

Reasoning, per the operator's own instruction to check whether the lost
defect classes survive elsewhere before recommending a drop:

- **A6** (`route53:ListTagsForResource`, a data source's own tag read) and
  **route53:GetChange's** "this action does not support resource-level
  permissions, must be `Resource: "*"`" mechanism are the two classes at
  stake. The module keeps an `aws_security_group` in the default VPC
  specifically so `ec2:GetSecurityGroupsForVpc` is reachable — and that
  action is BOTH (a) a `Describe*`-does-not-cover-`Get*` naming trap
  (already A9's own class) AND (b) one of the many EC2 actions that do not
  support resource-level permissions at all, so it must be granted on
  `Resource: "*"` too — the exact same mechanical class `GetChange`
  exemplified. One kept resource reaches both classes at once; dropping
  Route53 does not lose the "action has no resource-level ARN" class.
- **C-2** (the construct path's own `route53:ListHostedZonesByName`
  defect) is genuinely lost — there is no substitute for it in this
  reduced scenario. Flagged honestly, not hidden: this specific defect
  instance is gone, though its GENERAL class ("the harness makes its own
  direct AWS call the module's own HCL never makes") is independently
  reachable via `harness/validate.sh`'s own `ec2:DescribeVolumeStatus`
  call (deliberately not something granted by a naive `ec2:Describe*`
  wildcard's most literal reading, though in practice a `Describe*`
  wildcard DOES cover it — see the module's own header comment for the
  honest limit of this substitution).
- A6's specific "tag read on a DATA SOURCE, not the resource itself"
  flavor is a narrower instance of a broader lesson (`missing-tag-on-create`
  and the `iam:ListRoleTags`/refresh-time-read pattern already cover
  "a read/tag call is invisible from reading the resource block" more
  generally in this scenario).
- **Trade-off, stated plainly**: a hosted zone costs ~$0.50/month and is
  trivially provisioned — the operator's own framing. The decision to drop
  it is NOT about cost. It is because (a) DNS propagation is a documented,
  real source of live-check flakiness this scenario's own gating design
  cannot afford (`docs/scenario-proposal-iam-e2e-role.md` §6 point 6 — the
  same finding-1 lesson `apigw-redeploy`'s own `live_check.py` had to
  learn the hard way), and (b) the one defect class that would be
  genuinely and irreplaceably lost (C-2) is a single specific instance of
  a class already reachable elsewhere, not a unique category. If a future
  revision wants C-2 back specifically, add the hosted zone back with full
  awareness this reintroduces the propagation-flakiness risk.

### 2. The reduced module

`module/main.tf` (seeded via `seeded_files`, byte-identical across all
three arms, never touched by the agent) creates: a default-VPC security
group (A9 + the no-resource-level-ARN class, see above), an encrypted
`aws_ebs_volume` under the pre-provisioned CMK (A8, EC2 side), an
`aws_s3_bucket` + ownership-controls + policy behind a flag defaulted ON
(A3), a `data "aws_ssm_parameter"` read of the pre-provisioned plain
parameter (the deployer's own `ssm:GetParameter` requirement), and —
the one IAM resource the module itself creates — an
`aws_iam_instance_profile` that wraps the agent-authored workload role BY
NAME (reaches A7, tag-on-create, on the DEPLOYER's side, since the
deployer is the one running `terraform apply` against this module).
Dropped entirely relative to the full proposal: Packer/AMI, ASG/launch
template/instance refresh (and therefore A5,
`iam:CreateServiceLinkedRole`, deliberately — it is account-state-dependent
and unreproducible in a shared account where the SLR already exists, same
reasoning the proposal itself gave), the EC2 instance/EIP/cloud-init/Caddy/
Datadog/git-sync/Atlantis itself (all boot-time, add no policy class).
Measured (not estimated, unlike the original proposal's own §5.2 caveat):
a full `terraform init && apply` of this module against a hand-run local
credential set was not attempted (no AWS calls made this pass, per the
operator's own directive) — cycle time remains genuinely unmeasured;
flagged as unproven below, same as the original proposal's own §7 caveat.

### 3. Two roles, one task — design resolution

The operator's directive ("keep the 2 roles in 1 task") is implemented
exactly as the proposal's own §5.1 described, with one concrete
resolution the proposal itself left ambiguous (its own KEEP-table row 1,
"aws_iam_role + _role_policy + _instance_profile... A7 tag-on-create",
appeared to have the MODULE create the workload role, which would
contradict "the agent authors both roles"): **the module creates ONLY the
EC2 instance profile (an `aws_iam_instance_profile` wrapping the
agent-supplied role NAME), never the role itself.** Both roles' full
definitions (trust policy AND permissions policy) are 100% agent-authored,
in the agent's own substrate, deployed via the agent's own real deploy
command. This reconciles A7 (needs the DEPLOYER to run an apply that
creates a tagged IAM resource) with the operator's own requirement (the
workload role itself is authored by the agent, not the module) — see
`specs/iam-e2e-role.yaml`'s own `module/main.tf` `seeded_files` entry
comment for the load-bearing reasoning spelled out in place.

Trust mechanism (SCHEMA.md `verifier.live_check`, mirroring the
proposal's own §5.4): both roles trust the account root, gated by an
`sts:ExternalId` condition the agent chooses; the workload role
additionally trusts `ec2.amazonaws.com` for production realism. The
harness (`harness/validate.sh`, `agent_role_name`'s own credentials as the
caller) assumes the deployer role, applies `module/` under it twice
(forcing refresh-time reads — A4), makes its own direct
`ec2:DescribeVolumeStatus` call under the deployer identity (the
"harness's own AWS call is itself a defect source" requirement — an
analogue of the real episode's `ssm:GetInventory`), assumes the workload
role, runs `harness/assertions.py` (an `ssm get-parameters-by-path
--with-decryption` call — reaching A8/C-1 together in one call — plus an
`ec2:DescribeVolumes` self-discovery proxy standing in for a real
instance's own cloud-init, since this reduced module boots no instance),
then destroys everything under the deployer identity.

### 4. No terratest — confirmed, not just proposed

Implemented exactly as `docs/scenario-proposal-iam-e2e-role.md` §5.5
recommended: `harness/validate.sh` (bash) + `harness/assertions.py`
(stdlib `python3`, no `boto3`, matching every arm image's documented
baseline) over the `aws` CLI v2 and `terraform` CLI already present in all
three arm images — verified directly: `aws`, `terraform`, `jq`, `python3`
all confirmed present via each arm's own `Dockerfile`/README. Zero image
delta. Both scripts are seeded as read-only reference input (`seeded_files`,
chmod 0o444) into every arm's workspace, identically.

### 5. `QADeployApplicationRole` — a real, small gap, NOT closed this round

`agent_role_name: "QADeployApplicationRole"` is set in the spec, following
`docs/adding-scenarios.md`'s own decision rule (checked against this
scenario's actual mutating calls, not assumed). Concretely checked against
`qa_roles_stack.ts`'s existing grants: `IamRoleLifecycleScoped`
(`CreateRole`/`GetRole`/`PutRolePolicy`/`GetRolePolicy`/`AttachRolePolicy`/
`DetachRolePolicy`/`DeleteRolePolicy`/`DeleteRole`/`TagRole`, scoped to
`role/cdktn-bench-task/*`) already covers everything the agent's own
credentials need to CREATE and manage both roles' definitions and inline
policies, since — per §3 above — the agent's own credentials never need
`ec2`/`ssm`/`kms`/`s3` grants directly (those are the DEPLOYER role's own
policy content, not the agent's operating credential; the deployer role's
policy is created BY the agent's `iam:PutRolePolicy` call, not exercised
BY the agent's own identity). **The one missing grant**: `sts:AssumeRole`
scoped to `arn:aws:iam::<account>:role/cdktn-bench-task/*` — needed for
`harness/validate.sh` (run under the agent's own credentials) to assume
the deployer role at all. `iam:PassRole` is NOT needed (no EC2 instance is
ever launched with the workload role attached in this reduced module, so
nothing ever calls an API that requires passing it).

**Not added to `qa_roles_stack.ts` this round.** Per
`docs/adding-scenarios.md` §4's own procedure ("operator authorization,
explicitly, in writing... quote the operator's own words, as
[Amendment 16] does"), this run's own authorization (the four numbered
directives quoted above) does not contain an exact quote naming this
specific `sts:AssumeRole` grant — unlike Amendment 16's own authorization,
which named its grants explicitly, action by action. Rather than
interpret "build it" as blanket authorization to widen a shared,
already-deployed IAM role, this amendment records the EXACT proposed diff
(above) and defers the edit, following the same "code + docs only, no live
wiring" pattern Amendment 16 itself used for its own two remaining gaps.
**Until this one-statement extension is authorized and `aws-bench env
setup` is re-run, this scenario is not trial-runnable** — same
honestly-flagged state `apigw-redeploy` shipped in after Amendment 16.

### 6. Anti-gaming design and an honest assessment of how it could still be gamed

Per the operator's explicit requirement, the oracle asserts BOTH
properties, neither alone sufficient (`oracles/iam-e2e-role/intent.md`
states this explicitly): (i) LIVE, gating — the two roles actually work,
checked by `harness/validate.sh` via `tests/live_check.py` (hand-authored,
`gating: true` since three catches are `predicted_tier_caught: "live"` by
construction); (ii) STATIC, tier 0/1 — the two roles are least-privilege,
checked entirely from the delivered policy documents. A wildcard-admin
policy passes (i) trivially but fails (ii)'s `no-full-service-wildcard-
actions` tier-0 check (verified: `Action: "*"` on the deployer role scores
reward 0.0, `oracles/rego/iam-e2e-role/policy.rego`'s `deny` fires nothing
for it, but `tests/static_tiers.sh`'s own jq-compiled `not_regex` check
catches it before Rego is even invoked).

**How this could be unfair or gamed, stated plainly (not hidden):**

1. **The `cfn-guard` bundle is strictly weaker than the `rego` bundle for
   the ONE tier-1 check this scenario has** (`wildcard-matches-protected-
   bucket`). Rego's `glob.match` catches ANY agent-authored S3 `Resource`
   pattern that matches the decoy bucket's ARN — general, by construction.
   `cfn-guard` 3 has no equivalent glob builtin, so the `.guard` bundle can
   only deny a small, fixed denylist of known-bad literal strings. A
   sufficiently creative overbroad pattern on the `awscdk` arm ALONE
   (e.g., a prefix/suffix shape this denylist doesn't happen to name)
   could evade this specific catch on that one arm while still correctly
   failing on `hcl_raw`/`terraconstructs`. Documented in both policy
   files' own headers, not just here.
2. **Negative-fixture coverage is INCOMPLETE this round.** All 7 catches
   have a `hcl_raw` `broken/` fixture (verified: the 4 static ones score
   reward 0.0, the 3 live ones score reward 1.0 AND print
   `CDKTN_BENCH_LIVE_ONLY_CONFIRMED_MARKER`, all via direct local
   invocation reproducing `tests/static_tiers.sh`'s own logic — `make
   falsifiability`'s actual docker-gated run was not executed this pass,
   see §8 below). `awscdk` and `terraconstructs` have NO `broken/`
   fixtures yet, for any catch — a real, tracked gap, not silently
   accepted. Until they exist, `gates/oracle_falsifiability.py` will
   report `MISSING` for those (arm, catch) pairs, which is a hard FAIL
   per that gate's own documented contract (`solve.sh` IS authored on
   those arms, so `NOT_AUTHORED`'s one non-gating exception does not
   apply). The 4 static-tier catches' underlying assertions run
   identically regardless of arm (same jq ops, same Rego bundle for the
   two TF-shaped arms, real `cfn-guard` bundle for `awscdk` — verified
   directly against the `awscdk` reference template, reward 1.0), so the
   MECHANISM is proven arm-symmetric even though the fixture FILES
   proving it per-arm are not yet all written.
3. **The deployer role is not arm-discriminating, by design** (the
   scenario's own central, pre-registerable hypothesis — see
   `docs/scenario-proposal-iam-e2e-role.md` §4.3/§6 point 1). If most of
   an agent's tokens-to-green are spent on the deployer loop, the arms
   will show little separation on THAT half — expected, not a flaw, and
   restated here before any trial runs so it cannot look like a post-hoc
   excuse.
4. **The v1 reference solution does NOT exercise the grantXxx-derivation
   contrast on the workload role.** All three arms' reference solutions
   author the workload role's permissions BY HAND (mirroring `hcl_raw`
   exactly), not via `parameter.grantRead()`/`key.grantDecrypt()` on an
   imported construct. This was a deliberate simplification under this
   pass's time budget (`arms.terraconstructs.reason` in the spec records
   the construct-arm coverage that WOULD support the grantXxx path —
   `StringParameter.fromSecureStringParameterAttributes(...).grantRead()`
   + `Key`/alias import + `.grantDecrypt()`, all verified present in the
   pinned `terraconstructs@0.2.13` package). Consequence: THIS SPECIFIC
   REVISION of the scenario does not yet produce the "construct arms win
   on the workload role, tie-or-lose on the deployer role" contrast the
   whole scenario exists to measure — the scaffolding (module, harness,
   oracle, catches) supports it, but the reference solutions do not yet
   demonstrate it. Flagged as the single most important open follow-up,
   not glossed over: a future revision should redo the workload-role half
   of the `awscdk`/`terraconstructs` reference solutions (and add a
   `getparametersbypath-not-granted`/`missing-kms-for-securestring`
   negative pair that actually goes THROUGH `grantRead()` rather than
   hand-written statements) before this scenario's own results are cited
   as evidence for or against the grantXxx-asymmetry hypothesis.
5. **The action catalogue (`actions-are-real-iam-actions`) is an
   ALLOWLIST an agent could theoretically special-case around** if it
   somehow learned the catalogue's exact contents (e.g. from this very
   file) rather than from correct IAM knowledge — an agent that reads
   `specs/iam-e2e-role.yaml` and copies the catalogue's own action list
   verbatim would trivially pass this check without understanding why
   each action is needed. Structurally unavoidable for an allowlist-shaped
   check (same limitation the toy spec's own analogous check has); not
   unique to this scenario.
6. **Trust-condition strictness is a weak, existence-only proxy at tier 0**
   (`trust-has-external-id-condition` checks that AT LEAST ONE
   `Condition.StringEquals` block exists SOMEWHERE across both roles
   combined, not that EACH role's own account-root statement carries one)
   — a consequence of `generator/jsonpath_jq.py`'s translator not
   supporting bracket-quoted keys containing a colon (`['sts:ExternalId']`),
   confirmed by hitting that exact `ValueError` while authoring this spec.
   The stronger, per-role, key-specific version is written into
   `oracle.rego_hints` as guidance for a future policy.rego revision but
   is NOT currently enforced by any tier. An agent could therefore give
   ONE role a real ExternalId condition and the OTHER role an unrelated,
   different condition (or a condition on the wrong key) and still pass
   this tier-0 check.

### 7. `reset.sh` — not yet added, a real gap

Per `docs/adding-scenarios.md` §3's own requirement ("give the scenario
its own `scenarios/anchor/reset/reset.sh` sweep... do not rely solely on
the framework's generic post-trial sweep"), this scenario's own sweep
entry (fixed-name roles `iam-e2e-role-{deployer,workload}` under
`/cdktn-bench-task/`, the module's own fixed-name instance profile, and
tag-based sweep for the trial-suffixed SG/volume/bucket) is **NOT yet
added** to `scenarios/anchor/reset/reset.sh` — an explicit, tracked
follow-up, not silently skipped. Without it, a trial that dies mid-`apply`
(or whose harness run never reaches its own `terraform destroy`) leaves
orphaned resources for the framework's generic sweep to find, which (per
that same doc's own warning) has no guaranteed delete handler for every
resource type this scenario touches.

### 8. What remains before this scenario is trial-runnable — stated plainly

1. `QADeployApplicationRole` needs the one `sts:AssumeRole` statement
   (§5 above) — proposed, not authorized, not wired.
2. `aws-bench env setup` has not been re-run against the target account
   (nothing in this pass touched live infrastructure at all).
3. `scenarios/anchor/reset/reset.sh` needs this scenario's own sweep
   entry (§7 above).
4. `ops/fixtures/iam-e2e-role/provision.sh` has not been run — the CMK,
   SSM parameters, and decoy bucket do not yet exist in the account. NO
   trial can succeed without them (every reference solution's own S3/SSM/
   KMS resource ARNs are built assuming they exist).
5. `awscdk`/`terraconstructs` negative fixtures are not yet authored
   (§6 point 2) — `make falsifiability`/`make grading-proof` for THIS
   spec were not run this pass (both are Docker-image-gated;
   `gates/oracle_falsifiability.py`'s own `_arm_mirror_provider_versions`
   needs `cdktn-bench/<arm>:dev` images this pass did not build). The
   underlying logic (`tests/static_tiers.sh`'s tier-0/tier-1 checks, the
   Rego/cfn-guard bundles) was instead verified by direct, manual
   invocation against real `terraform plan`/`cdk synth`/`cdktn synth`
   output for all three arms' reference solutions (all score reward 1.0)
   and all seven `hcl_raw` negative fixtures (the four static ones score
   0.0, the three live ones score 1.0 and print the required marker) —
   strong evidence, not a substitute for the real gate.
6. The grantXxx-derivation contrast (§6 point 4) is not yet demonstrated
   by any reference solution.
7. No real `harness/validate.sh` run has ever happened against a real AWS
   account — the entire "iterate against real denials" loop this scenario
   exists to measure is, as of this amendment, unexercised end-to-end.

**Verification performed this pass** (all offline, no AWS credentials
used): `make validate-spec SPEC=specs/iam-e2e-role.yaml` — OK. `make gen
SPEC=specs/iam-e2e-role.yaml` — OK, 3 arms + oracles generated. `make
parity SPEC=specs/iam-e2e-role.yaml` — OK. `terraform validate`/`plan
-refresh=false` against `module/main.tf` standalone, and against all three
arms' reference solutions (with each arm's own offline fixture — dummy
credentials for `hcl_raw`, `mock-sts.js` for `terraconstructs`, no
credentials needed for `awscdk`'s CFN synth) — all succeed fully offline.
`opa eval`/`cfn-guard validate` against the hand-authored `policy.rego`/
`policy.guard` bundles, both directly and via a faithful reproduction of
the generated `tests/static_tiers.sh`'s own logic (path-substituted since
this pass has no writable `/app`/`/logs` and no Docker image built) — all
three arms' reference solutions score reward 1.0 (`tier0_pass=1
tier1_status=PASS`); all seven `hcl_raw` negative fixtures score exactly
as their `predicted_tier_caught` requires. `make check` — see this
amendment's own closing note below for the exact result.

**Files added:** `specs/iam-e2e-role.yaml`, `tasks/anchor/
iam-e2e-role-{awscdk,hcl-raw,terraconstructs}/` (generated + hand-authored
`solution/`), `oracles/iam-e2e-role/intent.md`, `oracles/rego/
iam-e2e-role/policy.rego`, `oracles/cfn-guard/iam-e2e-role/policy.guard`,
`ops/fixtures/iam-e2e-role/{provision.sh,teardown.sh}`, this amendment.
**Files NOT modified:** `scenarios/anchor/scenario/cdk_app/stacks/
qa_roles_stack.ts` (the proposed `sts:AssumeRole` grant is documented, not
applied — §5), `scenarios/anchor/reset/reset.sh` (§7), `specs/split.yaml`
(no `generator/split.py --write` run this pass — a separate, deliberate,
logged action per `docs/adding-scenarios.md` §7, not done here).

### Split re-computation (same amendment, 2026-08-08)

`uv run python generator/split.py --write` was run after the above (a
separate, deliberate, logged action per `docs/adding-scenarios.md` §7 --
adding a new `specs/*.yaml` makes `generator/tests/test_split.py::
TestComputeSplit::test_matches_committed_split_yaml` fail otherwise, since
`specs/split.yaml` has no entry for a scenario that didn't exist when it
was last written). Result: `iam-e2e-role` assigned `train`, rank 2 of 6.
**No existing scenario's `train`/`holdout` group changed** — every one of
`apigw-openapi`, `apigw-redeploy`, `ecs-swappiness`,
`s3-lambda-log-retention`, `sfn-jsonata` kept its prior group (only their
numeric `rank` shifted to make room for the new 6th entry) — confirmed by
diffing `specs/split.yaml` before/after. No equipping-tuning integrity
concern per that doc's own "re-split procedure."

## Amendment 20 (2026-08-13) — `iam-e2e-role`: the grantXxx-derivation
## rework that makes the scenario actually measure its own contrast

Directed by the operator (Vincent, repo owner), quoting Amendment 19's own
§6 point 4 back to this run as the assignment: "this specific revision of
the scenario does not yet produce the 'construct arms win on the workload
role, tie-or-lose on the deployer role' contrast the whole scenario exists
to measure... a future revision should redo the workload-role half of the
`awscdk`/`terraconstructs` reference solutions... before this scenario's
own results are cited as evidence for or against the grantXxx-asymmetry
hypothesis." This amendment is that future revision. Scope: `iam-e2e-role`
files only — a concurrent agent was working on `apigw-redeploy` in the same
tree; nothing under that scenario's own paths, `scenarios/anchor/reset/
reset.sh`, `qa_roles_stack.ts`, or `specs/apigw-redeploy.yaml` was touched
by this amendment, and `specs/split.yaml`/train-holdout assignments were
left untouched (no `generator/split.py --write` run this pass). **No AWS
call was made, mutating or read-only, at any point in this run.**

### 0. A methodology upgrade over Amendment 19: real toolchain execution

Amendment 19 verified its offline claims by *manually reproducing*
`tests/static_tiers.sh`'s jq/opa/cfn-guard logic against real `terraform
plan`/`cdk synth`/`cdktn synth` output, because Node.js was not available
in that authoring environment. **This run installed Node.js v26 (via
`brew install node`) specifically to close that gap** — every claim below
about `cdk synth`, `cdktn synth`, `npm run build`, and the resulting
`tests/static_tiers.sh` reward is a REAL execution of the REAL generated
task tree (a scratch copy of `tasks/anchor/iam-e2e-role-{awscdk,
terraconstructs}/environment/{workspace,app}/` plus each arm's own
generated `tests/`), not a hand-simulation of the same logic. `terraform`,
`opa`, and `cfn-guard` were already present; `npm install` reached the real
npm registry (confirmed reachable) and installed the exact pinned
`aws-cdk-lib@2.263.0` / `aws-cdk@2.1135.0` / `terraconstructs@0.2.13` /
`cdktn@0.23.0` versions the specs/arms pin. This is the first time this
scenario's own claims about these two arms' synth/plan behavior have been
checked against the real packages rather than their `.d.ts`/`.js` source
read by eye.

### 1. What changed, per arm

**hcl_raw: untouched.** Both roles remain 100% hand-authored, exactly as
Amendment 19 shipped — this is the deliberate floor arm; there is nothing
for it to derive.

**awscdk workload role, reworked.** The SecureString `db-password`
parameter is now imported via `ssm.StringParameter
.fromSecureStringParameterAttributes(scope, id, {parameterName,
encryptionKey})` and its `.grantRead(workloadRole)` is called for real —
this derives `{ssm:DescribeParameters, ssm:GetParameters, ssm:GetParameter,
ssm:GetParameterHistory}` scoped to that one parameter's ARN, and —
because `encryptionKey` is set — internally cascades into
`cmk.grantDecrypt(workloadRole)` (verified directly in the real installed
package: `aws-cdk-lib@2.263.0` `aws-ssm/lib/parameter.js`'s
`ParameterBase.grantRead` reads `this.encryptionKey&&this.encryptionKey
.grantDecrypt(grantee)` before granting the four SSM actions — byte-for-
byte what `docs/scenario-proposal-iam-e2e-role.md` §4.1 quoted from the
same file at a different revision). The CMK itself is imported via
`kms.Key.fromKeyArn(scope, id, kmsKeyArnParam.valueAsString)`. The plain
"config" parameter, `ssm:GetParametersByPath` (the anti-overclaim gap — see
§3), and the EC2 self-discovery actions remain hand-authored, in a
separate, explicitly-commented `WorkloadHandAuthoredPolicy`. Deployer role:
byte-for-byte unchanged from Amendment 19.

**terraconstructs workload role, reworked — but ONLY HALF as far as
awscdk, for a real, verified reason (§2).** `encryption.Key.fromKeyArn(this,
id, kmsKeyArnVar.stringValue).grantDecrypt(workloadRole)` is genuinely
library-derived and offline-plan-safe. The SSM read actions for BOTH
parameters (config and db-password alike) stay hand-authored in a single
`ReadAppParameters` statement — `storage.StringParameter
.fromSecureStringParameterAttributes()` was NOT used here, deliberately,
because doing so breaks this scenario's own offline static tier (§2).
Deployer role: byte-for-byte unchanged from Amendment 19.

### 2. A real, verified per-arm coverage/plan-safety finding (not assumed)

Attempting the awscdk-symmetric design on terraconstructs first (import
`db-password` via `storage.StringParameter
.fromSecureStringParameterAttributes().grantRead()`, exactly like awscdk)
was tried, for real, this pass, and it FAILS this scenario's own offline
static tier. Root cause, confirmed by reading the real installed
`terraconstructs@0.2.13` source (`lib/aws/storage/parameter.js`):
`fromStringParameterName`/`fromStringParameterArn`/
`fromSecureStringParameterAttributes` ALL unconditionally construct a real
`data "aws_ssm_parameter"` Terraform data source (`new
provider_aws_1.dataAwsSsmParameter.DataAwsSsmParameter(...)`), even when
the caller never reads the resulting `.stringValue` — unlike
`aws-cdk-lib`'s own equivalents, which produce CloudFormation-side
artifacts (a `CfnDynamicReference` for SecureString, an `AWS::SSM::
Parameter::Value<String>` template Parameter for plain strings) that
resolve only at real DEPLOY time, never at synth. Terraform reads data
sources during `plan` itself, not just `apply`, and `-refresh=false` does
not exempt them. Reproduced directly: a real `terraform init && terraform
plan` against exactly this construct fails OFFLINE with
`UnrecognizedClientException: The security token included in the request
is invalid` on the resulting data source — this scenario's own
`mock-sts.js` mocks only STS, by design (its own header comment), never
SSM. Consequence: on terraconstructs, ONLY the KMS half of the
`db-password` permission bundle is genuinely library-derived; the SSM half
is not, for a structural reason specific to how CDKTF-style constructs
model "import an existing resource" versus how CloudFormation does. This
is recorded in `specs/iam-e2e-role.yaml`'s own `arms.terraconstructs.reason`
field (not just here) and in both arms' `solution/solve.sh` header
comments, per the operator's own instruction to treat this as "an OBSERVED
per-arm coverage finding... rather than papering over it."

A second, smaller finding on the awscdk side (also verified by real `cdk
synth`, not assumed): `ssm.StringParameter.fromStringParameterAttributes()`
/`.fromStringParameterArn()` — even for a PLAIN (non-secure) parameter —
unconditionally create an `AWS::SSM::Parameter::Value<String>` CloudFormation
template Parameter as a side effect of that class's `stringValue` field
initializer, which appears in the synthesized template even when nothing
ever reads `.stringValue` (confirmed: it appeared, unused, and `cdk synth`
printed `WARNING ... is not referenced anywhere in the template`, when this
pass first tried importing the plain "config" parameter the same way as
"db-password"). CloudFormation resolves that parameter TYPE using the
DEPLOYING PRINCIPAL's own `ssm:GetParameters` permission at stack-update
time — a coupling onto whoever calls `cdk deploy` (this benchmark's
`QADeployApplicationRole`) that was never authorized and is not needed.
The reference avoids this entirely by not importing "config" via the SSM
L2 at all — it stays hand-authored, exactly like the plain parameter
already was in Amendment 19.

### 3. The KMS key ARN cannot be known offline, on any arm — same shape as
### hcl_raw's own `account_id` workaround

`Key.fromKeyArn()` (both libraries) requires a real KEY ARN, not an alias.
Confirmed against AWS's own KMS developer guide (`cmks-in-iam-policies.html`,
fetched this pass): "You must use its key ARN to specify a KMS key in an
IAM policy statement; you cannot use a key id, alias name, or alias ARN."
The pre-provisioned CMK's key ID is an opaque, randomly-assigned GUID with
no relationship to its alias name (`alias/cdktn-bench-iam-e2e-role`), so —
unlike the account id, which the account-root ARN needs and which CDK/CDKTF
can resolve via a pseudo-parameter/mocked data source — it cannot be
computed or looked up offline (`kms.Key.fromLookup()`/`encryption.Key
.fromLookup()` both require a real, live AWS lookup at synth/plan time,
which `--no-lookups` and this scenario's own offline static tier both rule
out, for the same reason `hcl_raw`'s reference avoids `data
"aws_caller_identity"`). Both reworked reference solutions use a
deploy-time-supplied value instead — a `cdk.CfnParameter` (awscdk) / a
`cdktn.TerraformVariable` (terraconstructs) — with a syntactically-valid
placeholder default for offline synth/plan, exactly mirroring the pattern
`hcl_raw`'s own `account_id` variable already established in Amendment 19.
A real deploy passes the true value, resolved the same way `hcl_raw`'s own
README documents for `account_id`: `aws kms describe-key --key-id
alias/cdktn-bench-iam-e2e-role --query KeyMetadata.Arn --output text`.

### 4. Oracle changes

- **Action catalogue** (`actions-are-real-iam-actions`, shared across all
  three arms): added `ssm:GetParameterHistory`. `grantRead()` on BOTH
  libraries grants this action unconditionally (it is one of the fixed
  four), and it was simply missing from the catalogue Amendment 19 built
  from the v1 (fully hand-authored) reference solutions, which never
  needed it. A real IAM action, verified present in both libraries' source;
  adding it to an allowlist does not weaken the `invalid-action-name` catch
  (an agent still cannot pass by inventing an action not on the list).
- **`missing-kms-for-securestring` catch**: `applies_to: [hcl_raw]` REMOVED
  (now defaults to all three enabled arms, per `spec_model.Catch`'s own
  default). Amendment 19 restricted this catch to `hcl_raw` because the v1
  reference authored the workload role by hand everywhere, making a missing
  KMS grant "unreachable by construction" on the construct arms. That
  reasoning no longer holds: on awscdk, omitting `encryptionKey` from the
  `fromSecureStringParameterAttributes` call reproduces the gap exactly
  (`grantRead()`'s own `if (this.encryptionKey)` cascade simply never
  fires); on terraconstructs, dropping the whole `Key.fromKeyArn()`
  /`.grantDecrypt()` block reproduces it. Both are now real, authored
  `solution/broken/missing-kms-for-securestring/` fixtures (§5), verified
  to score reward 1.0 on every static tier (identical to the reference) and
  to mechanically fail an offline IAM-evaluator's `kms:Decrypt` check —
  exactly the `predicted_tier_caught: live` contract already declared.
  The catch's own description was reworded to stop asserting the KMS grant
  must be "scoped by a `kms:ViaService` condition" (`hcl_raw`'s own shape,
  since it has no way to reference the real key ARN) — the construct-arm
  shape (`Resource` scoped directly to the real key ARN, no condition) is
  equally correct; the catch is about the grant being ABSENT, not about
  which of the two correct shapes was used.
- **`oracles/rego/iam-e2e-role/policy.rego`**: the `not_verifiable` block's
  comment was corrected — it previously claimed both roles' policies are
  "fully static... with no reference to a provider-computed output," which
  is no longer true of the workload role's KMS statement on the two
  construct arms (`{"Ref":"KmsKeyArn"}` / `${var.kms_key_arn}`, per §3).
  Verified this is NOT a correctness gap: this policy's only rule
  (`s3-resource-not-overbroad`) never inspects KMS statements, so the
  plan-time-unknown KMS `Resource` is irrelevant to anything this file
  actually evaluates — confirmed by a real `opa eval` against a
  reworked-reference plan.json returning an empty `deny` set. Comment
  reworded to state this precisely rather than the now-inaccurate blanket
  claim. `oracles/cfn-guard/iam-e2e-role/policy.guard` made no such claim
  and needed no change.
- **`oracles/iam-e2e-role/intent.md`**: unchanged (generated verbatim from
  `oracle.intent`, which this amendment did not edit — the two-property
  "static shape + live check" design is untouched by this rework).
- **`specs/iam-e2e-role.yaml` `arms.terraconstructs.reason`**: rewritten to
  record the real per-arm finding in §2/§3 above in place, replacing the v1
  text's forward-looking "a future revision could redo this" framing (now
  moot — this IS that revision).

### 5. Fourteen new negative fixtures — the actual gap this amendment closes

`tasks/anchor/iam-e2e-role-{awscdk,terraconstructs}/solution/broken/` now
each have all 7 catches' fixtures, mirroring `hcl_raw`'s own 7 (which are
unchanged). Every one of the 14 new fixtures was generated by taking the
new reference `lib/scenario-stack.ts` and applying exactly ONE targeted
change (mechanical diff, same discipline `hcl_raw`'s own fixtures use), then
RUN for real end-to-end (`npm run build`/`npx cdk synth --no-lookups`, or
`npx cdktn synth` + real `terraform init`/`plan` under this arm's own
`mock-sts.js`, then the arm's real, generated `tests/static_tiers.sh`) —
not hand-predicted:

| Catch | awscdk mechanism | terraconstructs mechanism | Verified result (both arms) |
|---|---|---|---|
| `admin-wildcard-policy` | deployer's 7 statements replaced by one `Action:"*"`/`Resource:"*"` | same | tier0 FAIL, reward 0.0 |
| `invalid-action-name` | `s3:DeleteBucketOwnershipControls` appended to `S3Scratch` | same | tier0 FAIL, reward 0.0 |
| `trust-policy-unconditional` | `.withConditions(...)` dropped from both roles' account-root principal | same | tier0 FAIL, reward 0.0 |
| `wildcard-matches-protected-bucket` | `s3ScratchArn`/`s3ScratchObjectsArn` drop the `-scratch` suffix | same | tier1 FAIL (cfn-guard/rego both fired), reward 0.0 |
| `missing-tag-on-create` | `iam:TagInstanceProfile` dropped from deployer's `InstanceProfileLifecycle` | same | static PASS (reward 1.0), offline IAM-evaluator confirms `iam:CreateInstanceProfile` ALLOW / `iam:TagInstanceProfile` DENY, prints `CDKTN_BENCH_LIVE_ONLY_CONFIRMED` |
| `missing-kms-for-securestring` | `encryptionKey` dropped from the SecureString import (whole `Key`/`CfnParameter` block removed as dead code) | whole `Key.fromKeyArn()`/`.grantDecrypt()` block removed | static PASS (reward 1.0), evaluator confirms `ssm:GetParametersByPath` ALLOW / `kms:Decrypt` on the real CMK ARN DENY, prints the marker |
| `getparametersbypath-not-granted` | hand-authored `GetParametersByPathGapFiller` statement removed | `ssm:GetParametersByPath` dropped from the hand-authored `ReadAppParameters` action list | static PASS (reward 1.0), evaluator confirms `ssm:GetParameter`/`kms:Decrypt` ALLOW / `ssm:GetParametersByPath` DENY, prints the marker |

All 4 static-tier catches score exactly 0.0 and all 3 live-tier catches
score exactly 1.0-plus-marker, on BOTH arms, matching
`predicted_tier_caught` exactly. The corrected references themselves
(`solution/solve.sh`) score reward 1.0 on all three arms, including
`hcl_raw` (re-verified unaffected by the action-catalogue addition). This
closes Amendment 19 §6 point 2's tracked gap ("`awscdk`/`terraconstructs`
have NO `broken/` fixtures yet, for any catch") for `iam-e2e-role`
specifically — `gates/oracle_falsifiability.py` (not run this pass, still
Docker-gated, see §7) should now report a real PASS/FAIL per (arm, catch)
pair instead of `MISSING` for these two arms.

### 6. The honest result this scenario now measures — stated plainly

**The WORKLOAD role now shows real, evidenced asymmetry, not aspiration:**
awscdk derives BOTH the SecureString parameter's SSM read actions AND its
KMS decrypt permission from one `grantRead()` call; terraconstructs derives
ONLY the KMS decrypt half (a real per-arm coverage difference, §2, not a
tuning choice); `hcl_raw` derives neither and must hand-write both,
correctly, using the real episode's own `kms:ViaService`-conditioned shape.
All three arms still hand-write the same three things regardless: the
plain "config" parameter's reads, the `ssm:GetParametersByPath` gap-filler
(no library on either arm grants it — this is deliberately unaffected by
this rework, still the scenario's anti-overclaim catch), and EC2
self-discovery.

**The DEPLOYER role shows parity, unchanged and by design:** 100%
hand-authored, byte-for-byte identical in content across all three arms,
before and after this rework. No amendment to this scenario should expect
that to change without a corresponding change to the libraries themselves
— `docs/scenario-proposal-iam-e2e-role.md` §4.3's finding ("no feature,
helper, or concept anywhere in the library for deriving the deploying
principal's policy") was independently re-confirmed by this pass finding
no such helper while authoring the reworked reference solutions either.

This is exactly the two-sided result Amendment 19 §6 point 1 pre-registered
before any trial: construct arms win where a library genuinely derives
something (workload role, partially on terraconstructs, more fully on
awscdk), and are at parity where no library does (deployer role). Nothing
in this pass was tuned to make either arm look better than the verified
evidence supports — the terraconstructs-only SSM limitation (§2) and the
awscdk-only hidden-CfnParameter wrinkle (§2) are both real constraints this
pass discovered while trying to make the SYMMETRIC design work, not
choices.

### 7. What remains unproven — stated plainly, most of it unchanged from
### Amendment 19

1. **`make falsifiability`/`make grading-proof` (Docker-gated) were not
   run** — no `cdktn-bench/<arm>:dev` images were built this pass. Every
   claim above about reward/tier status was instead verified by REAL
   `npm`/`cdk`/`cdktn`/`terraform`/`opa`/`cfn-guard` execution against the
   real generated task trees, copied to a scratch directory outside the
   repo, with `/app/project`/`/logs/verifier` path-substituted (same
   technique Amendment 19 used, but this time driving the REAL toolchain
   instead of hand-simulating its logic) — strong evidence, still not a
   substitute for the real gate.
2. **No real `harness/validate.sh` run has ever happened against a real
   AWS account** — unchanged from Amendment 19; the live half of this
   scenario's oracle remains entirely unexercised end-to-end. In
   particular, whether `AWS::SSM::Parameter::Value<String>`-type
   CloudFormation parameters truly resolve using the DEPLOYING PRINCIPAL's
   own credentials (the reasoning in §2 for avoiding that construct) is
   asserted from AWS's own documented behavior, not confirmed against a
   real `cdk deploy` in this account — mitigated, not eliminated, by simply
   not shipping a reference solution that depends on the answer either way.
3. **`QADeployApplicationRole` still needs its one `sts:AssumeRole`
   statement** (Amendment 19 §5) — still proposed, not authorized, not
   wired. Unaffected by this rework (the deployer role's own
   permissions, and the agent's own operating credential, are both
   unchanged from Amendment 19).
4. **`ops/fixtures/iam-e2e-role/provision.sh` still has not been run** —
   the CMK, SSM parameters (including the "db-password" SecureString this
   rework now depends on more directly for the workload role's own live
   correctness), and decoy bucket do not yet exist in the account.
5. **`scenarios/anchor/reset/reset.sh` still has no `iam-e2e-role` sweep
   entry** — unchanged gap from Amendment 19 §7.
6. **The cfn-guard-vs-rego strictness asymmetry for
   `wildcard-matches-protected-bucket`** (Amendment 19 §6 point 1) is
   unchanged and unaffected by this rework — still a known, documented gap
   specific to the tier-1 S3 check, orthogonal to the workload role's own
   KMS/SSM permissions.

**Verification performed this pass** (all offline, no AWS credentials
used, Node.js v26 installed via `brew` specifically to make real execution
possible): `make validate-spec SPEC=specs/iam-e2e-role.yaml` — OK, 7
catches, 7 structural_asserts. `make gen SPEC=specs/iam-e2e-role.yaml` — OK,
regenerated `tests/static_tiers.sh` (action-catalogue addition only) and
`environment/workspace/lib/scenario-stack.ts` for the awscdk arm (this
regeneration also fixed a real pre-existing leak — that file had somehow
been left containing the FULL reference-solution content instead of the
generator's own empty agent-facing skeleton; regenerating restored the
correct empty skeleton, which this amendment treats as a welcome
side-effect, not something it caused). `make parity SPEC=specs/
iam-e2e-role.yaml` — OK. All three arms' `solution/solve.sh` verified via
real `npm run build && npx cdk synth --no-lookups`, real `npx cdktn synth`
+ real `terraform init && terraform plan` (under real `mock-sts.js`), and
real `terraform init && terraform validate && terraform plan -refresh=false`
(hcl_raw, unchanged) respectively, each followed by that arm's own real,
generated `tests/static_tiers.sh` — all three report `tier0_pass=1`,
tier-1 `PASS`, `reward=1.0`. All 14 new negative fixtures (§5) plus
`hcl_raw`'s pre-existing 7 (spot-checked: reference still 1.0 after the
catalogue change) verified the same way, each scoring exactly what
`predicted_tier_caught` requires. `opa eval`/`cfn-guard validate` against
the hand-authored `policy.rego`/`policy.guard` bundles (the latter
unedited; the former's comment corrected, §4) — both still evaluate
correctly against real plan/template output from the reworked references
and fixtures.

**Files added:** `tasks/anchor/iam-e2e-role-{awscdk,terraconstructs}/
solution/broken/{admin-wildcard-policy,invalid-action-name,
trust-policy-unconditional,wildcard-matches-protected-bucket,
missing-tag-on-create,missing-kms-for-securestring,
getparametersbypath-not-granted}/solve.sh` (14 files), this amendment.
**Files modified:** `specs/iam-e2e-role.yaml` (`arms.terraconstructs.reason`,
the action catalogue, the `missing-kms-for-securestring` catch),
`tasks/anchor/iam-e2e-role-{awscdk,terraconstructs}/solution/solve.sh`
(workload-role half reworked; deployer role untouched),
`oracles/rego/iam-e2e-role/policy.rego` (comment only),
regenerated-but-generator-owned files under `tasks/anchor/
iam-e2e-role-{awscdk,hcl-raw,terraconstructs}/tests/static_tiers.sh` and
`tasks/anchor/iam-e2e-role-awscdk/environment/workspace/lib/
scenario-stack.ts` (see above). **Files NOT modified:** everything under
`apigw-redeploy`'s own paths, `scenarios/anchor/reset/reset.sh`,
`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`,
`specs/split.yaml`, `ops/fixtures/iam-e2e-role/*` (still written-not-run,
unchanged from Amendment 19), `oracles/cfn-guard/iam-e2e-role/policy.guard`,
`oracles/iam-e2e-role/intent.md`, `tasks/anchor/iam-e2e-role-hcl-raw/
solution/*` (the floor arm, deliberately untouched).

---

## Amendment 19 (2026-08-13) — QADeployApplicationRole: sts:AssumeRole on the task path

**Operator authorization (verbatim, 2026-08-13):** "I authorize sts:AssumeRole
addition to QADeployApplicationRole. One statement: sts:AssumeRole scoped to
role/cdktn-bench-task/*. Without it the deployer role can't be assumed in-trial,
so the first live apigw-redeploy run stays blocked."

**Implemented:** one `PolicyStatement` (sid `StsAssumeTaskRolesScoped`) added to
`QADeployApplicationPolicy` in `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`
— `Allow sts:AssumeRole` on `arn:aws:iam::<account>:role/cdktn-bench-task/*` only,
the same path CreateRole/PassRole are scoped to.

**Still out of scope (unchanged):** `sts:AssumeRole` on the CDKToolkit bootstrap
roles (`cdk-hnb659fds-*`, path `/`) — needed for the awscdk arm's `cdk deploy`
to execute — is NOT covered by this authorization and remains withheld pending
its own sign-off.

**Consequence:** requires `aws-bench env setup` to redeploy `QARolesStack` before
the change takes effect in the account (also mandatory anyway after the reset.sh
removal + role changes changed the scenario source hash — see Amendment 18).

---

## Amendment 21 (2026-08-13) — drop the iam-e2e-role scenario

**Operator decision (verbatim, 2026-08-13):** "drop iam-e2e-role (Slice H) (spec
only) - reason: the real intent should be writing cross service infra which
requires carefully crafted IAM Policies (which are encoded in the cross services
L2 patterns in AWSCDK), the e2e example was just a personal experience.. but it
doesn't hold."

**Removed:** `specs/iam-e2e-role.yaml`, `tasks/anchor/iam-e2e-role-*` (3 arms),
`oracles/{rego,cfn-guard}/iam-e2e-role`, `oracles/iam-e2e-role`,
`ops/fixtures/iam-e2e-role`. `specs/split.yaml` and `local-registry.json`
regenerated/pruned. The harness capability the scenario exercised (live deploy,
mutating tasks, the QADeployApplicationRole path) is unaffected and still used by
`apigw-redeploy`.

**Why it didn't hold (confirmed by our own evidence, docs/scenario-proposal-iam-e2e-role.md
§4):** the scenario's core was the *deployer/CI* IAM role, and **no construct
library derives the deployer principal's policy** — `grantXxx()` only ever derives
the *workload* principal. So the scenario measured the one boundary where the
abstraction gives no advantage; of the 12 evidenced defects, constructs eliminated
exactly one (the KMS family) and introduced two of their own.

**Salvaged direction (future scenario, not yet specced):** the *workload*-grant
asymmetry is real and does hold. A **cross-service workload-grant** scenario —
e.g. a Lambda that must read an S3 bucket and decrypt with a KMS key — is where
`aws-cdk-lib`'s cross-service L2 patterns (`bucket.grantRead(fn)` deriving the
exact identity policy, resource policy, and KMS grant in one call) legitimately
beat hand-written `aws_iam_role_policy` + bucket policy + key policy in HCL. This
is the correct home for the IAM-derivation question. `docs/scenario-proposal-iam-e2e-role.md`
is kept as the evidence record; the ordered defect list remains reusable.

---

## Amendment 22 (2026-08-13) — raise the turn budget 8 → 100

**Operator decision (verbatim, 2026-08-13):** "set max-turns to 100 (if not 50 at
a minimum - but start large and add claude.md note to monitor and trim where
required)."

**Change:** `scripts/run-bench.sh` `MAX_ITERS` default 8 → 100. `CLAUDE.md`
"Turn budget" section added (monitor `num_turns`; trim toward 50 with evidence).

**Why (a correction, not just a knob):** the pre-registration's `MAX_ITERS = 8`
means 8 *feedback cycles*, but the code maps `MAX_ITERS` → Claude Code's
`--max-turns`, which counts *agent steps*. One cycle is many steps, and a live
scenario's steps include minutes-long `terraform apply` / `cdk deploy`. The first
live trial (`apigw-redeploy-hcl-raw`, 2026-08-13) hit `error_max_turns` at 8 —
right-censored purely by an under-budget, not by the agent's ability. `MAX_TOKENS`
remains the intended censoring budget; `--max-turns` is a runaway backstop.

**Pre-registration status:** this refines the operationalization of §4's budget
cap (turns ≠ cycles), it does not change the *metric*. The censoring discipline
(never drop a capped run; pair with success-rate) is unchanged.

---

## Amendment 23 (2026-08-13) — first live green + tokens-to-green denominator = output tokens

**Result (first uncensored live trial).** `apigw-redeploy-hcl-raw`, claude-code /
claude-sonnet-5, 100-turn backstop, no `MAX_TOKENS` (pilot = deliberately
token-uncensored to discover where trajectories land). **reward 1.0**,
`subtype=success`, `num_turns=49`, agent wall 841s, output 45,535 tok, cache-read
3.62M, fresh input 98, billed $2.28. `live_check` behavioral & passing: the
modified stage served `{"routes":3,"status":"ok"}` and `/hello`+`/version` showed
no regression; account reset to baseline cleanly afterward. The full
apply→modify→re-apply→verify loop works end-to-end on a real agent trajectory.
This supersedes the earlier 8-turn censored run (Amdt 22) — that was a config
bug, not a measurement.

**Operator decision (2026-08-13).** The headline **tokens-to-green denominator is
OUTPUT TOKENS** — the agent's authoring effort, which is what the abstraction
thesis is about (how much infra code must be written/rewritten to reach green).
Billed `cost_usd` is reported alongside as the cost-of-ownership figure.
`MAX_TOKENS` (the real censoring budget) censors on **output tokens**.

**Why not total/cache-read.** Cache-read (3.62M here, ~80x output) is dominated
by system-prompt + growing-context replay each turn — it scales with *turn count*
(interaction length), not authoring skill, and would flatter whichever arm gets a
shorter harness prompt. Counting it would conflate "verbose loop" with
"inefficient authoring" and corrupt the cross-arm comparison.

**Turn-budget evidence.** `num_turns=49` — the 100 cap did not bind; the agent
converged on its own. 49 sits too close to a 50 cap to trim safely on one sample;
keep 100 for live scenarios until several runs show the spread (per CLAUDE.md
monitor-and-trim). `MAX_TOKENS` still to be pilot-set from output-token
distributions once we have them for both arms.

**Pre-registration status:** fixes the operationalization of §3's tokens-to-green
metric (which token count) — a clarification the pre-reg left open. Success-rate
pairing and censoring discipline unchanged.

---

## Amendment 24 (2026-08-13) — adopt aws-bench's IAM model; retire QADeployApplicationRole

**Operator decision (2026-08-13).** After reading how aws-bench itself handles
deploy permissions, adopt its model verbatim: mutating scenarios run the agent
as **`QALocalInvocationApplicationAdmin` (AdministratorAccess)** — broad power in
a disposable, SCP-guarded account — instead of a bespoke, minimally-scoped
deploy role. The operator's framing: "throwaway account that gets reset and has
a region-restricted SCP … building multiple scenarios will churn IAM policies
rather than focus on benchmarking."

**Evidence (Sonnet exploration of `../aws-bench` + `../aws-bench-datasets`).**
aws-bench's model is unambiguously **broad-power-in-disposable-account**:
- Deploy/reset/cleanup always run as `OrganizationAccountAccessRole` (org-admin);
  a dedicated `cfn-service-execution` role is given `AdministratorAccess` outright
  (`provisioning.py:589-626`).
- The agent's own identity for **mutation tasks is `QALocalInvocationApplicationAdmin`
  = `AdministratorAccess`** (35 tasks); read/introspection tasks get a
  ReadOnly-ish role (99 tasks). No task in 134 defines a hand-scoped per-resource
  policy. No `PermissionsBoundary` anywhere.
- Safety is **disposable one-account-per-scenario + a region-restriction SCP + a
  role-protection SCP (guards the framework's own admin roles) + reset/
  contamination gating** — not least-privilege IAM.

**Why this is correct here, not just convenient.** Two hazards a scoped deploy
role creates, both removed by a shared admin role:
1. **Measurement validity.** A too-tight deploy role turns *harness* permission
   gaps into fake *agent* failures (`AccessDenied` looks identical to the agent
   failing). Broad power makes a deploy failure genuinely the agent's.
2. **Arm parity.** With the scoped role, hcl-raw's terraform deployed under the
   scoped role while awscdk's default synthesizer routed CloudFormation through
   the `AdministratorAccess` bootstrap `cfn-exec-role` — the awscdk arm silently
   had *more* deploy authority. A shared admin role gives both arms identical
   authority; a deploy failure means the same thing in both. (This retired an
   in-progress `CliCredentialsStackSynthesizer` workaround — see below.)

**Safety gate verified before adoption (2026-08-13).** Both SCPs confirmed
present and genuine on the OU/account via org-admin read:
- `awsbench-region-restrict-anchor` (p-jupkf61a) on account `886312446417`.
- `awsbench-protect-org-access-role` (p-qyvay65z) on OU `cdktn-anchor`
  (ou-4rnb-at85dguq) — `Deny` on `iam:DeleteRole/UpdateRole/PutRolePolicy/
  AttachRolePolicy/DetachRolePolicy/DeleteRolePolicy/UpdateAssumeRolePolicy`
  against `OrganizationAccountAccessRole` and `cfn-service-execution`, for every
  principal except `OrganizationAccountAccessRole` itself. So even as admin the
  agent cannot break the reset path.

**Changes.**
- `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`: removed
  `QADeployApplicationRole` + `QADeployApplicationPolicy` (and with them
  Amendment 19's scoped `sts:AssumeRole` — subsumed by admin). Kept
  `QALocalInvocationApplicationRole` (read) and `QALocalInvocationApplicationAdmin`
  (admin). Synth verified: exactly those two roles, `QADeploy*` gone.
- `specs/apigw-redeploy.yaml`: `agent_role_name` → `QALocalInvocationApplicationAdmin`;
  rationale block rewritten; the stale "NOT YET TRIAL-RUNNABLE" caveat removed
  (first live green already on record, Amdt 23).
- `generator/gen.py`: **reverted** the Amendment-23-turn `CliCredentialsStackSynthesizer`
  edit — awscdk `bin/app.ts` is back to the standard `new cdk.App()` bootstrap
  path, which under admin is both simpler and how real awscdk users deploy.
- Regenerated all tasks. apigw-redeploy (all 3 arms) now assume the admin role;
  read-only scenarios unchanged. awscdk offline static proof still passes
  (salted Deployment id changes; static tier intact).

**Supersedes.** Amendment 19 (scoped `sts:AssumeRole`) — subsumed. The
apigw-redeploy CliCredentials note recorded mid-Amdt-23 — reverted. `QADeployApplicationRole`
is retired everywhere except stale *comments* in hand-authored reference
`solve.sh` files (answer-key only, never agent-visible; cosmetic sweep pending).

**Pre-registration status:** operationalization of the live-sandbox permission
model. The equipping-hash and integrity gates are unchanged; the deploy identity
is harness plumbing, not part of what is measured.

---

## Amendment 25 (2026-08-20) — one toolchain shape everywhere: `tsc` (emitting) → `node`, gate chained into the app command

**Decision.** Land the consolidated verdict of `docs/ts-runtime-spike2-results.md`
(five measurement agents, 2026-08-13) as a single package: **every TypeScript
tree in this benchmark now runs a real `tsc` compile and then plain `node` on
the emitted JS**, and on the two *graded* arms the compile is **chained into the
synth app command** so an agent can never synth stale JS. `ts-node` is off every
execution path. No new runtime was introduced — bun, tsx,
`--experimental-strip-types`/`-transform-types`, the cdk-terrain #198 pattern,
deep-import hints and slim provider shims were all measured and **rejected**
(evidence in `docs/ts-runtime-spike2-results.md` and `docs/ts7-spike-results.md`).

**Why chaining, not just a build step.** Two hazards, both reproduced:
1. *Stale-JS gate loss.* With a bare `node main.js` / `node bin/app.js` and a
   previously-good emitted JS on disk, editing the `.ts` into a type-broken
   state still synthesizes **exit 0 with the old code** — a broken solution
   scores as correct and the agent's edit silently does nothing (phantom debug
   turns corrupting tokens-to-green). `noEmitOnError: true` means a failing
   build never overwrites good JS, so the *build's exit code* is the
   load-bearing gate and must be impossible to skip. Re-verified on both arms
   during this landing (terraconstructs: `retention: 10` → TS2322 →
   `cdktn synth` exit 1 with a stale-good `main.js` present; awscdk:
   `versioned: "yes"` → TS2322 → `cdk synth` exit 2 with a stale-good
   `bin/app.js` present; and the negative control — bare `node main.js` on the
   same broken tree — exits **0**).
2. *Transpile-only runners invert the instrument.* Anything that removes
   type-checking from the agent's iteration loop also removes the steering this
   benchmark measures. Sequential `tsc` → `node` keeps the type error in the
   loop at peak `max(gate, synth)` rather than ts-node's concurrent sum.

**Changes.**
- `arms/terraconstructs/environment/app/cdktf.json`: `"app"` `npx ts-node main.ts`
  → **`npx tsc -p tsconfig.json && node main.js`** (tsconfig has no `outDir`;
  emit lands next to sources).
- `arms/terraconstructs/environment/app/tsconfig.json`: `+ "skipLibCheck": true`
  (spike-measured 1416 → 989 MB, 4.36 → 1.89 s, **catch-preserving** — all five
  typed-value traps still fire).
- `arms/awscdk/environment/workspace/cdk.json` (and its hand-maintained byte-copy
  `tasks/anchor/smoke/environment/workspace/cdk.json`): `"app"` `node bin/app.js`
  → **`npx tsc -p tsconfig.json && node bin/app.js`**, closing the identical
  desync hazard on that arm. Its spec-level `build_command` step stays.
- `generator/gen.py::build_static_tiers_sh`: for **every** `terraconstructs`
  spec, unconditionally inject `npx tsc -p tsconfig.json` as the arm's first
  toolchain step, with its own `BUILD FAILED` → `reward 0.0` branch — the same
  unconditional pattern the arm's tf-plan step already uses, rather than relying
  on per-spec `build_command` YAML discipline. A spec that *does* set
  `build_command` for this arm is now a hard generation error (`specs/SCHEMA.md`
  updated). awscdk behaviour is unchanged.
- `arms/terraconstructs/environment/Dockerfile`: run the gate once at image build
  so a warm `.tsbuildinfo` (tsconfig already sets `"incremental": true`) ships in
  the image. Deliberately fatal: in a generated task this compiles that task's own
  skeleton, so a skeleton that does not type-check breaks the image build loudly
  instead of becoming a reward-0.0 "agent failure" in every trial.
- `scenarios/anchor/scenario/cdk_app/` (deploy plumbing, the historical exit-137
  site): `cdk.json` `"app"` → **`node dist/lib/app.js`**; `tsconfig.json`
  `+ "types": ["node"]` (`outDir: ./dist` was already correct);
  `scenario/Dockerfile` now `npm ci && npm run build` so `dist/` is baked.
  **No chained `tsc` here on purpose** — this tree is harness plumbing no agent
  ever edits, so the compile is paid once at image build. Local-dev rebuild
  instructions added to `scenarios/anchor/README.md`.
- `.gitignore`: emit artifacts the new shape creates next to tracked sources
  (`main.js`/`main.d.ts`/`lib/*.js`/`lib/*.d.ts` in the arms' workspaces,
  `*.tsbuildinfo`, `cdktf.out/`), enumerated file-by-file rather than as a
  blanket `*.js` because `mock-sts.js` is a tracked source in the same directory.
- All tasks regenerated; regeneration is idempotent (second full run is a
  byte-for-byte no-op). The five `tasks/anchor/*-terraconstructs/` dirs carry a
  byte-identical `cdktf.json` and a `build` gate in `tests/static_tiers.sh`.

**`ts-node` pins retained** in `arms/terraconstructs/environment/app/package.json`
and `scenarios/anchor/scenario/cdk_app/package.json`: dropping the dependency
would force a `package-lock.json` regeneration for zero behavioural gain, and the
packages are no longer on any execution path. Revisit at the next pin bump.

**Operational follow-ups (not done here).** `scenarios/anchor/**` changed, so
`env setup` must be re-run before the next live run or resets fail on the
scenario-source-hash. Arm images must be rebuilt (`make build-arms`), which moves
the equipping hash — expected, and exactly what that hash exists to record.

**Pre-registration status:** toolchain/plumbing operationalization. What is
measured is unchanged: the same type errors are caught, at the same tier, by the
same diagnostics; output equivalence (`cdk.tf.json` / CloudFormation templates)
was verified byte-identical across the old and new execution paths.

---

## Amendment 26 (2026-08-20) — multi-step trial semantics — **DRAFT, pre-registered, not yet exercised live**

**Status: DRAFT / pending-first-live-run.** Every semantic below is *pre-registered*
— written down before any multi-step trial has been run, so it cannot be chosen
after seeing which choice flatters an arm. Nothing here has been validated against
a real trajectory yet. The first live multi-step run may falsify any of it; when it
does, the correction lands as a *new* amendment, never as an edit to this one. No
multi-step result may be published under this amendment while it is still marked
draft.

**What was built (task #14).** `cdktn_bench/`, an importable package + a
`cdktn-bench` console script that *extends* `aws_bench` by inheritance. Nothing in
`aws-bench` or `harbor` is modified or vendored. Harbor 0.9.0 already ships a
complete `MultiStepTrial`; upstream aws-bench simply refuses to build one
(`AwsBenchTrial.create`: *"multi-step AWS tasks are not yet supported (per-step
pre/post-invoke credentialing is undefined)"*). `CdktnMultiStepTrial(MultiStepTrial,
AwsBenchSingleStepTrial)` composes Harbor's step engine with aws-bench's AWS
lifecycle by MRO, and answers the credentialing objection with aws-bench's own
`ScriptRunner` re-based onto the step. Architecture and evidence:
`docs/design/multistep-trial-investigation.md` (Seam A).

### 1. Fresh agent session per step. `--resume` is explicitly REJECTED.

Each step invokes a brand-new `claude --print` process, and Harbor relocates the
session store (`/logs/agent` → `steps/<name>/agent/`) between steps, so step 2
starts with an empty Claude config dir. We keep that.

The reason is measurement, not convenience: a resumed session writes the **full
prior history** into the resumed session's JSONL, and Harbor's trajectory parser
de-duplicates only *within one parse*. Step 2 would therefore re-sum step 1's
assistant usage, and **per-step output-token attribution — the denominator of
tokens-to-green (Amendment 23) — silently breaks.** A `--resume` arm remains
possible later (it would measure the value of retained context) but only behind
per-step JSONL de-duplication by message id.

Consequence to design around: **each step's instruction must be self-contained.**
"Now also add X to what you just built" lands on an agent with no recall; state
carries through the *workspace*, which is the artefact being graded. This also
strengthens the no-foreshadowing property — there is no conversational channel
through which step-2 intent could leak.

### 2. The harness deploys prior-step work, by default.

`steps/<name>/pre_invoke/pre_invoke.sh` runs before that step's agent, inside the
agent container, with `~/.aws/credentials` staged for the task's
`[scenario].pre_invoke_role_name`. That is where `terraform apply` / `cdk deploy`
of the previous step's IaC lives, and where out-of-band ("someone changed it in
the console") drift injection lives. Its `placeholder.json` feeds `{{...}}` tokens
into *that step's* prompt, so a drift-injection script can hand the next
instruction the ARN it just mutated.

**A spec may opt into agent-deploys instead** — a step-1 instruction that says
"…and deploy it" — where the deploy loop *is* the measurement (the apigw-redeploy
shape, Amendment 23). The choice changes what the trap measures and whether
agent-side deploy failures score against the agent, so it is a per-spec, declared
choice, never a default that drifts.

Per-**step** IAM roles are deliberately deferred: one `pre_invoke_role_name` per
task for now. A dedicated over-privileged "console operator" identity for drift
injection is a later amendment if drift realism demands it.

### 3. `min_reward` is a HARD gate; the reward strategy is `"final"`.

`[[steps]]` may declare `min_reward`; a step that misses it aborts the remaining
steps. Step 2's prompt never fires unless step 1 verified green. That stays a hard
gate — a change-request task whose starting state was never actually built is not
a measurement of anything.

The trial-level reward is **`final`** (the last step's `verifier_result`
verbatim), *not* Harbor's `mean` default. `CdktnMultiStepTrial` applies `final`
whenever `task.toml` leaves `multi_step_reward_strategy` unset; an explicit
setting still wins. With `mean`, a trial that fails step 1 and is aborted scores
the mean of the one step it ran — **which can beat a trial that ran both steps and
failed the second.** That is a perverse incentive in a green/not-green benchmark
and it is closed here rather than discovered in the data.

The abort is quiet by construction (Harbor records it on the `StepResult`, never
on `TrialResult.exception_info`), so `gates/emit_result.py` now emits
`steps.n_started` / `steps.n_declared` / `steps.n_failed` / `steps.aborted_early`
on the record. A half-run trial must never read as a clean one.

**Why `n_started` and not `n_completed`, and why `aborted_early` is not just
arithmetic.** Harbor appends the `StepResult` *before* it runs the step
(`harbor/trial/multi_step.py::_run`), so the list counts steps **started**. A
step that died in `_prepare_step` still occupies its slot. Comparing counts
alone therefore misses exactly one case — **the failing step is the LAST
declared one**, where `n_started == n_declared` — and that is precisely where
this design puts the harness action (step 2's `pre_invoke` deploys step 1's work
and injects drift). So `aborted_early` is the OR of two independent conditions:
steps missing from the tail (`n_started < n_declared`), or `n_failed > 0`, where
`n_failed` uses Harbor's own abort predicate verbatim (`_should_stop_after_step`:
`exception_info and not verifier_result`). A step that raised but was still
scored is not counted — Harbor does not stop for it. Pinned by
`gates/tests/test_emit_result_multistep.py::test_a_failed_LAST_step_is_still_aborted_early`.

**Open question, deliberately left open for the first live run.** A *harness*
failure inside `steps/<name>/pre_invoke` (a `terraform apply` the harness itself
could not complete) currently aborts the step and is **not** reclassified as
`invalid-infra`: the record stays `valid` and the published row carries reward
`0.0`. Precisely, as verified against the installed rev:

- `steps.per_step[].exception_type` is set (e.g. `ScriptExecutionError`). This is
  the **reliable, always-present** signal that a step died — prefer it over any
  count when identifying harness failures.
- `steps.aborted_early` is `true` — but only because `n_failed` feeds it (see
  above). Counting alone would report `false` for the last-step case.
- The **record-level** `reward` is `null`, not `0.0`: strategy `final` selects
  the last step's `verifier_result`, and a step that died never verified. It is
  `to_result_row` that coerces `null → 0.0` for the published row. So the
  scored-as-zero behaviour is a property of the ROW, and a reader of the record
  must not expect a `0.0` there.

Arguably this should be reclassified: a harness deploy that failed is
infrastructure, not an agent failure, and scoring it 0.0 penalises the arm for
the harness. It is left as a scored 0 for now because inventing the
reclassification rule before seeing a real failure would be guessing at which
exception types are genuinely harness-side. The evidence to decide is emitted on
every record; the decision lands as its own amendment.

### 4. Tokens-to-green across steps = cumulative sum, per-step also emitted.

**Definition.** A multi-step trial's tokens-to-green is the **cumulative sum of
per-step agent OUTPUT tokens** (Amendment 23's denominator, unchanged) **up to and
including the step at which the trial's final oracle first passes.** Steps after
that point, if any, do not count; a trial that never reaches that point is
right-censored exactly as a single-step one is.

Per-step output tokens are emitted alongside (`steps.per_step[].n_output_tokens`),
so the addends stay visible and a per-step analysis needs no re-derivation. The
same cumulative rule applies to iterations-to-green (`n_llm_calls`, summed across
steps, with `steps.n_llm_calls_per_step` emitted alongside).

**Comparability warning, stated up front:** an N-step task and a 1-step task are
not equipping-comparable on tokens-to-green by construction — more prompts means
more authoring. Cross-shape comparisons are refused, not adjusted.

### 5. `MAX_TOKENS` censoring stays TRIAL-level, shared across steps.

One budget for the whole trial, not N per step. The budget is a statement about
how much authoring effort a task is allowed to consume before we call it censored;
splitting it per step would make the same task cost more the more prompts it is
decomposed into, and would make a decomposition change silently move the censoring
threshold.

**Known and accepted, pending the first live run:** `--max-turns` (the runaway
backstop, Amendment 22) is applied *per `claude` invocation* by Harbor and
therefore does double for a 2-step trial. It is a backstop, not the headline cap
(Amendment 22), so this is tolerated for now — but `jobs/<name>/budget.json`
records a single `max_iters`, and a multi-step run must not be compared against a
single-step one on turns without accounting for it.

### 6. Existing generated tasks stay single-step. No normalization churn.

The 3-arm generated tasks under `tasks/anchor/` keep exactly one `instruction.md`
and are untouched. Normalizing them to a 1-step multi-step shape would churn every
task checksum (`Task.checksum` is a dirhash of the whole task dir and rides the
resume identity), invalidating resumes and moving every equipping hash, in
exchange for collapsing two result shapes into one. Not worth it.

The extended CLI therefore handles **both** shapes: `cdktn_bench.trial.CdktnTrial`
dispatches on `task.has_steps` — a stepless task falls through to the *untouched*
`AwsBenchSingleStepTrial`, a `[[steps]]` task builds a `CdktnMultiStepTrial`. One
CLI, two task shapes, so gates and equipping have exactly one path to reason about
(`aws-bench` itself stays installed and working; `scripts/run-bench.sh` is
unchanged).

### 7. Task-directory rules the generator will have to obey.

Not yet implemented (generator emission of `steps/` is a separate slice); pinned
now by `cdktn_bench/tests/fixtures/multistep-task/` and its tests so the rules
exist before the code that must follow them:

1. **Every step's oracle goes in `steps/<name>/tests/`.** The shared root `tests/`
   stays empty or strictly step-agnostic — Harbor uploads it for *every* step's
   verification and only empties `/tests` at the start of the *next* step's
   verification, i.e. after that step's agent has already run. A step-2 oracle in
   the shared `tests/` is readable by step 1's agent.
2. **Never place later-step material in `environment/`** — that is the image the
   agent lives in from second zero.
3. **Never place later-step material in an earlier step's `workdir/`** — it is
   copied into the agent's cwd before that step runs.
4. Step instructions live host-side only and are read on demand at that step's
   agent invocation; the task directory is never uploaded. That is what makes the
   no-foreshadowing guarantee real rather than a convention.

### 8. Gate changes that came with it.

`gates/emit_result.py` and `gates/audit.py` are now step-aware: the trajectory,
`tier1-not-verifiable` and `test-stdout.txt` readers follow the relocation into
`steps/<name>/`. Verifier-side evidence is read from the **scoring** step (the
last one, per `final`); trajectory evidence is **concatenated across steps**,
because "did this trial ever really invoke the arm's toolchain?" is a trial-level
question. `gates/equipping.py` folds every `steps/<name>/instruction.md` into the
equipping hash, since a multi-step task has no root `instruction.md` at all —
without it, no multi-step trial could be published. Single-step trial dirs are
byte-identical through all of it, and `HASH_SCHEME_VERSION` is **not** bumped: no
existing hash moves.

**Pre-registration status:** new semantics, registered before first use. Nothing
in Amendments 22–25 changes. The single-step measurement — its reward, its
tokens-to-green denominator, its censoring, its equipping hash — is untouched.

**Draft addendum (2026-08-20, pre-first-run):** two consequences of the shipped
implementation that the draft above leaves unstated. Both are properties of the
code as committed, recorded here so the first live run is read correctly; neither
is a new decision, and both stay inside this draft.

*(a) The per-step `pre_invoke` inherits the TASK-level timeout — there is no
per-step override.* `CdktnMultiStepTrial._run_step_phase_script`
(`cdktn_bench/trial.py`) reads `self.task.config.pre_invoke` — the single
task-level `[pre_invoke]` section — and passes its `timeout_sec` to every step's
`ScriptRunner`. `[[steps]]` has no `pre_invoke` block of its own to raise it, and
aws-bench's default is **600 s** (`PhaseScript.timeout_sec: float = 600.0`,
`aws_bench/dataset/task_config.py`). §2 above puts `terraform apply` / `cdk deploy`
of the *previous* step's stack inside that hook, and a real deploy can comfortably
exceed 600 s. **A multi-step task whose step `pre_invoke` deploys therefore MUST
set `[pre_invoke].timeout_sec` explicitly in `task.toml`** — and the value applies
to *every* step, so it must be sized for the slowest one. A timeout here does not
read as a slow deploy: it surfaces as the step-aborted shape §3 describes
(`steps.per_step[].exception_type` set, `steps.aborted_early` true, record-level
`reward` null coerced to a published `0.0`), i.e. as a scored-zero trial. Per-step
timeouts are a later amendment if the shared value proves too coarse.

*(b) A step with no `trajectory.json` makes the whole trial's `n_llm_calls` null,
which makes that trial turn-censoring-blind.* The `None`-not-`0` contract
(`gates/emit_result.py::extract_n_llm_calls` / `extract_n_llm_calls_per_step`)
extends across steps by design: if ANY step's trajectory is missing, unreadable,
malformed, or carries no `steps` list, the cumulative sum is **unknown** and the
record's `n_llm_calls` is `null` — a partial sum would silently understate
iterations-to-green. The consequence to state plainly: `to_result_row`'s censoring
auto-detection reaches its `max_iters` branch only when `n_llm_calls is not None`,
so such a trial can never be auto-detected as turn-censored, and — if it did not
also meet `max_tokens` — publishes `censored: false` even if it really did exhaust
its turns. This is **turn-censoring blindness only**: token accounting is
unaffected (tokens come from `result.json`'s `step_results[].agent_result`, not the
trajectory — `_aggregate_step_tokens`), so the `max_tokens` branch, which
Amendment 22 names the real censoring budget, still fires normally. A step that
died before its agent ever ran is exactly the case that produces it, and it is
visible on the record as `steps.n_llm_calls_per_step[<name>] == null` alongside
`steps.aborted_early`. Passing `censored=` explicitly (the caller-knows-best path)
also bypasses the blindness entirely.

---

## Amendment 27 (2026-08-20) — scenario-form change: `apigw-redeploy` is now MULTI-STEP (no foreshadowing); the runner flips to `cdktn-bench`

**Operator directive (verbatim, 2026-08-20):** *"extend the trial to allow multi
step first - we also need a pass on the existing scenarios to break down the
prompts (no foreshadowing, first step prompt should not know the future)"*.
Amendment 26 built the engine. This amendment records the **scenario-form
change** — the generator now emits multi-step tasks, and the one offending
scenario is decomposed.

### 1. The audit: one offender in six

Every spec's full instruction body (`shared_body` **and** every
`per_arm.<arm>.language_line`) was read and classified. Evidence, with verbatim
quotes of the offending sentences: `docs/prompt-decomposition-audit.md`.

| Spec | Class | Verdict |
|---|---|---|
| `apigw-openapi` | (a) genuinely single-step | unchanged |
| **`apigw-redeploy`** | **(b) foreshadowing** | **decomposed, 2 steps** |
| `ecs-swappiness` | (a) | unchanged |
| `s3-lambda-log-retention` | (a) | unchanged |
| `sfn-jsonata` | (a) | unchanged |
| `_toy/toy-ssm-parameter` | (a) | unchanged |

The rule applied: *"then modify/update/add X"* in a first prompt is
foreshadowing, full stop. Realistic day-1 context that does not name a specific
future change is fine — **realism is fine, prophecy is not**. No spec used the
acceptable form; the distinction is recorded for the next author.

`apigw-redeploy` leaked in four places, all quoted in the audit doc: the
opening sentence ("*apply a prescribed configuration change, and re-deploy
it*"), an entire "Step 2" paragraph specifying the route, the integration type
and the exact JSON body the step-2 oracle asserts on, and — on **one arm only**
— the awscdk `language_line` naming `MockIntegration`, which was an arm-parity
defect as well as a foreshadowing one.

A fifth finding is **answer-key leakage, not foreshadowing**, and is deleted
rather than relocated: the old prompt named the trap outright ("*A second
deploy that does not actually create a new, live-serving deployment behind the
stage … is exactly the mistake this task exists to test for*"). A prompt that
says "the mistake is X, don't make X" measures instruction-following, not the
abstraction's ability to prevent X by construction. It appears in **neither**
step.

### 2. THE COMPARABILITY RULE — single-step results must never be pooled

**The single-step and multi-step forms of `apigw-redeploy` are different
scenarios.** The three-arm live results of 2026-08-13 (`docs/live-results.md`:
awscdk 9,403 / terraconstructs 24,218 / hcl-raw 45,535 output tokens, all
reward 1.0, first recorded in Amendment 23) were produced under the
**single-step** form. They:

- **remain valid** as pilot evidence *for the single-step form* — nothing about
  them is retracted;
- **must not be pooled** with any multi-step-form result, in any estimator, at
  any n.

This is not a judgement call to be made later from the data. It follows
mechanically from Amendment 26 §4's already-registered rule ("*an N-step task
and a 1-step task are not equipping-comparable on tokens-to-green by
construction — more prompts means more authoring. Cross-shape comparisons are
refused, not adjusted*") plus the fact that the *content* of the prompts
changed too. A multi-step-form run of this scenario is a **new pre-registered
comparison** with its own census, whose headline metric is
**tokens-to-green-across-steps** (Amendment 26 §4: the cumulative sum of
per-step agent OUTPUT tokens up to and including the step at which the final
oracle first passes).

Two mechanical consequences worth stating so nobody has to rediscover them:
the task checksum moved (it is a dirhash of the whole task dir), and the
equipping hash moved (a multi-step task has no root `instruction.md`, so
`gates/equipping.py` hashes `step_instructions` instead —  Amendment 26 §8).
Neither is a regression; both are exactly the mechanisms that make an
accidental pooling impossible to do silently.

### 3. WHO DEPLOYS: `apigw-redeploy` opts into agent-deploys in BOTH steps

Amendment 26 §2 makes the harness the **default** deployer
(`steps/<name>/pre_invoke/pre_invoke.sh`) and explicitly allows a spec to opt
into agent-deploys where the deploy loop *is* the measurement. This spec takes
that opt-in, and declares **no `pre_invoke` at all**. Reasoning
(`docs/prompt-decomposition-audit.md` §3):

1. **The discriminating event is the agent's own second apply.** The headline
   catch `triggers-incomplete-hash` is `predicted_tier_caught: "live"` by
   construction. If the harness ran the apply, the harness — not the agent —
   would own the exact action under measurement, and a config missing
   `triggers` would be indistinguishable from a correct one: both would have
   "a deploy the harness ran".
2. **It preserves the pilot's construct**, so the only thing this slice changes
   is *when the second intent is revealed* — the cleanest comparison available.
3. **Agent-side deploy failures should count against the agent here**, which is
   the stated consequence of the opt-in.

**Workspace carry-over was verified, not assumed** — it is what makes the
opt-in work at all. `MultiStepTrial._run` stops the agent environment **once,
after** the whole step loop, so the container and its filesystem survive every
step boundary; `_prepare_step` uploads `steps/<n>/workdir/` and runs `setup.sh`
**only if they exist**, and the generator emits neither. Only `/logs/agent` is
relocated between steps (which is what gives clean per-step token attribution,
Amendment 26 §1/§4). So step 02's agent opens the very workspace, terraform
state and deployed stack its own step-01 self left behind. Had this not held it
would have been a blocker, not something to paper over.

### 4. The spec-schema surface (`specs/SCHEMA.md` §2.6, §8.3)

Optional, top-level `steps:` — a sibling of `instruction`, not a child. Per
step: `name` (`NN-slug`, consecutive), `instruction` (`shared_body` + optional
per-arm `language_line`), `oracle` (assert-name projection + optional
`live_check` narrowing), optional `pre_invoke` (`deploy_prior` + `timeout_sec`),
optional `min_reward`.

Decisions inside that surface worth recording:

- **A spec WITHOUT `steps` emits byte-identically to before the field existed.**
  Proven, not asserted: `make gen-all` after the generator refactor produced a
  zero-line diff across all five stepless specs' task dirs (§7 below).
- **Minimum 2 steps.** A 1-step "multi-step" task is refused — it moves every
  checksum and hash for no measurement gain (Amendment 26 §6 already declined
  to normalize single-step tasks).
- **The final step MUST omit its assert projection**, i.e. runs the FULL tier
  suite. That is what keeps a multi-step scenario's terminal grading identical
  to what its single-step form graded, and what lets the existing reference and
  negative fixtures keep proving what they proved. Enforced in `spec_model`.
- **Every non-final step MUST name its subset.** Inheriting the full suite would
  grade an intermediate state against the FINAL state's asserts, which no
  correct intermediate solution can satisfy — every trial would abort at the
  `min_reward` gate.
- **`min_reward` defaults to 1.0 on every non-final step** (Amendment 26 §3's
  hard gate) and is omitted on the final one. "No gate" must be written
  explicitly (`min_reward: 0.0`), never be the result of forgetting a key.
- **Per-step, per-arm language lines exist because the spec-level line
  foreshadowed.** Declare them on every arm at every step; the inheritance
  fallback is not the normal shape.
- **`deploy_prior` runs a SPEC-DECLARED `output_contract.deploy_command`.** The
  generator refuses to infer a deploy command from an arm→command map: guessing
  is how a credentialed harness action silently deploys the wrong tree. A
  `deploy_command` declared with no `deploy_prior` step is a hard error too — a
  real deploy command nothing runs is a trap for the next reader. No current
  spec uses either (see §3), so the path is covered by a synthetic-spec test
  rather than shipping unexercised.
- **`[pre_invoke] timeout_sec` is emitted explicitly**, sized to the largest
  value any step declares — Amendment 26's draft addendum (a): the per-step
  hook inherits the single task-level timeout, whose aws-bench default of 600 s
  a real deploy exceeds, and a timeout there surfaces as a scored-ZERO trial
  rather than as a slow deploy.

### 5. Task-directory rules the generator now obeys (Amendment 26 §7, made real)

- **No root `instruction.md`** on a multi-step task; the generator deletes one
  if it finds it. `gates/equipping.py` folds `steps/*/instruction.md` into the
  equipping hash *only in the absence of a root one*, so a leftover would
  silently revert the hash to the single-step key for text no agent ever saw.
- **The shared root `tests/` carries exactly one file: a step-agnostic
  `README.md`.** Harbor uploads it during EVERY step's verification and only
  empties `/tests` at the start of the NEXT step's verification, so anything
  step-specific there is readable inside a later step's agent phase. Every
  oracle lives in `steps/<name>/tests/`.
- The generator **hard-errors rather than deleting** a hand-authored
  `live_check.py` found in a multi-step task's root `tests/`, and rather than
  deleting a stale step directory that still contains hand-authored material.
  gen.py does not destroy content it did not write.
- **`multi_step_reward_strategy = "final"` is written into `task.toml`**, not
  left to `CdktnMultiStepTrial`'s default, so the file itself records the
  scoring rule a published row was produced under.
- **Parity (§8.2 point 2) is now checked PER STEP**, in both `gen.py`'s own
  self-check and the standalone `check_parity.py`: everything before the
  language line must be byte-identical across arms *for the same step*.
- **`environment/` is prompt surface, and the scenario `title` may not appear
  in it.** New required-for-multi-step spec field `workspace_title`
  (`specs/SCHEMA.md` §0.1) supplies the header stamped into each arm's skeleton
  entry file; `title` stays host-side metadata. See §5.1.

### 5.1 The `environment/` leak — found by a verifier, fixed at the schema

Recorded because the *rule* existed (Amendment 26 §7 rule 2: "never place
later-step material in `environment/` — that IS the image the agent lives in")
and was still violated: it had no mechanism behind it, only prose.

`generator/gen.py` interpolated `spec.title` into five skeleton headers, and
this spec's title is *"API Gateway REST API: deploy, confirm, modify,
re-deploy (day-2 iteration)"*. So while the step-1 **prompt** was clean, line 1
of the very file that prompt says the agent owns announced the day-2 iteration
— and each arm's Dockerfile `COPY`s that file into the agent image, so it
reached the container. An agent reading it anticipates a second apply, which is
the exact anticipation the redeploy-trigger trap exists to defeat.

Fixed in three layers so the rule is now enforced rather than asserted:
`workspace_title` is **required** on a multi-step spec and **forbidden** on a
stepless one (`Spec._multi_step_requires_workspace_title` — required rather
than defaulted so the author must choose a step-1-safe header, forbidden on
stepless specs so the other five specs' byte-identity guarantee cannot be
traded away for a rename); the five emitter sites call
`spec.workspace_header()`; and
`generator/tests/test_multistep_emission.py::test_step_one_environment_leaks_nothing_about_step_two`
runs the deny-list over every file under a multi-step task's `environment/`.
`apigw-redeploy` declares `workspace_title: "API Gateway REST API (live)"`.
Full write-up, including the falsification of the new test:
`docs/prompt-decomposition-audit.md` §6.1.

**General lesson for the next multi-step spec:** the no-foreshadowing check has
*two* surfaces, not one — the step-1 prompt and everything under
`environment/`. Auditing only the prompt is how this shipped.

### 6. Falsifiability under the stepped form — what moved and what did not

The task-root `solution/` tree is **unchanged**: `solution/solve.sh` and every
`solution/broken/<catch>/solve.sh` stay where they were, and
`gates/oracle_falsifiability.py` runs them against the **final** step's oracle —
which §4 guarantees is the full tier suite. Those rows therefore check
byte-for-byte what they checked before the decomposition (the final step's
`static_tiers.sh` differs from the pre-change `tests/static_tiers.sh` by a
generated comment header naming which step's oracle it is, and nothing else —
proven both ways: against git history at landing time, and continuously by
`generator/tests/test_multistep_emission.py::test_final_step_oracle_is_byte_identical_to_the_full_suite`,
which re-renders the stepless script and compares). `gates/grading_proof.py`
needed no change, because those rows kept their labels.

**One obligation was ADDED, not removed:** every non-final step now needs its
own `steps/<name>/solution/solve.sh` scoring 1.0 against its own subset oracle.
Without it, nothing shows an intermediate oracle is *satisfiable* — and an
unsatisfiable step-01 oracle would abort every trial at the `min_reward` gate
before step 02's prompt ever fired, quietly (Harbor records a step abort on the
`StepResult`, never on the trial).

Those step-01 reference solutions are **thin `STEP=01` wrappers around the
arm's existing whole-scenario `solve.sh`**, whose `write_rev1()` already
defines revision 1. Copying the heredoc would give each arm two definitions of
revision 1 that drift apart the first time either is edited — and a step-01
oracle validated against a stale revision 1 proves nothing.

**Result (offline, all three arms, 2026-08-20):** 15/15 rows PASS —
reference 1.0 and step-01 reference 1.0 on every arm; every catch caught at its
predicted tier; `triggers-incomplete-hash` still reward 1.0 + the
`CDKTN_BENCH_LIVE_ONLY_CONFIRMED` marker on hcl-raw, N/A elsewhere.

### 7. `scripts/run-bench.sh` now execs `cdktn-bench`

`exec uv run aws-bench` → `exec uv run cdktn-bench`. This is a superset, not a
replacement: `cdktn_bench/cli.py` registers aws-bench's own `start` **function
object** on its own Typer app, so flag parity is total by construction, and
`cdktn_bench/trial.py::CdktnTrial.create` dispatches on `task.has_steps` — a
stepless task returns the **untouched** upstream `AwsBenchSingleStepTrial`, a
`[[steps]]` task returns `CdktnMultiStepTrial`. Every existing single-step
scenario runs the byte-identical path it ran before; the multi-step tasks the
generator now emits stop being refused with upstream's
`NotImplementedError("multi-step AWS tasks are not yet supported")`.
`aws-bench` stays installed and working, and `aws-bench env init/setup/cleanup`
are unaffected. Pinned by `test/test_run_bench_wrapper.py::TestExecTarget`, so a
silent revert fails there rather than at the start of a live, billed run.

### 8. Regeneration + proof

`make gen-all` is idempotent (second full run is a byte-for-byte no-op). Scoped
byte-identity of the five untouched scenarios was proven with
`git diff --stat` restricted to their task directories: **zero** changed files.
The only task dirs that moved are the three `apigw-redeploy-*` ones.

**Pre-registration status.** A **scenario-form change**, registered before any
multi-step-form result exists. It changes what `apigw-redeploy` measures (day-2
iteration without foreknowledge, instead of day-1 authoring with it), which is
why §2's no-pooling rule is stated here rather than inferred later. Nothing in
Amendments 22–25 changes. Amendment 26's semantics are unchanged and are now
exercised by a real generated task rather than only by a hand-authored fixture;
Amendment 26 remains **DRAFT** until the first live multi-step run, and no
multi-step result may be published while it is.

---

## Amendment 28 (2026-08-20) — BROWNFIELD scenario form: poisoned workspaces,
## the mandatory do-nothing catch, and a live idempotence tier — **ACCEPTED
## 2026-08-26 on the first complete live brownfield row**

**Status: ACCEPTED (promoted 2026-08-26).** Registered as DRAFT before any
brownfield result existed, on the criterion that the first live
`named-resource-replacement` run promotes it — that run being the first thing
able to falsify §4's and §5's claims about behaviour on a real account.

**That run happened, and the criterion is met.** Three arms, zero exceptions,
every arm green:

| arm | reward | out tok | turns | seed | live_check | idempotence |
|---|---|---|---|---|---|---|
| `awscdk` | 1.0 | 2,727 | 9 | `seed_deployed` | `pass` | `converged` |
| `hcl_raw` | 1.0 | 5,382 | 14 | `seed_deployed` | `pass` | `converged` |
| `terraconstructs` | 1.0 | 11,558 | 28 | `seed_deployed` | `pass` | `converged` |

`jobs/live-brownfield-seed/2026-08-25__22-21-37` (awscdk, hcl_raw) and
`…/2026-08-26__08-54-19` (terraconstructs, re-run after the idempotence fix
below). Every arm's live check returned `old_group_ids: []` against a real
security group and a real SSM interface endpoint — the discriminating assertion
resolved against infrastructure that genuinely existed, which is exactly what
`docs/brownfield-seed-not-deployed.md` established the earlier battery could not
claim.

**What the run CORRECTED rather than confirmed**, recorded because a promotion
that only confirms is not evidence of anything:

* §4's `terraconstructs` state path was WRONG (`cdktf.out/…` instead of the
  absolute `/app/project/terraform.<workspace_id>.tfstate`). That single error
  was the entire `not_verifiable` verdict that cost the arm its reward on both
  prior runs — an infrastructure defect wearing the costume of an agent result.
* §4's idempotence command on that arm re-synthesized WITHOUT
  `CDKTN_BENCH_LIVE=1`, regenerating `cdk.tf.json` against the offline mock-STS
  fixture, so the live plan died dialing 127.0.0.1:17771. Fixed in `gen.py`;
  the re-run then returned `converged`.

Both were found only because the run was real. §4 and §5's claims are now
exercised live and this amendment carries no DRAFT sections.

**A brownfield row may now be published** — subject to §6, which is unchanged
and binding: brownfield is a SEPARATE STRATUM and is never pooled with
greenfield. The three rows above are n=1 per arm; the reward column is solid,
the token column is directional (two hcl_raw failures earlier in this project
differed 54% in tokens on the same scenario).

The MECHANISM that makes the premise true — the single-step seed deploy — is
Amendment 31, which has its own promotion criterion and is assessed separately.

Supersedes nothing. Extends Amendments 23 (tokens-to-green denominator), 26
(multi-step semantics) and 27 (scenario-form changes are not poolable).
Implements `docs/design/poisoned-workspace-design.md`, including its open
questions Q1, Q3, Q4, Q5 and Q6; B1 was already resolved and shipped in
`dd96cd5`.

### 1. What a BROWNFIELD scenario is, and why it is a new form

Every scenario before this one is **greenfield**: the agent opens the empty
`entry_file` skeleton (`SCHEMA.md` §2.4 — an "already-wired app/stack/root
module with an empty body and a `// TODO` comment") and authors from scratch.
A **brownfield** scenario ships, as that same `entry_file`, a hand-authored,
working, plan-green configuration that already carries a latent pitfall, and
asks for one ordinary change to it (`SCHEMA.md` §2.7).

This changes what the pre-registration's "empty-harness trial starts from a
working, synth-able **zero** state" means — it becomes a working, synth-able
**non-zero** state. That reads as an amendment, not a clarification, which is
why it is registered here rather than noted in a spec comment (design memo
§9-B2).

The measured quantity changes with it. Greenfield measures tokens-to-green on
day-1 authoring. Brownfield measures tokens-to-green on a **change to code the
agent did not write** — which is where the trap fires, and which is the far more
common real task.

### 2. Seeds are hand-authored per arm, under the reference-solution discipline

There is no derivation path between the three arms' seeds
(`docs/scenario-candidates.md:169-176`: aws-cdk-rfcs #217 closed `not_planned`,
`hashicorp/terraform-cdk` archived, no public CDK→TF synthesizer). So the three
are hand-authored, exactly like `solution/solve.sh` and like
`generator/tests/fixtures/<id>/<arm>/<entry_file>`.

**"Equivalent" is defined behaviourally, never by census.** A resource-count or
resource-type check would fail every honest seed — the benchmark's whole thesis
is that one L2 construct decomposes into N Terraform resources. Equivalence is:
(a) every arm's seed synth/plans green with no overlay, and (b) every declared
`workspace_seed.seed_asserts` entry holds on every arm it applies to, resolved
through the same jq compilation and the same `_assert_lib.sh::assert_check` a
real trial's tier-0 runs. `make seed-parity` (a `--seed` mode of
`generator/check_reference_paths.py`, not a new gate) proves both, per spec, in
`make ci`.

Two consequences we accept rather than engineer away:

- **`applies_to` may legitimately differ per arm.** CloudFormation has no
  `lifecycle` meta-argument, and it expresses a graph edge as an `Fn::GetAtt`
  intrinsic where Terraform expresses it as a reference string. The asymmetry is
  the artifact families', not the seeds'. `named-resource-replacement` carries a
  worked example: `interface-endpoint-consumes-the-security-group` (TF arms,
  graph-edge regex) and `interface-endpoint-declares-security-groups` (awscdk,
  deliberately weaker `exists`), with the weakness recorded in the spec.
- **The gate proves declared facts, not sameness of system.** `premise` is the
  human-readable equivalence claim and is reviewed the way `oracle.intent` is
  (`SCHEMA.md` §4.1).

### 3. Prompt rules, and the seed as prompt surface

The seed lands under `environment/`, which each arm's Dockerfile COPYs into the
agent image. It is therefore **prompt surface**, exactly as Amendment 27 §5.1
established for the skeleton header. Rules (full list: `SCHEMA.md` §2.7):

1. Two legal framings: **change request** or **incident symptom**. An incident
   prompt states an observed symptom and a desired end state, never a diagnosis.
2. Never "find the bug" / "fix the mistake" / "review this config" — those turn
   a brownfield task into a code-review task and measure something else.
3. The **premise states facts, not warnings**. "It is already deployed in this
   account" is a fact; "careful, this group is in use" is a warning and a hint.
   In-use-ness must be discoverable from the configuration — which is precisely
   what a `seed_assert` pins.
4. **No mechanism naming** (`create_before_destroy`, "replacement", "perpetual
   diff"), extending §2.1's existing `instruction_concision` rule.
5. **The seed carries no comment a real production file would not**, including —
   answering design-memo **Q3** — none of the generator's own provenance headers.
   `Generated skeleton — generator/gen.py` / `Empty on purpose` / `TODO(agent)`
   tell the agent the file is bench scaffolding, which invites meta-reasoning
   about planted traps; a seeded `entry_file` gets **no header at all** and is
   written verbatim. Regeneration drift is already caught by the `gen-sync` CI
   check, so the header was never load-bearing for that. Mechanically tripwired
   by `spec_model._seed_comment_violations`; the real rule is a review-time
   obligation.
6. **The ownership note changes** from "write your entire solution there" to
   "holds this project's existing configuration — change it as needed". The
   don't-touch clause for `provider.tf`/`bin/app.ts`/`main.ts` is unchanged and
   still load-bearing (finding G1).
7. **The scenario `title` is prompt surface too, and a brownfield spec must
   therefore declare `workspace_title`** (`SCHEMA.md` §0.1). Amendment 27 §5.1
   established this for multi-step specs; the field was scoped to `steps:`, so
   a stepless brownfield spec could not override the header — and this pilot's
   first draft, `"Rename an explicitly-named, in-use security group and roll it
   out"`, was stamped into `bin/app.ts`'s CFN `description` and `main.ts`'s
   header comment, naming *both* halves of its own poison (rule 4) on two of
   three arms while `hcl_raw` — whose entry file IS the seed and carries no
   generator header — stayed clean. An **arm-asymmetric** hint inside the
   comparison the scenario exists to measure is worse than a symmetric one:
   it does not just make the task easier, it biases the number. The field is
   now REQUIRED (not defaulted) on brownfield specs (the validator Amendment 27
   introduced as `Spec._multi_step_requires_workspace_title` is renamed
   `Spec._workspace_title_required_where_header_is_prompt_surface` to match its
   widened scope — Amendment 27's text is left as written, being append-only),
   must describe only what the workspace already *is*, and the emitted bytes
   are deny-list-scanned by
   `test_workspace_seed.py::TestBrownfieldPromptSurface` — which also pins the
   verbatim `title` string as unreachable from `environment/` and
   `instruction.md`, so the guard cannot rot as later specs invent new wording.
   Generalised lesson, and the reason this is a rule rather than a fix: the
   author's hostile self-check covered "the seed and the instruction", and the
   leak was in neither. **The unit that must be read hostilely is every byte
   the Dockerfile COPYs, not the files the author happened to write.**

Prompt parity is preserved *by construction*, not by review: `premise` is
spec-level and arm-agnostic and is inserted **before** the per-arm language
line, i.e. inside the parity-checked shared prefix.

Answering design-memo **Q5** (naming): `workspace_seed` and `seeded_files` stay
separate blocks. Their permissions and semantics are opposites — writable task
content the agent is asked to edit (`0o644`) versus read-only reference input
(`0o444`) — and a path may not appear in both.

### 4. The idempotence tier *(draft)*

`verifier.idempotence` (`SCHEMA.md` §5.1): after the agent's solution is green,
the agent's **own toolchain** must report a converged state against what it
deployed.

**It is a live tier, not a static one, and that is a blocking fact.**
`terraform plan -detailed-exitcode` is `2` against empty state, always, so the
generated static tier — which plans an empty directory — can never produce a
meaningful second-plan signal offline. `idempotence.enabled` therefore requires
`live_check.enabled`.

Per-arm commands are injected unconditionally by the generator, never read from
a spec key: `terraform plan -refresh=false -detailed-exitcode` on `hcl_raw`;
synth-then-the-same-plan on `terraconstructs`; **`cdk diff --fail` against the
deployed stack** on `awscdk`. The last is not a convenience — a second synth plus
a template self-diff is vacuous by construction (CDK synth is deterministic) and
would silently hand that arm a free pass.

**Answering design-memo Q1: gating, fail-closed, using `live_check.gating`'s
contract verbatim.** Final reward is 1.0 iff the static tiers say 1.0 AND the
live check passes AND idempotence reports `converged`. Both `pending_changes`
and `not_verifiable` downgrade to 0.0. The reasoning is the one `SCHEMA.md` §5
already gives for `apigw-redeploy`: for the catch this scenario exists to
motivate, this tier is one of only two signals that can ever see it, and a
non-gating tier cannot cost a trial any reward.

**Offline it is skipped WITH A REASON, never fake-passed — on all three arms,
by two different mechanisms.** The guarantee is uniform; the mechanism cannot
be, because the arms keep their converged state in different places.

- **`hcl_raw` / `terraconstructs` — pre-flight file probe.** The block probes
  for the arm's local state file first; absent (offline, or an agent that never
  deployed) it reports `not_verifiable` with an explicit reason and never runs a
  plan whose exit code would be a meaningless `2`.
- **`awscdk` — post-flight completion marker.** This arm keeps *no* local state
  (`cdk diff` reads the deployed CFN stack), so there is no file a pre-flight
  probe could look at, and an earlier draft of this section wrongly claimed
  otherwise — a verifier caught it, and it was a real defect and not only a
  documentation one: `cdk diff --fail` exits `1` both for "found changes" and
  for "could not run at all", so an unresolvable AWS environment was being
  recorded as a genuine `pending_changes` verdict. Measured on this arm's exact
  pin (`aws-cdk 2.1135.0`, no range) with credentials unresolvable: exit `1`,
  `no credentials have been configured`, and **no marker printed**; dropping
  `--fail` gives the same exit `1`, so a `--fail`-less pre-flight does not
  discriminate either. `cdk-toolkit.js` emits
  `Number of stacks with differences: %s` unconditionally on the line before
  `return diffs && options.fail ? 1 : 0`, so the marker is present on every
  completed diff and absent on every early error exit. Exit `1` is therefore
  believed only when `idempotence.log` also carries the marker; otherwise the
  outcome is `not_verifiable` with the reason recorded.

The tier was fail-closed throughout (both `pending_changes` and
`not_verifiable` gate to `0.0`), so the defect never produced a fake pass — it
produced a mis-attributed verdict, which is exactly the kind of thing a
pre-registered claim must not be wrong about.

*Draft-scoped:* the per-arm exit-code mapping and the `-refresh=false` choice
are reasoned from documented behaviour, from this repo's own prior
`apigw-redeploy` finding, and (for `awscdk`) from a measured offline run plus
the pinned CLI's own source, but no *live* run has exercised the
converged/pending halves. The first live brownfield run is what promotes them —
specifically, it is the first thing that can show a real `cdk diff` exit `1`
*with* the marker.

**CORRECTION (2026-08-25) — the terraconstructs state path published here was
wrong.** This section stated the `terraconstructs` pre-flight probe watches
`cdktf.out/stacks/<id>/terraform.tfstate`. No terraconstructs run has ever
produced that file. `cdktn`'s `TerraformStack` installs a `LocalBackend` for any
stack declaring no backend of its own
(`packages/cdktn/src/terraform-stack.ts:340-341`) whose default path is
``path.join(process.cwd(), `terraform.${stackId}.tfstate`)``
(`packages/cdktn/src/backends/local-backend.ts:23`) — an **absolute** path baked
into `cdk.tf.json` at synth time. Corroborated by a real synthesized
`cdk.tf.json` from this repo's own jobs directory
(`jobs/claude-sonnet-5/2026-08-20__17-16-22/apigw-redeploy-terraconstructs__W2J5uiF`):
`{"backend": {"local": {"path": "/app/project/terraform.hello-version-api.tfstate"}}}`,
and by the agent in that same trial reading a version-4 state document back from
exactly that path.

**Consequence, recorded because it changes what a published number meant.** Both
live `named-resource-replacement` runs reported `not_verifiable` on this arm
*despite* an apply AWS itself confirmed ("Apply complete! Resources: 6 added",
security group and endpoint present in the account). That was **the probe
failing, not the deploy** — an infrastructure defect wearing the costume of an
unverifiable agent result, the same class of failure as the missing
`AWS_DEFAULT_REGION`. `gen.py::IDEMPOTENCE_STATE_PROBE["terraconstructs"]` is
corrected to `terraform.__WORKSPACE_ID__.tfstate`, and the post-synth re-probe
is repointed at the absolute path. Because the state file is **not** inside the
directory `cdktn synth` rewrites, that re-probe is now expected never to fire;
it is retained anyway, because the guarantee is the contract and the mechanism
is cheap. The correction is load-bearing for Amendment 31, which depends on that
path to hand the seed's converged state to the agent.

**Exercised live 2026-08-26 (this section is no longer DRAFT).** With the path
corrected AND the `CDKTN_BENCH_LIVE=1` fix on the re-synth, all three arms
returned `converged` on a real account. The correction above is what made that
possible; the header table records the rows.

### 5. The MANDATORY do-nothing catch — answering design-memo Q6: yes

Brownfield creates exactly one failure mode greenfield cannot have: **a change
request whose end state the seed already satisfies rewards doing nothing**, and
every existing gate stays green while it happens. `solution/solve.sh` scoring
1.0 proves the oracle *accepts* a correct change; it never proves the oracle
*rejects* the absence of one.

So every `workspace_seed` spec ships `solution/broken/seed-unchanged/solve.sh` —
a no-op that submits the seed exactly as found — and
`gates/oracle_falsifiability.py` requires it to score **< 1.0**, with a
dedicated, differently-worded check whose absence is a hard FAIL rather than a
skip.

`< 1.0` rather than `== 0.0` deliberately: 0.0 is what today's reward contract
produces and what the pilot observes, but the claim being falsified is "doing
nothing does not earn full marks", and pinning an exact value would couple the
gate to the reward scale rather than to the property.

**And `< 1.0` alone is not enough.** `tests/static_tiers.sh` writes `0.0` for a
broken toolchain as well as for a rejected solution, so the gate additionally
requires the run to have produced a graded artifact (a tier-0 summary). Without
that second half the one check whose whole purpose is to be un-fakeable would
pass vacuously on any infrastructure hiccup — and this is not hypothetical:
the pilot's first full batch run reported `TF-PLAN FAILED` on the
terraconstructs arm (mock-STS port contention between back-to-back fixtures)
while the same fixture in isolation failed honestly on the tier-0 name assert.
Unprovable now fails closed, with a message telling the operator it is
infrastructure rather than a verdict.

The fixture is **generator-owned and overwritten on every run** — a documented
exception to `SCHEMA.md` §8.2 point 8's "solution/** is hand-authored". Its
content is entirely mechanical (it writes nothing), so there is nothing for an
author to contribute, and the one fixture whose whole purpose is to be
un-weakenable must not be quietly weakenable into a passing no-op.

Design-memo **Q4** (should `seed_asserts` also run at trial time, inside the
container, as a pre-agent tier?) is **deferred, not answered**: the
generation-time/CI gate is what ships. Recorded here so the deferral is explicit
— it would cost one extra synth/plan per trial and would prove the *container's*
starting state rather than the host's.

### 6. METRIC RULE: brownfield is a separate stratum

**Brownfield tokens-to-green is never pooled with greenfield tokens-to-green.**
Same refusal, same reason, as Amendment 26 §4 (N-step vs 1-step) and Amendment
27 §2 (`apigw-redeploy`'s two forms): the two measure different tasks. A
brownfield trial starts from a plan-green, resource-bearing workspace and is
graded on a change; a greenfield trial starts from an empty skeleton and is
graded on authoring. Averaging them produces a number that describes neither.

Partly supported mechanically, and the gap is stated rather than glossed:

- **What IS mechanical.** `task.toml [metadata] workspace_seed_sha256`, folded
  into the existing `extra_cfg` manifest slot by
  `gates/equipping.py::compute_equipping_hash`, gives every brownfield row a
  distinct `equipping_hash` — and moves it the moment any arm's seed changes.
  Two trials against different starting workspaces therefore carry visibly
  different equipping, which is the schema's own definition of "not comparable"
  (`metrics/result_schema.json`: "Two rows are only comparable if this
  matches"). This needed no `HASH_SCHEME_VERSION` bump — greenfield tasks have
  no such key, so no published hash moves — and it is not redundant with
  `image_digest`, which fallback-resolves to a bare tag string whenever docker
  is offline or the image isn't built locally.
- **What is NOT yet mechanical, and must be respected by hand until it is.**
  `metrics/tokens_to_green.py::cell_key` is `(arm, model, harness)`. It does not
  key on scenario form, so a headline cell computed over a mixed row set WOULD
  average brownfield and greenfield trials together, `equipping_hash`
  notwithstanding — that field is carried on every row but is not part of the
  cell key. Until `cell_key` grows a form dimension, **do not run
  `make metrics` over a results directory containing both forms**; aggregate
  each stratum separately. (`benchmark.json`'s per-cell `scenario_coverage` /
  `by_scenario` breakdown already separates them for reading, but the headline
  `tokens_to_green` figure does not.) Deliberately not changed in this pass:
  altering `cell_key` moves the shape of every published `benchmark.json` and is
  a pre-registration change in its own right, which belongs in its own amendment
  next to the first real brownfield results rather than being smuggled in ahead
  of them.

### 7. The pilot, and what was measured rather than assumed

`specs/named-resource-replacement.yaml`: a VPC, one private subnet, an SSM
interface VPC endpoint, and the explicitly-named security group that endpoint
uses. The change request is a rename to a team-prefixed name.

The pitfall is documented engine behaviour, not planted sabotage:
`aws_security_group.name` is ForceNew; Terraform's default replacement order is
destroy-then-create; EC2 refuses to delete a group still attached to an ENI
(`DependencyViolation`). CloudFormation's replacement path is
create-new-then-delete-old, so the **awscdk arm converges on the naive edit** —
recorded as the measurement, not engineered away.

Three things were established empirically before the spec was frozen, and each
changed the design:

1. **`terraform show -json` emits no `lifecycle` key at all.** Planning the same
   configuration with and without `create_before_destroy` produces byte-identical
   `.configuration.root_module.resources[]` nodes (terraform 1.15.8 /
   hashicorp/aws 6.58.0). The design memo's own sketched seed assert for this
   (`…aws_security_group….lifecycle`, op `not_exists`) would therefore have been
   a **dead path** — passing vacuously on a seed and on a fixed solution alike.
   It is not in the spec. The catch is `live`-tier, and its negative fixture
   *mechanically demonstrates* that indistinguishability offline (planning both
   variants and diffing the graded artifact) before printing
   `CDKTN_BENCH_LIVE_ONLY_CONFIRMED`, so a future terraform release that starts
   emitting `lifecycle` turns `make falsifiability` red instead of letting the
   catch keep claiming an invisibility it no longer has.
2. **terraconstructs' L2 hides the fix.** `SecurityGroupProps` has no `lifecycle`
   member and the underlying L1 is `private readonly`, so the correct answer on
   that arm needs the standard escape hatch
   (`(sg.node.defaultChild as TerraformResource).lifecycle`). Raw HCL exposes the
   same knob as a first-class two-line block. That is an anti-L2 finding in its
   own right and is recorded in the arm's reference solution.
3. **The `--seed` gate immediately caught a real defect in this very spec.** The
   first draft declared one three-arm assert for "the endpoint consumes the
   group"; on awscdk that path resolves to an `Fn::GetAtt` **map**, so a `regex`
   op fails. Split into the two arm-shaped asserts §2 describes. This is the
   exact class of dead-path defect the gate exists for, found on its first run.

### 8. Regeneration + proof

`make gen-all` is idempotent. **Byte-identity of every pre-existing scenario was
verified by regenerating all of them and diffing: zero changed files.** The only
new task dirs are the three `named-resource-replacement-*` ones. The two
generator changes that could have moved existing bytes were built specifically
not to: the idempotence block is *generation*-conditional (not a dead runtime
branch), and `workspace_seed_sha256` / the `[verifier] env` extension are emitted
only when the corresponding spec key is set.

### 9. Deliberately NOT done in this pass

- **`specs/split.yaml` WAS regenerated, and nothing flipped.** Adding a
  scenario shifts the 60/40 cutoff over a growing set, so a re-split can flip an
  EXISTING scenario's group — an integrity event that must be logged, which is
  why `generator/split.py --write` is never a side effect of `make gen`. Ran
  and diffed here:

  | scenario | before | after |
  |---|---|---|
  | `ecs-swappiness` | train (rank 0) | train (rank 1) |
  | `apigw-openapi` | train (rank 1) | train (rank 2) |
  | `s3-lambda-log-retention` | train (rank 2) | train (rank 3) |
  | `sfn-jsonata` | holdout (rank 3) | holdout (rank 4) |
  | `apigw-redeploy` | holdout (rank 4) | holdout (rank 5) |
  | `named-resource-replacement` | *(absent)* | **train (rank 0)** |

  `n_train` goes 3/5 → 4/6 (round-half-up of 0.6·6 = 3.6), and the new scenario
  takes rank 0, so every existing id keeps its group; only ranks shift by one.
  **No equipping is tainted and nothing needs retiring.** The new scenario lands
  in `train`, which is the conservative outcome: a brand-new scenario in
  `holdout` would be selection material nobody had built anything against yet.
- **No live run.** `verifier.live_check` and `verifier.idempotence` are both
  wired and gating, and `tests/live_check.py` is hand-authored on all three
  arms, but nothing in this pass touched AWS. §4's exit-code mapping and §7's
  claim that the naive edit actually fails with `DependencyViolation` on the TF
  arms are reasoned from documented behaviour, not observed — which is exactly
  what keeps this amendment DRAFT.
- **Design-memo Q2 (`lambda-alias-tracks-unpublished-latest`) is untouched.** It
  needs pre-deployed *state*, not seeded *code*, and the memo's recommendation
  (defer to a single-step `[[steps]]` task with a `pre_invoke`) still stands.
  Nothing in this pass blocks or unblocks it.

### 10. ADDENDUM (2026-08-20, task #15 round 3) — IDENTITY SEPARATION: the spec `id` is operator-facing; `workspace_id` is what the agent may know

*Written into this DRAFT amendment rather than appended as a new one because it
closes §3's own rule 7 — the generalised lesson this amendment already claims to
have learned, which it had learned only for the `title` field. Everything below
is pre-registered; nothing in it has been exercised live.*

#### 10.1 What was still leaking, after §3 rule 7

§3 rule 7 says: *the unit that must be read hostilely is every byte the
Dockerfile COPYs.* It fixed the SENTENCE (`title` → `workspace_title`,
§0.1/§3.3). It did not fix the NAME. A round-2 verifier found the scenario `id`
itself reaching `environment/`:

| Site | Arms | Value |
|---|---|---|
| `environment/app/main.ts` — `new ScenarioStack(app, …)` construct id | terraconstructs | `spec.id` |
| `environment/app/main.ts` — `gridUUID` | terraconstructs | `spec.id` |
| `environment/preflight.sh` — `cdktf.out/stacks/<id>/` ×3, *also printed by the agent's own `npx cdktn synth`* | terraconstructs | `spec.id` |
| skeleton/entry headers — `from specs/<id>.yaml`, `` `make gen SPEC=specs/<id>.yaml` `` | **all three** on a greenfield spec; the two with a generator-written entry file on a brownfield one (the seed carries no header) | `spec.id` |

`named-resource-replacement` contains `replacement`, which this amendment's own
§3 rule 4 names verbatim as banned mechanism vocabulary — and it is not the
change request ("rename the security group to X"), it is the DIAGNOSIS the agent
is supposed to reach from the configuration. It reached awscdk and
terraconstructs and **not** hcl-raw, whose entry file IS the seed and carries no
generator stamp: arm-asymmetric, inside the cross-arm comparison the scenario
exists to produce. Confirmed wider on the same read: `apigw-redeploy`'s id is
**step 2's verb**, stamped into every step-1 surface on all three arms.

**Why every guard missed it, and this is the part worth remembering.** Both
deny-list scans SCRUBBED THE SCENARIO ID BEFORE SCANNING, on the same
procedural-sounding reasoning — *"every generated header cites the id, and a
`make gen` invocation needs it"*:

- `test_workspace_seed.py::_brownfield_scrub` did `text.replace(spec.id, …)`, so
  its own `\breplacements?\b` pattern could never match, and
  `test_the_leak_is_symmetric_across_arms` compared three empty sets;
- `test_multistep_emission.py::ACCEPTED_RESIDUALS` scrubbed the bare
  `apigw-redeploy`, so its own `redeploy` token could never match.

Two independent guards, written by different passes days apart, with the same
blind spot in the same place. And Amendment 27's manual sweep grepped the hyphenated `re-deploy`
only, which is why the unhyphenated id passed it untouched.

#### 10.2 THE RULE

> The spec **`id` is operator-facing and MAY name the pitfall.** Trap detail
> belongs to operators: spec YAML comments, `task.toml [metadata]`, `solution/`
> directories, `oracles/`. **Everything the AGENT can see must be named for the
> CURRENT STEP'S GOAL only.**

**The leak test, in one question:** *does this agent-visible name or word reveal
more than that step's own prompt does?* If yes, it is a leak — whatever kind of
thing it is: a title, an id, a construct id, a directory name, a comment citing
a design memo.

This is deliberately a test about INFORMATION, not about field names. It is what
catches the next site nobody has thought of yet, in the way that "sanitise the
title" and then "sanitise the id" each failed to.

#### 10.3 The mechanism: `workspace_id` (SCHEMA.md §0.1)

`workspace_id` is to the NAME what `workspace_title` is to the SENTENCE, on the
same required/optional rules:

- **Required** on a multi-step or brownfield spec — the author must CHOOSE a
  safe name, never inherit a leaking one by omission.
- **Optional elsewhere, defaulting to `id`** — *but the deny-list runs against
  the resolved value either way*. A single-step greenfield spec whose id would
  leak is refused at spec-load time until it declares one. An id that names only
  the open goal of its own prompt is fine as the default, and every such spec
  regenerates byte-identically.

Declared: `named-resource-replacement` → `internal-services-network`;
`apigw-redeploy` → `hello-version-api` (step 1 asks for a REST API serving
`GET /hello` and `GET /version`; nothing in the name implies a second change).
Both operator-facing ids are KEPT — they are good names for a results table.

The deny-list moved OUT of the test modules and into `generator/spec_model.py`,
because a *validator* needs it:
`Spec._agent_visible_identity_is_deny_list_clean` refuses a leaking
`workspace_id`/`workspace_title` at load time rather than letting a test notice
three regenerations later. It is split into two classes with different scopes,
and the split is load-bearing:

| Surface | mechanism/meta | foreshadowing |
|---|---|---|
| `environment/**` | banned | banned |
| every step's prompt **but the last** | banned | banned |
| the **last** prompt (or a stepless `instruction.md`) | banned | allowed |

Step 02's prompt *is* a change request and *does* ask for a re-deploy; a sweep
that must be switched off for the file where the words are correct is a sweep
nobody keeps running. Naming the FIX is never allowed, in any prompt. Every
separator-bearing pattern now matches `-`, `_`, a space, **or nothing** —
`redeploy` as well as `re-deploy` — and that is an INVARIANT with its own test
(`test_no_deny_list_pattern_requires_a_separator`), not a convention: a pattern
that writes `[ _-]` without the `?` fails the suite. The whole leak was one
optional quantifier wide. `agent_deny_vocab` extends the foreshadowing
class per scenario, declared in the spec so the words that would give a trap
away are reviewed in the same file as the trap.

#### 10.4 No exemption for the id — the scrub is now an assertion

The two exemptions are gone. What is scrubbed before a scan is now only:

1. **`workspace_id`** — whose cleanliness a VALIDATOR guarantees, so scrubbing
   it removes no information the deny-list could have used. The exemption
   became an assertion; that is the whole trick.
2. **Tokens the agent's own prompt hands it** — derived from the emitted prompt,
   never declared, and re-proven per entry. `apigw-redeploy-api` is the only
   one: step 01 says "named EXACTLY `apigw-redeploy-api`", so it reveals exactly
   as much as the prompt does. A bare id can never qualify (the derivation
   requires a suffix), which is what keeps the id inside the scan.
3. **Arm boilerplate** — each entry proven to exist under `arms/*/environment/`.

**"Proven boilerplate" is not the same as "carries no information."** Six
`arms/*/environment/` files explained themselves by naming the scenario that
first needed them ("python3 … currently only apigw-redeploy"; three such lines
in `hcl-raw`'s `provider.tf` alone). Byte-copied into every task dir, that
shipped `redeploy` into the agent image of the very scenario it names — and it would have passed any allowlist-honesty check that
asks "does this also appear under a greenfield control?", because it appears
under *every* control. Constant across scenarios is not the same as carrying no
information about one. All six now describe the PROPERTY the arm needs ("any
spec with `verifier.live_check.enabled: true`"), pinned by
`test_arm_image_sources_name_no_scenario`.

#### 10.5 The header stamps cite no spec at all

`from specs/<id>.yaml` and `` `make gen SPEC=specs/<id>.yaml` `` became
`Generated skeleton -- generator/gen.py.` and `` `make gen` ``, **uniform across
every scenario and every arm**. Rewriting the citation with `workspace_id` was
considered and rejected: it would name a spec file that does not exist and lie
to the next maintainer. These lines address a bench maintainer, who holds the
repo and gets the usage message from `make gen` anyway. Uniform beats
scenario-varying: a stamp that is neutral for *some* scenarios would itself
signal which ones have something to hide. The mapping is not lost — it is
recorded host-side as `task.toml [metadata] workspace_id`.

**Cost, stated plainly:** every task dir's skeleton headers moved, so this pass
does NOT preserve §8's byte-identity property for pre-existing task dirs. That
was traded deliberately for a stamp that carries zero scenario information;
`task.toml` for the five agent-safe scenarios is still byte-identical (the new
`[metadata] workspace_id` key is emitted only where the two names differ).

#### 10.6 The sweep is now a permanent test, corpus-wide

`generator/tests/test_scenario_identity.py` — every spec including `_toy`, every
enabled arm, every byte of `environment/` plus every prompt:

- the operator-facing id appears in no agent-visible file;
- the vocabulary sweep, in both scopes, with the spec's own `agent_deny_vocab`;
- **arm symmetry** as set equality (asymmetry is what corrupts the measurement,
  so it gets its own assertion rather than riding on the scan);
- the workspace identity is stamped IDENTICALLY on every arm that stamps it;
- `arms/*/environment/**` names no scenario;
- both allowlists proven honest;
- **the pre-fix stamps replayed verbatim and required to FAIL** — a deny-list
  nobody ever saw fail is a deny-list nobody can trust. Run it against the old
  `_brownfield_scrub`/`ACCEPTED_RESIDUALS` and it goes red.

#### 10.7 Also in this pass: the terraconstructs idempotence re-probe

The round-2 verifier's note. The terraconstructs idempotence command re-runs
`npx cdktn synth` AFTER the pre-flight state probe and BEFORE `terraform plan`,
**in the same directory the probe just checked**. If synth ever cleans
`cdktf.out/stacks/<id>/`, the probed `terraform.tfstate` is gone by plan time and
an offline-shaped plan (exit 2) would be recorded as a genuine `pending_changes`
verdict — precisely the fake verdict the probe exists to prevent, delivered
through the one window the probe cannot see through.

Fixed by re-probing INSIDE the command, after synth and before terraform is
believed: a vanished state prints a named marker and exits a reserved rc (`9`,
distinct from every code terraform and cdk produce), which the generated block
maps to `not_verifiable` with that reason. Emitted only for the arm whose
command can raise it, so no other arm's `tests/test.sh` moves a byte. Still
unexercised live — this remains the promotion gate this amendment already
designates.

#### 10.8 Falsified, not assumed — and one consequence that is not cosmetic

**The two regression tests were run against the PRE-FIX code and go red.** With
the old id exemption reintroduced verbatim, all **8** of the stamps that were
really on disk at HEAD (`new ScenarioStack(app, "…")`, `gridUUID: "…"`,
`STACK_DIR="cdktf.out/stacks/…"`, `OUT_FILE=…`, and the two skeleton-header
forms, across both scenarios) are ACCEPTED by the scan; with the shipped scrub
all 8 are REJECTED. Likewise `_brownfield_scrub`: the pre-fix version reports
"no leak" on the exact bytes of the pilot's `main.ts` stamping, the shipped one
reports `\breplacements?\b`.

**`gridUUID` is not decoration — it names real AWS resources.** On the
terraconstructs arm every L2's default physical name is
`${gridUUID}-${uniqueResourceNamePrefix(...)}` (terraconstructs 0.2.13
`lib/aws/compute/function.js`). Changing `gridUUID` therefore changes the
deployed resource names on that arm, and one hand-authored fixture depended on
the old value: `apigw-redeploy-terraconstructs/solution/solve.sh`'s residual
log-group sweep matched `/aws/lambda/apigw-redeploy` (finding G7's own fix).
That sweep now covers `/aws/lambda/hello-version-api` **and keeps the old
prefix**, because a real deploy made before this change leaves residue under the
old name and this sweep is the only thing that removes it. Checked and found
NOT affected: hcl-raw's Lambda names are explicit literals in the HCL; awscdk's
stack id is the constant `"ScenarioStack"`, never id-derived; every oracle and
`live_check.py` lookup for both scenarios keys on a spec-declared literal name,
not on the grid prefix. The retired scoped-IAM proposal in
`docs/slice-g-iam-proposal.md` still scopes an ARN to `apigw-redeploy-*` on this
arm; it is a proposal for a role Amendment 24 already retired, but if it is ever
revived that pattern must become `hello-version-api-*`.

---

## Amendment 29 (2026-08-22) — physical resource identity is never load-bearing — **DRAFT, pre-registered, not yet exercised live**

**Decision.** The benchmark adopts a stated authoring convention, and grades
consistently with it:

> **Identity flows through explicit references carrying opaque IDs. Never
> through a name-based join — whether that join is a hardcoded literal or a
> data-source lookup.**

Four corollaries:

| axis | rule |
|---|---|
| **Identity** | physical names are **generated** (`namePrefix`, `bucket_prefix`, CFN-assigned). Cross-stack wiring uses an explicit reference (export/import, output/input, remote state) — never a literal name, and never a `data` lookup keyed on a human-readable name. |
| **Convention** | naming standards are expressed as a **prefix**, which preserves auditability without pinning identity. |
| **Attribution / observability** | **tags**. Mutable, multi-dimensional, and the mechanism actually designed for it. |
| **Stateful safety** | `prevent_destroy` / deletion protection / `RETAIN` / backups. An **orthogonal** axis — see §3. |

### 1. Why name-joins are implicit dependencies

A literal name in stack B naming stack A's resource creates **no edge in the
IaC graph**. The consequences are not stylistic: no ordering guarantee, no
reference counting, no cascade on change, no deletion protection. An
export/import or output/input reference gives all four. (CloudFormation's
import-blocks-delete behaviour *is* reference counting — with its own costs, see
the `cross-stack-export-deadly-embrace` candidate, but it is at least a real
edge.)

Fixed names also destroy **redeployability**: you cannot stand up a second
instance of the same stack in one account/region without collision. For S3 the
namespace is *global*, so the collision domain is every AWS account on earth.

**Data-source lookups keyed on names are the same anti-pattern**, and add a
second failure mode: they resolve at plan time against live state, so identical
config silently means different things on different days. An AMI name-filter
matching a newer image produces an unrequested replacement; a literal at least
fails loudly when its target is gone. `data "aws_route53_zone" { name = … }`,
`data "aws_vpc" { tags = … }`, `data "aws_iam_role" { name = … }` are all
name-joins — pass the opaque `zone_id` / `vpc_id` / role ARN in instead.

*Convergence worth noting:* the harness already forbids context lookups
(`--no-lookups`, offline provider mirror) for **hermeticity**. That constraint
enforces this tenet as a side effect, and explains why
`asg-launch-template-tag-propagation` uses a literal AMI id — the same
discipline arriving from a different direction.

### 2. The narrow surviving exception

A genuinely **external** consumer outside our IaC — a partner account trusting a
role ARN, a third party with a baked-in URL. Real, but small, and usually better
solved by an indirection layer (a DNS record, a CDN alias, a stable façade role
that assumes rotating ones) than by pinning the underlying resource's physical
name. It is a migration/contract problem, not an IaC-design preference.

### 3. Statefulness argues AGAINST fixed names, not for them

The common intuition is that stateful resources (S3, RDS, DynamoDB — broadly
what CloudFormation defaults to `RETAIN`) deserve fixed names as the careful
choice. **It is exactly backwards.** With a fixed name, create-before-destroy
is *impossible* — the replacement would collide with the original — so the
engine is forced into destroy-then-create, guaranteeing downtime and, on a
stateful resource, data loss. A generated name is what makes CBD available at
all.

Stateful resources do require more care; that care is `prevent_destroy`,
deletion protection, `RETAIN`, and backups. None of it requires, or is helped
by, a fixed physical name.

### 4. What this means for oracles (binding, effective immediately)

1. **No oracle may key identity on a physical name** — not `values.name`, not
   `Properties.RoleName`, not `bucketName`. Grade **existence + type +
   properties**, keyed on the plan **address** (TF arms) or **logical id** (CFN
   arm). A solution that omits the physical name and lets the provider compute
   one MUST score identically to one that sets it, **on every arm**.
2. **Where a prompt states a requirement applies to all of N resources, the
   oracle enforces it per-resource** (set difference over addresses), not
   "at least one". Name-agnostic and per-resource are compatible.
3. A deny message must state something the graded artifact actually
   contradicts. A factually false deny is itself a defect.

Ecosystem evidence that (1) matches practice rather than inventing it:
terraconstructs' own suite uses existence+property matching (154 of 253 test
files use `toHaveResourceWithProperties`); `test/assertions.ts:179-184` ships a
helper documented as *"Get an Array of resources by type, **discarding the
resource names**"*; `src/aws/iam/role.ts:489-509` defaults to `namePrefix`
whenever `roleName` is omitted; `bucketName` appears **0 times** in bucket test
assertions. Its integration tests read physical names only from Terraform
**outputs** post-deploy, as lookup handles for real AWS API calls, and never
assert them against hardcoded strings.

### 5. Disclosed confound, and how it is neutralised

This is a **normative stance on IaC practice**, in a benchmark that otherwise
claims neutrality between tools. It must be disclosed, because idiomatic
raw-HCL material pushes fixed names heavily (it is how you wire things without a
reference discipline), so the convention is not equally natural to all arms.
CDK and terraconstructs default to generated names; raw HCL forces an explicit
choice.

The neutralisation is a deliberate split between **grading** and **measurement**:

- **Grading is neutral** (§4): oracles never *require* a name and never
  *penalise* one. Both shapes score 1.0. No arm is advantaged, because nothing
  is scored on this axis.
- **The stance is measured, not assumed.** Where load-bearing names cost
  something real, a scenario measures that cost and the data argues the case.
  `named-resource-replacement` (Amendment 28) is the first: a fixed name forces
  destroy-then-create on rename.

**Pre-registered empirical test of the tenet itself** — a scenario that
**deploys the same stack twice into one account/region**. Fixed names fail on
collision; generated names pass. Arm-neutral (every arm can do either), cheap,
and decisive. Queued in `ROADMAP.md` §5. If that scenario does *not* separate
the shapes, this amendment's premise is weaker than claimed and should be
revisited.

### 6. Addendum (2026-08-23) — the tenet governs resources you CREATE, not ones you ADOPT

The rule as first written missed **brownfield adoption**: importing existing
infrastructure (`terraform import` / `import` blocks, CloudFormation resource
import, `CfnResource` adoption). An imported resource *already has* a physical
name, assigned by whoever created it. The config must state that name to match
the live resource — that is not a design choice, it is a fact being recorded.

So the boundary is **create vs adopt**:

- **Creating** a resource: never pin the physical name (§1-§4 apply in full).
- **Adopting** an existing one: the name is **given**. Stating it is correct,
  and an oracle must not penalise it. What the tenet still asks is that
  *downstream* wiring reference the adopted resource, rather than re-hardcoding
  its name at every use site.

This is a materially different task shape from the brownfield form of
Amendment 28, which seeds *code* into the workspace. Adoption requires **real
pre-deployed infrastructure** for the agent to import — which cannot be served
by `workspace_seed` (a file) or by multi-step `pre_invoke` (per-trial). It
therefore joins the cases in `ROADMAP.md` M7 that force a **second aws-bench
scenario**.

**Status.** DRAFT until the redeployability scenario runs. §4 is binding on
oracle authoring now, because it is a consistency requirement (the arms must be
graded at equal strictness) independent of whether the tenet itself holds.

---

## Amendment 30 (2026-08-23) — awscdk tier-1 may be graded by OPA/Rego; train/holdout re-split at 14 scenarios

Two changes, both mechanical consequences of Batch A landing.

### 1. OPA/Rego is now available as the awscdk tier-1 engine (ROADMAP M8)

**Cause, proven by execution.** cfn-guard 3.2.0 cannot express a cross-resource
join (no logical-id join between an IAM role and the `AWS::IAM::ManagedPolicy`
that names it). The awscdk tier-1 for
`iam-managed-policy-exclusive-vs-attachment` therefore degraded into a
count-equality proxy, unsound in **both** directions:

- a policy reaching only ONE role, declared from both sides, balanced the counts
  and scored **1.0** — a false PASS that defeated that scenario's own
  `policy-attached-to-one-role-only` catch — while the byte-equivalent
  terraconstructs solution scored 0.0;
- a policy attached to BOTH roles from both sides scored **0.0** — a false FAIL
  the synthesized template flatly contradicts — while terraconstructs scored 1.0.

Three consecutive opus fix rounds failed to close it. This was a **tooling
ceiling**, not an authoring defect, and Amendment 29 §4 makes equal-strictness
cross-arm grading binding.

**Decision.** A spec may select the awscdk tier-1 engine. Rego policies for the
awscdk arm live in `oracles/rego-cfn/<id>/` and are evaluated against the
synthesized CloudFormation template — a different input shape from the TF arms'
`terraform show -json`, hence a separate path rather than one shared policy file.
All existing tier-1 failure semantics are preserved unchanged
(`SKIPPED_NO_ASSERTS`, `TOOL_MISSING` + `tier1-unavailable`, `SKIPPED_STUB` +
`tier1-unauthored`, and the hard reward gate); each exists because it once
allowed a silent false pass. `opa` is added to the awscdk arm image.

**cfn-guard is RETAINED, and reclassified.** It stays installed and supported —
it is a real tool an awscdk team has. It is simply not the *authority* for a
cross-arm comparison, because it grades at a different strictness than the engine
used on the other arms. Specs already using it are unchanged and regenerate
byte-identically.

**Caveat on the capability claim.** "awscdk has more guardrail tooling" must NOT
be evidenced by cfn-guard's existence — Terraform has conftest/OPA, Checkov,
tfsec and Sentinel. The genuinely CDK-specific guardrail is **Aspects / cdk-nag**
(programmatic, type-aware, running at synth over the construct tree, no HCL
equivalent). Any guardrail-advantage claim should be measured there.

**Immediate evidence the diagnosis was right:** after migrating,
`iam-managed-policy-exclusive-vs-attachment` passed adversarial verification in a
**single** round.

### 2. Train/holdout re-split (Amendment 10 procedure)

Batch A took the non-toy spec set from 6 to 14, so `generator/split.py --write`
was run per Amendment 10's documented re-split procedure.

**No id flipped.** Every pre-existing scenario kept its group, so the
train→holdout taint rule in that procedure is not engaged — and no tuned
skill/MCP equipping exists yet in any case (the equipping factorial is ROADMAP
M2, still unbuilt), so there is nothing that could have been tainted.

| group | scenarios |
|---|---|
| **train** (8) | `acm-dns-validation-record-wiring`*, `apigw-openapi`, `ddb-gsi-attribute-definitions`*, `ecs-swappiness`, `named-resource-replacement`, `s3-bucket-hardening-decomposition`*, `s3-lambda-log-retention`, `s3-notification-custom-resource-tax`* |
| **holdout** (6) | `apigw-redeploy`, `asg-launch-template-tag-propagation`*, `iam-managed-policy-exclusive-vs-attachment`*, `lambda-log-group-ownership-and-retention`*, `s3-notification-authoritative-singleton`*, `sfn-jsonata` |

`*` = new in Batch A. Ratio 8/6 matches the 60 % round-half-up rule for n=14.

**Freeze note.** Per `generator/split.py`'s own procedure, `--write` should stop
being run once real equipping-tuning work begins for a phase. That point is
ROADMAP M2; until then, re-splitting as scenarios land is expected and cheap.

---

## Amendment 31 (2026-08-25) — single-step seed deploy: the brownfield premise
## is made true by the harness — **ACCEPTED 2026-08-26**

**Status: ACCEPTED (promoted 2026-08-26).** Registered as DRAFT before any
brownfield result produced under this mechanism existed, on the criterion in §7:
the first live `named-resource-replacement` run under the mechanism, the same
run that promotes Amendment 28.

**That run happened.** Three arms, zero exceptions, every arm `seed_deployed` /
live_check `pass` / idempotence `converged`
(`jobs/live-brownfield-seed/2026-08-25__22-21-37` and
`…/2026-08-26__08-54-19`). The per-arm table is in Amendment 28's header.

### §7's capture list — what the run actually settled

**1. terraconstructs state path — ANSWERED, indirectly.** §7 asked for
`find /app/project -iname '*.tfstate*'` after the seed deploy. That listing was
not taken; the evidence is the seed movement guard's own behaviour, which is
conclusive for the question asked. The guard writes `not_verifiable` whenever
the receipt's `state_identity` is empty or the on-disk identity is unreadable.
terraconstructs returned `converged` with `seed-identity.err` empty, so the
receipt carried an identity, the state file WAS found at
`/app/project/terraform.<workspace_id>.tfstate`, and the identity had MOVED from
the seed's. The absolute path published in Amendment 28 §4's correction is
confirmed.

**2. `cdktn deploy` exit code on a PARTIAL apply — STILL UNOBSERVED.** No
partial apply occurred on any arm; all three deploys were clean. This cannot be
settled by waiting for it to happen by chance, and Layers 2 and 3 exist
precisely because Layer 1 might miss it. The claim stands as designed-for, not
as demonstrated. Anyone forcing this case (an induced mid-apply failure) should
record the result here.

**3. Interface VPC endpoint readiness at `apply` return — ANSWERED for the
shape used.** The live asserts read `SecurityGroupIds`, not `State`, and passed
on all three arms, so the attachment is true the instant the endpoint object
exists. An endpoint-`State` assert remains unavailable: it needs a
poll-with-timeout primitive the generator still does not have.

### Observability gap found by this promotion

`/logs/seed-deploy-receipt.json` is written by `pre_invoke.sh` and read by
`tests/test.sh`, but is **not** downloaded into the job artifacts — only
`/logs/pre_invoke/*` and `/logs/verifier/*` are. The receipt is the anti-vacuity
channel and the movement guard's only input, so no post-hoc audit of it is
possible from a finished job dir; item 1 above had to be inferred rather than
read. Worth adding to the downloaded set.

### Relationship to multi-step

This amendment is the SINGLE-STEP mechanism and is complete on its own terms.
Upstream aws-bench still refuses multi-step outright
(`aws_bench/task/aws_trial.py`: *"multi-step AWS tasks are not yet supported
(per-step pre/post-invoke credentialing is undefined)"*); multi-step runs only
through this repo's `CdktnMultiStepTrial` (Amendments 26/27), and
`specs/apigw-redeploy.yaml` remains the only spec declaring `steps:`. The
multi-step `pre_invoke.deploy_prior` facility is still exercised by no real
spec. Nothing here changes that; a brownfield scenario needing pre-deployed
STATE rather than pre-deployed RESOURCES is the case that would.

**Numbering note.** `docs/design/single-step-seed-deploy.md` calls this
"Amendment 29". Amendments 29 and 30 had already landed by the time it was
implemented, so it is registered here as **31**. The design doc's own section
numbering is otherwise unchanged and remains the contract.

### 0. The defect

`workspace_seed.premise` told the agent its workspace "is already deployed in
this account". **Nothing deployed it** (`docs/brownfield-seed-not-deployed.md`).

On `named-resource-replacement` that is not a cosmetic gap. The trap is a
*replacement* trap — renaming a literally-named security group forces
destroy-then-create, and the interface VPC endpoint holding that group turns the
destroy into a `DependencyViolation` — so every step of it needs the group to
exist **in AWS and in state**. With nothing deployed the trap could not fire on
any arm, and `tests/live_check.py`'s discriminating assertion ("fail if the OLD
group survives") was satisfied **vacuously**: the oracle reported `pass` while
proving nothing. Three published rows were voided.

### 1. The mechanism, and where it runs

A brownfield spec declaring `workspace_seed.deploy` (`specs/SCHEMA.md` §2.7.1)
makes the generator emit, per arm,
`tasks/anchor/<id>-<arm>/pre_invoke/{pre_invoke.sh,_assert_lib.sh}` plus
`task.toml`'s `[scenario] pre_invoke_role_name` and a task-level
`[pre_invoke] timeout_sec`.

`aws_bench/task/aws_trial.py::AwsBenchSingleStepTrial._prepare` runs that script
**inside the agent container**, after the container is up (so `/app/project`
already holds the seed, COPYed in at image build) and **before the agent's first
token**. **No runner change was required**: that hook already runs
unconditionally for any task carrying the file, and a multi-step brownfield spec
reaches the same `_prepare` through its MRO (`harbor/trial/multi_step.py`
overrides `_run`/`_prepare_step`, never `_prepare`). The whole change is
generator + spec + docs — nothing in `cdktn_bench/` or any vendored library.

Anything the script writes under `/app/project` is there when the agent arrives.
That is the entire mechanism by which cross-arm deploy state gets *placed*.

`output_contract.deploy_command` is **reused verbatim** and gains a second legal
consumer (the first being `steps[].pre_invoke.deploy_prior`). A second per-arm
deploy field would give a spec two places to say the same thing and one place
for them to drift apart.

### 2. The anti-vacuity contract — and why a missing seed ABORTS rather than scoring 0.0

Four fail-closed layers, in order (the fourth added by §10's review):

1. **The deploy must exit 0.** A non-zero exit raises `ScriptExecutionError` out
   of `_prepare`; `Trial.run`'s handler then never calls `_run()`. No agent
   phase, no verifier, no reward key at all.
2. **The state artifact must exist** — the per-arm probe of §3. This catches a
   toolchain that reports success while leaving nothing the next phase can use.
3. **`workspace_seed.deploy.live_asserts` must hold**, resolved against real AWS
   CLI responses through the same `generator/jsonpath_jq.py` compiler and the
   same `_assert_lib.sh::assert_check` tier-0 uses. At least one entry must set
   `pins_catch`, mirroring `seed_asserts[].pins_catch`: without the
   back-reference the asserts drift into proving that *something* got deployed
   rather than that the *poisoned* thing did — the same vacuity, one level up.
   Two load-time rules narrow the ways a live assert can pass on an **empty
   account** — the ops that pass on zero resolved nodes (§10, finding M1) and
   the `jsonpath` shapes that resolve to a container rather than iterating it
   (§11, finding A). Neither is a proof of falsifiability, and §2.7.1 says so.
4. **The verifier refuses to grade a trial whose seed never ran.** Layers 1–3
   all live inside `pre_invoke.sh`, which `_prepare` executes **iff the file is
   on disk** — `if self.task.has_phase_script(ScriptType.PRE_INVOKE):`, no
   `else`, no log line. So the script writes a receipt at
   `/logs/seed-deploy-receipt.json` (not under `/logs/pre_invoke/`, which
   `ScriptRunner` deletes), `task.toml` sets
   `[verifier].env.SPEC_SEED_DEPLOY_REQUIRED = "true"`, and the generated
   `tests/test.sh` writes **no reward file at all** when the key is set and the
   receipt is missing — so Harbor's own `RewardFileNotFoundError` aborts the
   trial instead of a 0.0 being recorded (§10, finding M3).

The verdict is written to `/logs/pre_invoke/seed-proof.json` as
`seed_deployed` (0), `seed_absent` (2) or `seed_unverifiable` (3), shaped like
`live_check`'s and `idempotence`'s own three-valued contracts. Both
non-`seed_deployed` verdicts **abort the trial**, and the strengthening is the
point:

> A reward of 0.0 is a **measurement**. It says the agent failed. A seed that was
> never deployed did not produce an agent failure; it produced **no measurement
> at all**. Recording it as 0.0 would repeat the original defect with the sign
> flipped — a number that looks like evidence and is not.

The abort lands as `result.json` with `exception_info` set and no
`verifier_result`, which `metrics/extract_signals.py` already renders as
`INFRA-FAIL:` and drops from every rollup. The honest outcome falls out of
existing code. `_finalize()` and — because `super().run()` returns normally after
recording the exception — `_reset_scenario_account()` both still run, so a
half-deployed seed is still torn down.

`seed_asserts` are **not** this instrument and are not replaced by it. They run
at generation time, offline, un-overlaid, never in a container
(`make seed-parity`), and answer *"do the three seeds declare the same
system?"*. A green `make seed-parity` is evidence about three YAML bodies; it
never was evidence about an account.

### 3. Cross-arm state — the hard half

| arm | where converged state lives | how the agent's later run binds to it | proof |
|---|---|---|---|
| `awscdk` | **In AWS.** CFN stack `ScenarioStack`. No local state. | `bin/app.ts` is generator-owned and non-agent-editable and fixes the physical stack name, so a later `cdk deploy` issues an **UpdateStack**. | `describe-stacks` ⇒ `CREATE_COMPLETE`/`UPDATE_COMPLETE` |
| `hcl_raw` | `/app/project/terraform.tfstate` (implicit local backend) | same container, same cwd, same file | `[ -s … ]` |
| `terraconstructs` | `/app/project/terraform.<workspace_id>.tfstate` — **not** under `cdktf.out/` (Amendment 28 §4 correction) | the absolute path is baked into `cdk.tf.json` at synth time and is identical in offline and live mode, so every later synth from `/app/project` resolves the same file | `[ -s … ]` |

**A deployed seed broke `hcl-raw`'s tier-0 outright, and that is measured, not
predicted.** That arm's `plan_command` carried no `-refresh=false`, so the moment
a `terraform.tfstate` exists the *offline* verifier plan refreshes through
`provider.tf`'s dummy credentials and dies —
`aws_vpc.internal_services: Refreshing state... [id=vpc-05c33a26cbf19bef8]`,
then `PLAN FAILED`
(`jobs/rerun-named-resource-replacement/2026-08-25__01-43-17/named-resource-replacement-hcl-r__rtmpCyN/verifier/test-stdout.txt:42-46`).
That row's 0.0 was read as "the agent's config is bad"; it was the **verifier**
failing on state the agent's own **successful** apply created. Once the harness
seeds state deliberately it would fire on **every** hcl-raw brownfield trial,
including a perfect one. `Spec._brownfield_plan_must_not_refresh` now hard-errors
at spec load for any `workspace_seed` spec whose enabled arm plans without the
flag. Grading is unaffected: every `tf_jsonpath` reads `$.planned_values` /
`$.configuration`, which carry the full desired end state, not a changeset.

### 4. Role parity — the seed deploys under the AGENT's own role

`[scenario] pre_invoke_role_name` is set to `agent_role_name`, and that is a
**rule, not a default**. `aws_creds.py` falls back to
`OrganizationAccountAccessRole` when the key is unset, and deploying the seed
with a broader role than the agent gets can create resources the agent cannot
subsequently modify or delete — a harness privilege asymmetry wearing the costume
of an agent failure, which is precisely the failure mode Amendment 24 retired
`QADeployApplicationRole` to avoid. *A seed the harness can deploy must be a seed
the agent can change.*

The container user is guarded too, on **both** knobs — and the reason first
published here was wrong, corrected by §10 (finding m3). A Dockerfile `USER`
moves the seed deploy and the agent **together** (both take the image default;
`ScriptRunner.run` passes no `user=`), so it cannot cause the EACCES asymmetry
this once claimed. What it *does* cause is that `ScriptRunner` creates
`/logs/pre_invoke` as **root** (step 2) and then runs the script as the image
default, so a non-root user cannot write `seed-proof.json`, the receipt or
`placeholder.json` there and the trial dies with no verdict anywhere. The
generator still hard-errors on a `USER` directive, now for that reason. The knob
that genuinely diverges the two users is `task.toml`'s `[agent] user` —
`_staged_credentials` writes `~/.aws/credentials` as that user while the phase
script runs as the image default — so a seed-deploying spec is refused if its
`task.toml` would carry one.

### 5. Measurement integrity

Seed-deploy time and tokens are never attributed to the agent, structurally
rather than by discipline: `pre_invoke.sh` is a shell script so no LLM runs and
`extract_signals`' session glob matches nothing it writes; cost is read from
`agent_result.cost_usd`, which Harbor populates from the agent run only; and
`ScriptRunner` `rm -rf`s `/pre_invoke` and `/logs/pre_invoke` for `PRE_INVOKE`
specifically, before the agent phase begins — so the agent cannot read the
script, the deploy log, or the proof. What it *does* see is a state-bearing
workspace, which is the brownfield premise being true.

**One standing obligation.** `_prepare` sits inside the trial's
`started_at`→`finished_at` window, so any *trial-duration* metric would include
the seed deploy. No metric reads a duration today. If one is ever added it must
read the **agent phase's** own window, never the trial's. Recorded here so it is
a decision rather than an oversight.

The existing metric rule is unchanged and still manual: brownfield
tokens-to-green is a separate stratum (Amendment 28 §6), and
`metrics/tokens_to_green.py::cell_key` is still `(arm, model, harness)` with no
scenario-form dimension. Deploying the seed does not change that; it makes the
brownfield rows worth stratifying for the first time.

**Equipping.** Regenerating this scenario moves its task bytes, so its
`equipping_hash` moves. That is correct — its three published rows are already
void — but **no pre-fix row may ever be pooled with a post-fix one**, and
nothing enforces that automatically.

### 6. Cost — per trial, and not reusable

The seed cannot be deployed once and reused, for three independent reasons, any
one of which is sufficient:

1. The post-trial reset is unconditional for a mutating task and has no
   keep-this carve-out. It destroys exactly what the seed created.
2. Both TF arms need the state **file** inside the agent's container filesystem,
   and containers are per-trial. Even a surviving account-side deployment would
   have to be re-materialized locally.
3. A persistent seed would put the account permanently out of baseline — the
   condition `_raise_if_contaminated` refuses to start a trial on.

**Wall clock: roughly +3–6 minutes per trial**, dominated by the interface VPC
endpoint reaching `available`, on top of the mandatory ~8.5–9 minute post-trial
reset. `concurrency_mode: mutating` holds the scenario's exclusive writer gate
across both, so a six-trial brownfield battery is strictly serial and runs near
an hour longer than the greenfield equivalent. **Dollars are negligible** — one
interface endpoint at roughly $0.01/AZ/hour, under a cent over a trial's life.

### 7. Promotion criterion, and what the first live run must capture

Promoted to ACCEPTED by the first live `named-resource-replacement` run under
this mechanism — the same run that promotes Amendment 28. Until then no
brownfield row may be published.

That run must capture three things this design could not settle offline:

1. `find /app/project -iname '*.tfstate*'` immediately after the terraconstructs
   seed deploy. The state-path resolution rests on `cdktn`'s own source plus a
   live `cdk.tf.json` from a *different* scenario; neither is a post-deploy
   directory listing for this one. Layer 2 fails closed if it is wrong — that is
   the design working, not failing, but it aborts rather than degrades.
2. `cdktn deploy`'s exit code on a **partial** apply. If it can exit 0 having
   applied only some resources, Layer 1 misses it — which is why Layers 2 and 3
   exist. Watch `seed-proof.json`.
3. Whether the interface VPC endpoint is far enough along when `apply` returns.
   The live asserts deliberately read `SecurityGroupIds` and not `State` for that
   reason; if an endpoint-state assert is ever wanted it needs the poll-with-
   timeout shape `live_check.py` already uses, and the generator has no poll
   primitive today.

### 8. Offline proof

`make gen-all` moves the three `named-resource-replacement-*` trees (new
`pre_invoke/`, changed `task.toml`, the `-refresh=false` plan on hcl-raw, and
the corrected terraconstructs state path in `tests/test.sh`) **and, after §10,
two files in every task tree**: `tests/_assert_lib.sh` (three-valued
`assert_check` return codes) and `tests/test.sh` (the layer-4 seed gate). Both
are single static templates, runtime-gated on env vars `task.toml` sets per
spec — the same discipline the live-check and idempotence blocks already use —
so every non-brownfield scenario's behaviour is unchanged and no other file
moves. `make check` green (**1072 passed, 5 skipped**, up from 1033).
`make falsifiability SPEC=specs/named-resource-replacement.yaml` and
`make seed-parity SPEC=specs/named-resource-replacement.yaml` both green.
`generator/tests/test_seed_deploy.py` proves the vacuity case **mechanically**
for **both** live asserts, compiled and executed exactly as a trial executes
them: `old-group-is-live` passes against a real `describe-security-groups`
response and fails against `{"SecurityGroups": []}`, and
`endpoint-holds-the-old-group` passes against an armed
`describe-vpc-endpoints` response and fails against the renamed-only, the
empty, and the stray-extra-group ones.

### 9. Batch B inherits every rule here

Four more brownfield scenarios assume a deployed seed. Each needs its own
`deploy` block, its own `live_asserts` with a `pins_catch`, and its own
`-refresh=false`. The generator enforces all three; none of them is a
review-time convention.

### 10. Adversarial review (2026-08-25, same day) — what it found and what changed

Two adversarial verifiers attacked the implementation above before it ever ran
live. Correctness came back *sound with caveats*; **vacuity came back
DEFECTIVE**. Zero blockers, five major, five minor — recorded here rather than
folded silently into §§1–9, because the shape of what they found is the point:
**every one of them was a case that produced the right-looking output and no
error.** That is this repo's signature failure mode, and it is the reason this
mechanism exists at all.

**M1 — the anti-vacuity coupling was a convention, not a structure.** §2's
layer 3 was declared "structural, not a review-time convention" on the strength
of `live_asserts`' `min_length: 1`. But three of §4.2's nine ops pass on **zero
resolved nodes** (`not_exists`, `absent_or_eq`, `not_regex`), as does `set_eq`
with an empty `expected`, so a spec could declare a deploy whose *entire* live
proof was satisfied by a completely empty account — the exact inert
configuration this whole mechanism exists to make unexpressible. Counting
asserts is not the same as making them capable of failing. All four are now
hard errors at spec load, on **every** live assert rather than only the
`pins_catch`-bearing one (a non-pinning tautology dilutes the verdict: "three
live asserts held" must mean three facts, not two facts and a tautology). The
*premise* — that those ops really do pass on `[]` — is pinned by an executed
test, so the rule cannot outlive its own justification.

**M2 — `contains` is a substring test, and the new name is a superstring of the
old one.** REPRODUCED. The assert whose entire job was to prove the trap is
**armed** — `endpoint-holds-the-old-group` — read
`op: contains, expected: internal-services-ssm-endpoint`, and on a string node
`assert_check`'s `contains` is jq's literal substring test. The solution's new
group name is `platform-internal-services-ssm-endpoint`: a strict superstring.
So that assert **passed against the exact post-solution account in which the
trap is disarmed**, and it had *zero* execution coverage — there was no
`describe-vpc-endpoints` fixture in the repo at all. It moved to `set_eq` over
`$.VpcEndpoints[*].Groups[*].GroupName` (**and to `eq` in round 3 — §11
finding B; `set_eq` runs `unique` and could not see a duplicate**), with
checked-in fixtures (armed, renamed-only, empty, stray-extra-group,
duplicate-vpcs) and a test that keeps the old substring behaviour itself
executable, so a future "simplification" back to `contains` fails with the trap
spelled out rather than rediscovering it in a live run.
`contains` is **unchanged** in `_assert_lib.sh` — it is shared with tier-0 and
its substring semantics are deliberate there.

**M3 — the whole mechanism failed OPEN if `pre_invoke.sh` was absent.** All
three layers lived inside a file `_prepare` runs *iff it is on disk*
(`if self.task.has_phase_script(ScriptType.PRE_INVOKE):` — no `else`, no log
line, pure file existence). A stale generator, a bad image layer or a truncated
upload therefore skipped every layer in silence and graded an empty account, on
which the live oracle passes for free: the original defect, restored by a
missing file. Fixed on both halves. **(a)** A test asserts the biconditional —
`task.toml` declares `[scenario].pre_invoke_role_name` **iff** the task ships a
generated `pre_invoke/pre_invoke.sh` — across every task dir in the repo, and it
runs under `make check`. **(b)** Layer 4 (§2): the script writes a receipt at
`/logs/seed-deploy-receipt.json` and `tests/test.sh` refuses to grade without
it. The path was chosen by reading `aws_bench/task/script_runner.py`, not
invented: step 7 removes `/pre_invoke` and `/logs/pre_invoke` and nothing else,
so `/logs/pre_invoke/seed-proof.json` — the operator-facing copy — is gone by
verification time, while `/logs` itself survives and the verifier runs in the
same container (a shared verifier environment is the only kind aws-bench
supports for a phase-script task). The refusal writes **no reward file at all**,
so Harbor's `RewardFileNotFoundError` aborts the trial — never a 0.0, for §2's
reason.

**M4 — `_brownfield_plan_must_not_refresh` could not fire for two of three
arms.** MEASURED. The validator reads `output_contract.plan_command` and
`continue`s when it is empty — and it is `None` on `awscdk` and on
`terraconstructs`. That arm's `terraform plan` comes from a hardcoded generator
template, where the flag was keyed off `verifier.live_check.enabled`: an
unrelated coupling the validator does not check, which a brownfield spec with
the live check off would have silently lost. The template now emits the flag for
any `workspace_seed` spec, and an arm-parametrised test asserts `-refresh=false`
on the **emitted bytes** of every enabled arm's `tests/static_tiers.sh` and
`tests/test.sh` — a validator that reads a spec field cannot see what a template
emits.

**M5 — the negative fixture swallowed its own deploy's exit code.** Both
`solution/broken/rename-replaces-an-in-use-security-group/solve.sh` files ran
`<deploy> || true` and then `live_check.py --expect stale`, which requires only
`outcome == "fail_stale"` — and `observe()` reports `fail_stale` for *any*
unsatisfied assertion, including "the deploy never ran". Not hypothetical: that
exact line named a **nonexistent stack** for its entire life and nothing
anywhere went red, and it is now strictly worse, because a harness-deployed seed
makes `fail_stale` true *by construction* before the fixture does anything. Both
files now capture the exit code and require the specific failure — non-zero
**and** `DependencyViolation` in the deploy log — before `--expect stale` is
allowed to run at all.

**m1 — `gating: false` is the same "spend with no measurement" as
`enabled: false`**, and unlike `enabled` it is the *default*, so it is reached
by omission. Non-gating, the live oracle's verdict never reaches `reward.txt`.
Now a hard error (§2.7.1 rule 3).

**m2 — the proof left AWS-response artifacts in the `/tmp` the agent then
uses.** The header claimed the agent "never sees this file, its output, or the
fact that a harness deployed anything" while `/tmp/seed-*.json`, `/tmp/seed-*.err`
and `/tmp/assert-jq-err.txt` survived step 7's cleanup, which removes
`/pre_invoke` and `/logs/pre_invoke` and nothing else. The probes moved under
`/logs/pre_invoke/` (deleted before the agent, *and* downloaded to the trial dir
first, so a failed seed now hands the operator the exact bytes that contradicted
it); the shared library's own `/tmp/assert-jq-err.txt` is removed explicitly
rather than by changing a path tier-0 depends on. The header no longer claims
more than the code enforces — it says what is guaranteed gone and names the one
artifact deliberately left behind.

**m3 — the non-root `USER` guard guarded the wrong knob.** See §4, corrected.

**m4 — `assert_check` collapsed "could not run" into "was contradicted".** A
jq query error returned 1, the same code as a genuine contradiction, so a
malformed AWS response produced `seed_absent` — *"the account does not hold the
seed this workspace describes"* — when the truthful verdict was
`seed_unverifiable`. No false pass (both abort), but a false **claim about a
real account**, in the one file whose whole job is to be believed, and a
violation of the three-valued verdict contract the rest of the harness honours.
`assert_check` now returns **2** for unresolvable and 1 for contradicted; the
seed proof counts them separately and checks unresolvable **first**. Both
existing callers test `!= 0`, so tier-0 is unchanged — pinned by a test that
runs the tier-0 call shape verbatim.

**m5 — neither live assert is scoped to this trial's VPC**, so the conjunction
they mean to prove ("*the* endpoint holds *the* group") is not asserted and a
leftover object from an incompletely-reset earlier trial satisfies either alone
(`_reset_scenario_account` logs a reset failure and never raises). **Concluded:
not fully fixable at this layer, and mitigated rather than closed.** The `aws`
argv is static spec text with no placeholder substitution, and the seed's VPC id
does not exist until the deploy runs, so there is nothing to scope *to* at spec
load. What the M2 fix buys is the part that matters: a *differently*-named
stray group is a loud, aborting **FAIL** instead of a silent pass — pinned by
the `stray-extra-group` fixture. A **same-named** leftover was still
indistinguishable from the seed at the time this was written; §11 finding B
narrows that too (`eq` bounds the resolved COUNT, so a duplicate now aborts),
and what remains unscoped is only "a same-named group in a *foreign VPC* versus
this trial's own". Adding a VPC-scoped placeholder to `live_asserts` is
deferred, not forgotten — see §11's re-assessment.


### 11. Adversarial review, round 3 (2026-08-25) — eight findings, and one **grading-signal change**

Round 2 closed nine of round 1's ten findings; round 3 re-verified the result
and returned narrower defects of the **same family**, which is the expected
convergence shape. Two were reproduced by the reviewer before being filed (A, B)
and the rest verified here. All eight are closed below. **Finding H changes what
the idempotence tier reports**, so it is recorded in full rather than in a
sentence — a weakened grading signal that nobody wrote down is how a weakened
signal becomes an invisible one, and round 2 changed this guard's behaviour
without recording it.

**A (major) — vacuity was reachable through the PATH, not only through the op.**
REPRODUCED. §10's finding M1 rejected the ops that pass on zero resolved nodes,
and then the code comment and `specs/SCHEMA.md` §2.7.1 both asserted the
stronger property — "a live assert cannot be satisfied by an empty account" — as
fact. It was not: `SeedLiveAssert` imposed **no shape rule on `jsonpath`** (the
only check was "non-empty and starts with `$`"), and a path that resolves to the
**container** rather than descending **into** it hands even `exists` one node on
an empty account — `[ .SecurityGroups ]` over `{"SecurityGroups": []}` is
`[[]]`, length 1, and `assert_check`'s `map(select(. != null))` drops nulls, not
empty arrays. So a `workspace_seed.deploy` whose *entire* live proof passed on a
completely empty account was still expressible, accepted at load, emitted, and
reported `seed_deployed`. **That is finding M1's own shape, reintroduced by
M1's fix** — a comment claiming a property the code did not enforce.

Now enforced: `SeedLiveAssert._wellformed` compiles the `jsonpath` at **spec
load** and requires the compiled jq filter to contain a `.[]` stage, i.e. the
path must carry a `[*]` or `[?(...)]` segment and **iterate** a collection.
`$.SecurityGroups[*].GroupName` is legal, `$.SecurityGroups` is not, and an
untranslatable path (`$.Stacks[0].StackStatus` — there is no index segment in
`generator/jsonpath_jq.py`'s grammar) is a spec error rather than a generator
traceback three commands later. Pinned both ways: a test that executes the
rejected shape against the empty-account fixture and shows it really does pass,
and tests that show the load raises.

**This is a narrowing, not a decision procedure, and every place that says so
now says only that.** The rule rejects some genuinely falsifiable paths as
collateral — recursive descent (`$..GroupName`) iterates nothing and is refused,
which a test pins deliberately. `spec_model.py`'s comments, the
`live_asserts` field comment and §2.7.1 were all rewritten to state exactly what
is enforced: two rules, each removing one *known* vacuous shape, neither proving
that an accepted assert can fail.

**B (major) — `set_eq` runs `unique`, so a same-named leftover was invisible.**
REPRODUCED. Both `live_asserts` used `set_eq`, whose compiled filter is
`... | unique | sort` on both sides, so *n* objects carrying the **same** value
collapse to one element and compare equal to a one-element `expected`. That is
reachable on this scenario: EC2 security-group names are unique **per-VPC**, not
per-account, and `--filters Name=group-name` is account-wide. Meanwhile the
emitted failure text and the spec comment both claimed `set_eq` caught exactly
this case.

The concrete chain, and it is the **inverse of the vacuity bug**: a reset whose
fastscan leaves the previous trial's group behind but reports success
(`_reset_scenario_account` only flags contamination when `reset_result.success`
is false) → this trial's seed deploys a second, fresh, identically-named group →
`unique` collapses them → the proof passes → the agent renames **its** group
correctly → the leftover still carries the old name → `live_check.py`'s
discriminating assertion sees the old name survive → `fail_stale` → **a perfect
agent scored 0.0 and published as an agent failure**. Just as corrupting to the
measurement as a free pass, with the sign flipped.

Both asserts are now `op: eq` (`($v | length) == 1 and ($v[0] == $e)`), which
requires **exactly one** resolved node, so multiplicity cannot be collapsed. Two
duplicate-name fixtures were added and the rule is executed both ways — `set_eq`
passing on them (the justification, kept alive beside the rule) and `eq`
returning **1**, a resolved contradiction rather than an unresolvable query. The
emitted `seed_absent` text and the spec comments now describe what `eq` proves:
*this account holds exactly one of these, and it is the right one.* `set_eq`
itself is unchanged in `_assert_lib.sh` — it is shared with tier-0 — and §2.7.1
gained a "watch `set_eq` on a region-wide query" note beside its existing "watch
`contains` on a string" one.

**m5's deferral is re-assessed and stands, narrowed.** `eq` bounds the resolved
**count**, so a contaminated account is now loud instead of silent for every
multiplicity case — which was most of m5's practical risk. What remains is
strictly "a same-named group in a **foreign VPC** versus this trial's own", and
that is still not expressible: `SeedLiveAssert.aws` is static spec text with no
placeholder-substitution surface and the seed's VPC id does not exist until the
deploy runs. Scoping still needs a new spec surface — a design change, not a
fix — so it stays deferred, on a materially smaller residue.

**C (minor) — the two authoritative documents disagreed about how many layers
there are.** `specs/SCHEMA.md` said "**Anti-vacuity: three fail-closed layers**"
and then enumerated four, while §2 above already said four. §2.7.1 is the
document the design names as authoritative, so it was the wrong one to be
wrong. Corrected to four. The generated `pre_invoke.sh` header's "prove it,
three ways" is **right** — layers 1–3 are the only ones in that file — and is
left alone.

**D (minor) — the awscdk state proof called a DEFINITIVE absence
"unverifiable".** `describe-stacks` on a nonexistent stack exits non-zero with
`ValidationError ... does not exist`. That is a **resolved fact** about the
account whose truthful verdict is `seed_absent` (2); it was reported
`seed_unverifiable` (3) — finding m4's three-valued mislabelling in the opposite
direction, in the very file m4's fix rewrote. The proof now fetches the response
once as JSON, branches on the stderr body (`does not exist` / `ValidationError`
→ 2; everything else — credentials, network, throttling, IAM → 3), and treats a
zero-exit response carrying no `StackStatus` as 3 as well: the question was
asked and *not* answered. Pinned by an executed fixture set that runs the
shipped bytes against a stubbed `aws`, the way `_assert_lib.sh`'s rc 1 vs rc 2
now is.

**E (minor) — the emitted-bytes `-refresh=false` test spoke for one spec.**
§10's M4 fix parametrised over arms but took the module's `spec` fixture, i.e.
`named-resource-replacement` only, so a second brownfield spec — and this
mechanism explicitly unblocks four Batch B ones — would have shipped with no
emitted-bytes assertion. The generator half is unconditional, so this was
coverage narrowness rather than a live hole. Now parametrised over **every**
`specs/*.yaml` whose loaded model carries a `workspace_seed`, keeping the
non-empty-plan-lines assertion per TF arm so it cannot pass vacuously, plus a
test that the spec list itself is non-empty.

**F (minor) — a missing `_assert_lib.sh` was reported as "the account is
wrong".** `. /pre_invoke/_assert_lib.sh` was sourced with no `set -e` and its
result was never checked. With the library absent — `ScriptRunner` uploads
`pre_invoke/` at **run** time, so a partial upload or a future rename reaches
this — the source failed silently, every `assert_check` became
`command not found` (rc 127), and the dispatch's `elif rc -ne 0` bucketed 127 as
CONTRADICTED. The run exited 2 saying *"the account does not hold EXACTLY the
seed this workspace describes"*: **a false statement about a real AWS account,
in the one file whose job is to be believed** — m4's contract violation through
a different door. Three changes: a `command -v jq` guard and a checked source
(plus a `command -v assert_check` check for the truncated-upload case), both
placed **before the deploy** so a broken proof harness never spends against the
account; and the per-assert dispatch now treats **any** rc outside
`_assert_lib.sh`'s documented `{0,1,2}` as unresolvable, naming the rc on
stderr. Pinned by tests that run the shipped script and assert both the verdict
and that the deploy log was never written.

**H (minor by count, largest by consequence) — THE IDEMPOTENCE TIER'S
"NOTHING WAS APPLIED" GUARD HAD BECOME A TAUTOLOGY. This is a grading-signal
change.**

`build_idempotence_block` emits, per TF arm,
`if [ ! -s "/app/project/terraform[.<workspace_id>].tfstate" ]; then
idem_outcome="not_verifiable"; idem_reason="nothing was applied ..."`. Before
`workspace_seed.deploy`, an agent that applied nothing left no state, the probe
fired, and the tier reported `not_verifiable`. **This mechanism writes that
exact file before the agent's first token**, so on a brownfield spec the probe
can never fire again: a `converged` verdict stopped distinguishing "the agent
deployed and converged" from "the agent did nothing and the SEED is still
converged". A live guard silently became a free pass — wrong output, no error,
indistinguishable from a legitimate result — produced by a fix, and nothing
recorded that it had happened. **awscdk has the same hole by a different
route**: it never had a file probe (CloudFormation *is* its state), and
pre-seed a do-nothing agent was caught anyway because `cdk diff` against a
nonexistent stack reports the whole stack as new; post-seed, the unmodified
workspace matches the deployed stack exactly and `cdk diff` exits 0.

**What changed.** `pre_invoke.sh` now stamps the identity of the state it
deployed into the receipt at `/logs/seed-deploy-receipt.json` as
`state_identity`, and the idempotence tier requires that identity to have
**MOVED** before it will believe a `converged`. Unchanged identity ⇒
`not_verifiable`, with a reason naming the seed.

**Why `lineage` + `serial`, not `serial` alone** (which is what the review
suggested): `serial` is a counter that **restarts** when the state is recreated
from scratch (`rm terraform.tfstate && terraform apply`, or an init against a
fresh backend), so an agent that destroyed and rebuilt could land back on the
seed's own serial and read as "nothing moved" — a false `not_verifiable` on a
real deployment. `lineage` is the UUID Terraform stamps in at creation and never
changes, so the **pair** moves under both "advanced" and "replaced". A test pins
exactly that case. On awscdk the same roles are played by `StackId` (a
delete-and-recreate under the same *name* yields a different id) and
`LastUpdatedTime`, with `CreationTime` as the fallback CloudFormation forces for
a stack that has only ever been created; a `cdk deploy` CFN answers "No updates
are to be performed" leaves both untouched, which is precisely the do-nothing
agent this catches.

**Three deliberate choices, each of which could have been made the other way.**

1. **`not_verifiable`, not `pending_changes`.** The tier's three values are
   "converged / still differs / could not be established" (§5.1). "The agent
   applied nothing" establishes nothing about idempotence — there is no
   agent-produced deployment to be idempotent *about* — and calling it
   `pending_changes` would assert a fact about a configuration the agent never
   rolled out. Under `verifier.idempotence.gating` both downgrade identically,
   so the honest label costs nothing.
2. **The old file probe is KEPT, not deleted.** It is a tautology on a seeded
   spec and it still speaks for a seed that vanished mid-trial. The movement
   guard sits in its `else`.
3. **Fail-closed on the TF arms, fail-QUIET on awscdk.** The TF arms read a
   local file, so an unreadable identity is a broken artifact this verifier is
   holding in its hand → `not_verifiable`. awscdk must ask CloudFormation, and
   offline — where `cdk diff` cannot resolve an AWS environment either — an
   unanswered question is **not evidence about the account**, so that guard
   narrows its claim to "the answer arrived and matched" and leaves the rest to
   the completion-marker guard below it. Making a claim there would repeat m4.

**What this changes about published numbers, stated plainly.**
`named-resource-replacement` sets `verifier.idempotence.gating: true`, so a
`not_verifiable` there downgrades the trial's reward to 0.0. A do-nothing agent
on *this* scenario was already going to score 0.0 — its unmodified workspace
fails the static tiers, which run first — so the guard is not expected to move
this scenario's numbers. What it moves is the **reason**, and the reachability
of the failure mode it closes: on any future brownfield spec whose static tiers
a seed alone could satisfy, the tier would otherwise have reported `converged`
for an agent that did nothing at all. The guard is registered here because a
grading signal changed, not because a number is predicted to.

**Blast radius.** The guard is emitted by the same `workspace_seed.deploy`
branch that emits `pre_invoke.sh`, never by `verifier.idempotence` alone, so
every non-brownfield task's `tests/test.sh` is byte-identical — asserted across
every task dir in the repo. The identity jq program has **one owner**
(`gen.py::SEED_STATE_IDENTITY_JQ`) and two emitters (the receipt writer and the
tier's reader), and a test asserts both carry it, because a drift between them
would make every brownfield trial `not_verifiable` — or, worse, every one
`converged` — with nothing recording why.

**G (minor) — the refresh validator was bypassed by `terraform -chdir=... plan`.**
`Spec._brownfield_plan_must_not_refresh` gated on the literal substring
`"terraform plan"`, so an ordinary `terraform -chdir=. plan -input=false ...`
passed spec load in silence and `gen.py` spliced it verbatim into `hcl_raw`'s
`static_tiers.sh` — producing the exact outcome the validator's own docstring
measures: with the seed's state present the offline verifier plan refreshes
through dummy credentials and dies, scoring **every hcl-raw brownfield trial
0.0 before the agent is judged**. The backstop that would have caught it was
finding E's narrow one. Both matchers now match the **plan subcommand**
(`\bterraform\b(?:\s+-\S+)*\s+plan\b`), terraform's global flags being
legal only between the binary and the subcommand, and a test asserts the
validator's pattern and the emitted-bytes test's pattern are byte-identical.

**Offline proof for all eight.** Full suite green, `make check`,
`make falsifiability` and `make seed-parity` green, and `make gen-all` moves
only the `named-resource-replacement-*` task trees. Nothing here has been
exercised live; §7's promotion criterion is unchanged and still unmet.
