# Intent-spec YAML schema

One YAML file per scenario under `specs/<scenario-id>.yaml` (except the
generator-testing fixture at `specs/_toy/toy-ssm-parameter.yaml`, which is
never a benchmark scenario — see its header comment). `../generator/` reads
this file and is the **only** thing allowed to write into
`../tasks/<scenario-id>/{awscdk,hcl-raw,terraconstructs}/` and
`../oracles/**/<scenario-id>/`. Hand-editing generated output is a bug.

This document is the contract the generator (Slice C) and the seed-scenario
authors (Slice D) both code against. Companion example:
[`specs/_toy/toy-ssm-parameter.yaml`](_toy/toy-ssm-parameter.yaml) — read it
alongside this doc; every field below has a concrete instance there.

Design inputs: `docs/aws-bench-datasets-guide.md` §2/§6 (task anatomy, the
`create-eks-cluster` reference task), `docs/iac-abstraction-aws-bench-plan.md`
Phase 1 (generator, M2; seed-scenario table; Tier-0.5 amendment),
`iac-abstraction-benchmark-prereg.md` §3 (oracle tiers), §5 (catch taxonomy),
§6 (prompt parity), `DECISIONS.md` Amendment 2/3 (arm set, build-context
contract, the falsified-catch lesson).

---

## 0. Top-level shape

```yaml
id: <kebab-case scenario id>
title: <string>
workspace_title: <string>         # §0.1, required iff `steps:` or `workspace_seed:`
                                  #       is set, else forbidden
workspace_id: <kebab-case>        # §0.1, required iff `steps:` or `workspace_seed:`
                                  #       is set, else optional (defaults to `id`)
agent_deny_vocab: [<string>, ...] # §0.1, optional, default []
difficulty: <1|2|3>
services: [<string>, ...]        # boto3 service ids, matches aws_services convention
arms: {...}                       # §1
instruction: {...}                # §2
seeded_files: [{...}, ...]        # §2.5, optional, default []
workspace_seed: {...}             # §2.7, optional, default null (BROWNFIELD)
catches: [{...}, ...]             # §3
oracle: {...}                     # §4
verifier: {...}                   # §5
provenance: {...}                 # §6
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Kebab-case, matches `^[a-z][a-z0-9-]*$`. Becomes the directory name under `tasks/`, `oracles/rego/`, `oracles/cfn-guard/`, and `oracles/<id>/` (§8). Must equal the spec's own filename stem (`specs/<id>.yaml`), enforced by the generator at load time — this is what lets the generator refuse to run against a renamed-but-not-moved file. |
| `title` | string | yes | Short human title, shown in any results viewer. Written to `task.toml [task] description` on a **single-step greenfield** spec; on a multi-step *or brownfield* spec that slot carries `workspace_title` instead and the full title moves to `task.toml [metadata] scenario_title` (both host-side metadata; the task dir itself is never uploaded to the agent). Not used in `instruction.md` — the instruction body is `instruction.shared_body`, not `title`. **Is** used as the skeleton header for a single-step greenfield spec — see §0.1. |
| `workspace_title` | string | **required iff `steps:` or `workspace_seed:` is set**; forbidden otherwise | The header comment stamped into each arm's skeleton entry file under `environment/`. §0.1. |
| `workspace_id` | string | **required iff `steps:` or `workspace_seed:` is set**; optional otherwise (defaults to `id`) | The agent-visible scenario **name** — the NAME half of what `workspace_title` does for the SENTENCE half. Kebab-case, `^[a-z][a-z0-9-]*$` (it becomes a construct id and a synthesized stack *directory* name). §0.1. |
| `agent_deny_vocab` | list[string] | no, default `[]` | This scenario's own trap/foreshadowing vocabulary — plain substrings that must not reach its agent before it gets there on its own, checked on top of the global deny-list. §0.1. |
| `difficulty` | int, `1`–`3` | yes | 1 = single-resource, 2 = multi-resource wiring, 3 = cross-service (prereg §5 difficulty gradient). The generator maps this to `task.toml [metadata] complexity`: `1→Atomic, 2→Sequential, 3→Orchestrated` — a generator convention, not a spec field; do not add a `complexity` field to the spec. |
| `services` | list[string] | yes, ≥1 | boto3 service client ids (e.g. `ssm`, `iam`, `lambda`), lower-case. Written into every generated `task.toml [metadata] aws_services`. Purely descriptive in v1 (no live boto3 call ever validates against it — that upstream `test/aws_service_catalog.ts` check is aws-bench-datasets' own CI, not ours), but keep it accurate; a later live-check phase (§5) will care. |

### 0.1 `title` vs `workspace_title` — the skeleton header is agent-visible

The generator stamps a one-line header comment into every arm's generated
skeleton entry file, and into the awscdk app's CloudFormation stack
`description`:

| Arm | File | Site |
|---|---|---|
| awscdk | `environment/workspace/lib/scenario-stack.ts` | `generator/gen.py` `awscdk_stack_skeleton()` |
| awscdk | `environment/workspace/bin/app.ts` (`description:`) | `generator/gen.py` `awscdk_bin_app_ts()` |
| hcl_raw | `environment/workspace/main.tf` | `generator/gen.py` `hcl_raw_main_tf()` |
| terraconstructs | `environment/app/main.ts`, `environment/app/lib/scenario-stack.ts` | `generator/gen.py` `terraconstructs_main_ts()` / `terraconstructs_stack_skeleton()` |
| *(all arms)* | `task.toml [task] description` — **host-side only** | `generator/gen.py` `build_task_toml()` |

Everything under `environment/` is `COPY`'d into the agent image by the arm
Dockerfile, so **the header is the first thing the agent reads** — it is
prompt surface, not metadata. A scenario `title` legitimately describes the
whole arc (`"…: deploy, confirm, modify, re-deploy (day-2 iteration)"`); putting
that arc in the skeleton foreshadows step 2 exactly as loudly as the prompt
would, which Amendment 26 §7 rule 2 and
`docs/design/multistep-trial-investigation.md` §5 rule 2 forbid ("never place
later-step material in `environment/` — that IS the image the agent lives in").

**Two spec forms hit this, for the same reason with different content.**
A multi-step `title` describes the *arc*; a brownfield (§2.7) `title` describes
the *change*, and in practice names the very property of the shipped config that
carries the pitfall. The pilot's own first draft is the worked example — and it
shipped, and a verifier caught it:

> `title: "Rename an explicitly-named, in-use security group and roll it out"`

`explicitly-named` and `in-use` are exactly the two facts that
`named-resource-replacement`'s `seed_asserts` declare to be THE POISON, and
which §2.7 prompt rule 4 requires the agent to *discover from the configuration*.
Stamped through `workspace_header()` they landed in `bin/app.ts`'s CFN
`description` and `main.ts`'s header comment — two of three arms, because the
third arm's entry file *is* the seed and carries no generator header at all. So
the leak was also **arm-asymmetric**: two arms were handed a hint inside the
cross-arm comparison the scenario exists to measure.

Therefore:

- **Single-step greenfield spec:** `workspace_title` is *forbidden*; the header
  is `title`, byte-for-byte as before this field existed.
- **Multi-step spec:** `workspace_title` is *required* and is used instead. It
  must be terminal — describing only what step 1 is asked to build, implying no
  future change.
- **Brownfield spec (`workspace_seed:`, §2.7):** `workspace_title` is *required*
  and is used instead. It must describe only **what the workspace already is**
  (`"Internal services network"`), never what is about to change about it, why
  it is interesting, or any property of it the prompt is not allowed to state.

Making it required rather than defaulting (to `title`, or to `id`) forces the
author to *choose* a safe header instead of inheriting a leaking one by
omission — which is precisely how the brownfield leak above happened.

`task.toml [task] description` is the one **non**-`environment/` row in that
table, and it is defence in depth rather than a live leak: Harbor uploads no
task file into the agent environment (`harbor/trial/trial.py`), so `task.toml`
is host-side metadata read only by the publisher/registry. It uses
`workspace_header()` anyway, because it is the last generator-stamped copy of
the whole arc left inside the task dir and "it's only metadata" is exactly the
reasoning that put the arc into the agent's own `main.tf` (Amendment 27 §5.1).
The full title is not lost — a multi-step *or brownfield* task.toml carries it as
`[metadata] scenario_title`.

Enforced by `Spec._workspace_title_required_where_header_is_prompt_surface`
(spec load time) and, against the real emitted bytes, by two deny-list scans of
every file under a task's `environment/`:

- `generator/tests/test_multistep_emission.py::test_step_one_environment_leaks_nothing_about_step_two`
  — step-2 vocabulary, over each multi-step task;
- `generator/tests/test_workspace_seed.py::TestBrownfieldPromptSurface`
  — pitfall-mechanism vocabulary **plus a verbatim-`title` pin**, over *every*
  brownfield task and its `instruction.md`. The verbatim pin is the direct
  regression guard for the leak quoted above: it fails on the literal `title`
  string appearing anywhere the agent can read, independent of which words that
  title happens to contain, so it cannot rot as future brownfield specs invent
  new ways to describe their change.

#### 0.1.1 `id` vs `workspace_id` — the scenario NAME is agent-visible too

Everything above is about the header *sentence*. The same split is needed for
the *name*, and for exactly the same reason — a verifier found the second half
of the leak after the first half was fixed.

**The rule, in one sentence:**

> The spec **`id` is operator-facing and MAY name the pitfall**. Every name the
> **agent** can see must be named for the **current step's goal** only.

**The leak test, in one question:** *does this name reveal more than this step's
own prompt does?* If yes, it is a leak — whatever kind of thing it is (a title,
an id, a construct id, a directory).

`id` is a genuinely useful operator name: it is the spec filename, the `tasks/`
and `oracles/` directory name, the `task.toml [metadata]` key, the row label in
a results table. Naming the pitfall there is *correct*. But `id` was also
stamped into `environment/`, which is the agent's image:

| Site | Arm | Was |
|---|---|---|
| `environment/app/main.ts` — `new ScenarioStack(app, …)` construct id | terraconstructs | `spec.id` |
| `environment/app/main.ts` — `gridUUID` | terraconstructs | `spec.id` |
| `environment/preflight.sh` — `cdktf.out/stacks/<id>/` (×3), *also visible in the agent's own `npx cdktn synth` output* | terraconstructs | `spec.id` |
| skeleton/entry headers — `from specs/<id>.yaml`, `` `make gen SPEC=specs/<id>.yaml` `` | **all** | `spec.id` |

Two scenarios were shipping their own answer through those sites:

- **`named-resource-replacement`** — the id is not the change request ("rename
  the security group to X"); it is the **diagnosis** the agent is supposed to
  reach from the configuration. It reached awscdk and terraconstructs and *not*
  hcl-raw (whose entry file IS the seed, so it carries no generator stamp) —
  arm-asymmetric, inside the cross-arm comparison the scenario exists to
  produce.
- **`apigw-redeploy`** — the id **is step 2's verb**. Amendment 27's
  foreshadowing sweep grepped the hyphenated `re-deploy` only, so the id sailed
  through every guard while the step-1 prompt itself was clean.

So: `workspace_id` is the agent-visible name, on the same required/optional
rules as `workspace_title`.

- **Multi-step or brownfield spec:** *required*. An author must choose a safe
  name rather than inherit a leaking one by omission.
- **Any other spec:** optional, defaulting to `id` — **but the deny-list runs
  against the resolved value either way**. A single-step greenfield spec whose
  id would leak is *refused at spec-load time* until it declares an explicit
  `workspace_id`. An id that names only the open goal of its own prompt (e.g.
  `s3-lambda-log-retention`, whose prompt asks for exactly that) is fine as the
  default, and every such spec generates byte-identically to before this field
  existed.

The two current declarations:

```yaml
id: named-resource-replacement          # operator-facing: names the pitfall
workspace_id: internal-services-network # agent-visible: names the workspace

id: apigw-redeploy                      # operator-facing: names step 2's verb
workspace_id: hello-version-api         # agent-visible: names step 1's goal
```

**The deny-list.** `generator/spec_model.py` carries it, not a test module,
because a *validator* uses it: `AGENT_MECHANISM_DENY_PATTERNS` (names the fix,
the diagnosis, or the benchmark's own machinery) and
`AGENT_FORESHADOW_DENY_PATTERNS` (names a later step). Both classes apply to
`workspace_id` and `workspace_title`, since both are stamped into
`environment/`, which is present from turn one.

The two classes have different **scopes** when the sweep runs over emitted
bytes, and collapsing them makes the sweep either blind or useless:

| Surface | Mechanism/meta | Foreshadowing |
|---|---|---|
| `environment/**` (every byte the Dockerfile COPYs) | banned | banned |
| every step's prompt **except the last** | banned | banned |
| the **last** prompt (or a stepless task's `instruction.md`) | banned | allowed |

Step 02's own prompt *is* a change request and *does* ask for a re-deploy;
banning those words there would ban the scenario. Naming the *fix* is never
allowed, in any prompt.

Every separator-bearing pattern matches `-`, `_`, a space, **or nothing** —
`redeploy` as well as `re-deploy`. That one omission is the entire reason
`apigw-redeploy` survived Amendment 27's sweep, so it is an invariant with its
own test (`test_no_deny_list_pattern_requires_a_separator`) rather than a
convention: no pattern may write `[ _-]` without the `?`.

`agent_deny_vocab` extends the foreshadowing class per scenario, declared in the
spec so the words that would give a trap away are reviewed in the same file as
the trap (`apigw-redeploy`: `/status`, `mock integration`, `"routes": 3`;
`named-resource-replacement`: `DependencyViolation`, `ForceNew`,
`destroy-then-create`).

**The header stamps no longer cite the spec at all.** `from specs/<id>.yaml`
and `` `make gen SPEC=specs/<id>.yaml` `` became
`Generated skeleton -- generator/gen.py.` and `` `make gen` ``, uniform across
every scenario and arm. Rewriting the citation with `workspace_id` was rejected:
it would name a spec file that does not exist. These lines address a *bench
maintainer*, who holds the repo and gets the usage message from `make gen`
anyway; the id→workspace mapping is recorded host-side in
`task.toml [metadata] workspace_id`. Uniform beats scenario-varying here — a
stamp that is neutral for *some* scenarios would itself signal which ones have
something to hide.

**Enforcement.**

- `Spec._workspace_id_required_where_identity_is_prompt_surface`,
  `Spec._workspace_id_format`,
  `Spec._agent_visible_identity_is_deny_list_clean` (runs on the *resolved*
  value, so defaults are checked too), and
  `Spec._terraconstructs_artifact_path_matches_workspace_identity` (the
  synthesized stack directory is named by `workspace_id`; a mismatch would not
  fail loudly, it would score every solution — including the reference — a
  constant 0.0 against a nonexistent `plan.json`) — all at spec-load time.
- `generator/tests/test_scenario_identity.py` — the corpus-wide sweep over real
  emitted bytes: the id never appears agent-visibly, the vocabulary sweep in
  both scopes, arm symmetry, `arms/*/environment/**` names no scenario, both
  allowlists proven honest, and the pre-fix stamps replayed and required to
  fail.

**No exemption for the id, anywhere.** Both earlier guards scrubbed it before
scanning ("every header cites it"), and that is precisely why each missed the
leak its own deny-list already named. The scrub is now an *assertion*: what gets
scrubbed is `workspace_id`, whose cleanliness a validator guarantees, plus
tokens the agent's own prompt hands it — and *that* allowlist is derived from
the emitted prompt and re-proven per entry, so a token stops being scrubbed the
moment the prompt stops saying it. (`apigw-redeploy-api` is the one such token:
step 01's prompt says "named EXACTLY `apigw-redeploy-api`", so it reveals
exactly as much as the prompt does.)

---

## 1. `arms`

```yaml
arms:
  awscdk: true
  hcl_raw: true
  terraconstructs:
    enabled: <bool>
    reason: <string>
```

- `awscdk` and `hcl_raw` are **literal `true`** — not objects, not `false`.
  Both are primary arms (`DECISIONS.md` Amendment 2); every scenario runs on
  both. The generator asserts `arms.awscdk == true and arms.hcl_raw == true`
  and rejects the spec otherwise — there is no code path for optionally
  skipping a primary arm.
- `terraconstructs` is the only arm with a real choice, because it's the
  **limited-coverage third arm** (Amendment 2). `enabled` is a plain bool;
  `reason` is **required in both directions**:
  - `enabled: true` → `reason` cites the specific coverage-table entry in
    `arms/terraconstructs/README.md` §3/§4 that supports it (e.g. "storage.Bucket +
    cloudwatch.LogGroup, see README §4 s3-lambda-log-retention row").
  - `enabled: false` → `reason` states the gap (e.g. "no JSONata/QueryLanguage
    support in the Step Functions construct, see README §3").
  A `reason` that just says "yes" or "no" fails review; it must be
  independently checkable against the arm's own README the way Slice D's four
  seed scenarios already are.

---

## 2. `instruction`

```yaml
instruction:
  shared_body: |
    <multi-line NL prompt body, create-new-infra imperative>
  placeholders:               # optional, default []
    - name: <TOKEN_NAME>
      source: literal | scenario_export | pre_invoke_random
      value: <string>          # required iff source == literal
  per_arm:
    awscdk: { language_line: <string>, output_contract: {...} }
    hcl_raw: { language_line: <string>, output_contract: {...} }
    terraconstructs: { language_line: <string>, output_contract: {...} }  # required iff arms.terraconstructs.enabled
```

### 2.1 `shared_body`

The **single source of truth** for the natural-language prompt (prereg §6
prompt parity). Written in the imperative, create-new-infra style of
`aws-bench-datasets`' `create-eks-cluster/instruction.md` — describe the
desired end state, never the implementation method (aws-bench-datasets'
`rubrics/evaluator-prompt.txt` "instruction states what, never how" applies
here even though we don't run their rubric). Never paste a catch's threshold
or valid-value set into the body (`instruction_concision` house rule,
`aws-bench-datasets-guide.md` §6c example (a)) — e.g. ask for "10-day log
retention", never mention that 10 is invalid or list the valid enum.

The generator assembles the final per-arm `instruction.md` as:

```
<shared_body, placeholders substituted>

<per_arm.<arm>.language_line>

<ownership note -- generator/gen.py::ownership_note(), added 2026-08-06, finding G1>

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.

<optional agent-output.json fence, iff per_arm.<arm>.output_contract.json_fields is non-empty>
```

`shared_body` must **not** itself contain the target-language line or the
`/logs/agent/agent-output.txt` trailer — the generator injects both, which is
what makes parity structurally impossible to break (a hand-edited task dir
skipping this assembly is the one way to break it, and there is no
hand-editing path — see §0).

The ownership note (`generator/gen.py::ownership_note()`) is generator-
computed from `output_contract.entry_file`, not a spec field — it names
`entry_file` as the one file the agent owns/should rewrite and names the
arm's non-agent-owned bootstrap file (`bin/app.ts` for awscdk, `provider.tf`
for hcl_raw, `main.ts` for terraconstructs — `generator/gen.py`'s
`ARM_BOOTSTRAP_FILE`) as off-limits. Added by finding G1 (benchmark-
integrity review, 2026-08-06): every arm workspace ships a **non-agent-
owned bootstrap file** alongside `entry_file` — `bin/app.ts` (awscdk,
pre-existing), `provider.tf` (hcl_raw), `main.ts` (terraconstructs, the
latter two added by this fix) — carrying config an agent's *normal, fully-
expected* full rewrite of its own `entry_file` must never be able to
delete (an offline-provider/dummy-credential fixture for the TF-shaped
arms; the App/stack-instantiation wiring for all three). Before this fix,
`hcl_raw`'s `entry_file` (`main.tf`) carried its own provider bootstrap
inline, and `terraconstructs`' `entry_file` (`main.ts`) carried both the
`App`/provider bootstrap AND the resource logic in one file — a normal
agent solution that fully rewrote its own `entry_file` (unremarkable,
expected behavior; the instruction never mentions the fixture) silently
deleted the offline-plan fixture along with it, and `terraform plan` then
failed with `No valid credential sources found` / a 403 against real STS —
scoring an otherwise-**correct** solution 0.0. See §2.4's table below for
the corrected per-arm `entry_file`/bootstrap-file split, and
`generator/gen.py`'s `hcl_raw_main_tf()` / `terraconstructs_main_ts()` /
`terraconstructs_stack_skeleton()` docstrings for the full before/after.

### 2.2 `placeholders` (optional, default `[]`)

Three resolution modes, matching `aws-bench-datasets-guide.md` §1's three
`{{token}}` shapes, narrowed to what a fully-offline static-tier task
actually needs:

| `source` | Resolved | Use case |
|---|---|---|
| `literal` | **At generation time** — the generator substitutes `value` directly into `instruction.md` and no `{{token}}` survives into the generated file. | The default and expected mode for v1. Since the `anchor` scenario exports nothing meaningful (`scenarios/anchor/README.md`), there is no live CloudFormation export to defer to; region/account-style flavor text is baked in as a literal (e.g. a fixed `us-east-1`, or an illustrative dummy account id like `123456789012`). |
| `scenario_export` | **At trial runtime**, by aws-bench's own placeholder substitution against a scenario's CFN exports — the token is left as literal `{{token}}` text in the generated `instruction.md`, unresolved by the generator. | Forward-compat only. No v1 scenario needs this (the anchor scenario exports nothing); reserved for a future non-anchor scenario or the Phase 2 state track (prereg §11), where a task genuinely needs to reference a pre-existing live resource. If used, the generator does **not** validate the token resolves to a real export (it can't — that scenario may not exist yet) and `task.toml [verifier.env]`/`[solution.env]` must carry a matching `"{{token}}" = "{{token}}"` passthrough per `aws-bench-datasets-guide.md` §2, which the generator emits automatically for every `scenario_export` placeholder. |
| `pre_invoke_random` | **At trial runtime**, by a generated `pre_invoke/pre_invoke.py` that computes a value (e.g. an 8-hex random suffix) and writes it to `/logs/pre_invoke/placeholder.json`, mirroring the `{{<8-hex-of-task-id>-<Name>}}` convention in the guide. | The **only** legitimate reason a generated task gets a `pre_invoke/` directory (§8) — never file-seeding (see the note in §8). Use when the instruction needs a name that's unique per trial for realism (e.g. "create a parameter named `/app-<suffix>/greeting`") without hand-picking a collision-prone fixed string. The oracle's `structural_asserts` (§4) must then match a **pattern**, not an exact literal, for anything built from this token. |

Every `name` must be referenced by at least one `{{name}}` occurrence in
`shared_body` or a `per_arm.*.language_line`; the generator rejects an unused
placeholder (dead spec field) and a `{{token}}` in the body with no matching
`placeholders` entry (unresolvable at generation time).

### 2.3 `per_arm.<arm>.language_line`

One sentence, injected verbatim after `shared_body`. States the target
language/toolchain and nothing else — no instructions on *how* to write the
code, no hints about the catch. Example pair (see the toy spec for the third):

```yaml
awscdk:
  language_line: "Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs."
hcl_raw:
  language_line: "Author this as hand-written Terraform HCL (no modules)."
```

### 2.4 `per_arm.<arm>.output_contract`

What the agent must leave on disk, precisely enough that the generated
`tests/static_tiers.sh` (§8) can find it without guessing. Every generated
task's starter workspace ships an **empty skeleton** at `entry_file` — an
already-wired app/stack/root module with an empty body and a `// TODO` /
`# TODO` comment pointing back at the instruction — so the agent edits inside
a known scaffold rather than inventing app structure from scratch. This
mirrors `arms/awscdk`'s own workspace convention (`bin/app.ts` wired,
`lib/example-stack.ts` is what gets overwritten) and is the mechanism that
makes an **empty-harness** trial (prereg §2.2) still start from a working,
synth-able zero state.

```yaml
output_contract:
  entry_file: <path relative to /app/project, the file(s) the skeleton pre-wires>
  artifact_path: <path relative to /app/project, where the synthesized/planned artifact lands>
  build_command: <string, optional — awscdk ONLY. MUST be unset for terraconstructs
                  (gen.py injects that arm's compile gate itself, see below) and is
                  unused by hcl_raw>
  synth_command: <string>          # or `plan_command` for hcl_raw
  json_fields: [{name: <string>, description: <string>}, ...]   # optional, default []
```

**`build_command` and the terraconstructs compile gate.** For `awscdk` this is
an ordinary per-spec field (`npm run build`). For `terraconstructs` it must be
**omitted**: `generator/gen.py::build_static_tiers_sh` injects
`npx tsc -p tsconfig.json` unconditionally as that arm's first toolchain step —
the same unconditional-injection pattern it already uses for the arm's tf-plan
step — so the compile gate cannot go missing because a spec author forgot a YAML
key. Setting it anyway is a hard generation error. The compile is *also* chained
into `arms/terraconstructs/environment/app/cdktf.json`'s app command
(`npx tsc -p tsconfig.json && node main.js`, mirroring awscdk's
`npx tsc -p tsconfig.json && node bin/app.js`), so every synth an agent runs
re-type-checks by construction and can never execute stale emitted JS. See
`docs/ts-runtime-spike2-results.md`.

| Arm | `entry_file` | Non-agent-owned bootstrap file | `artifact_path` | commands |
|---|---|---|---|---|
| `awscdk` | `lib/scenario-stack.ts` (class `ScenarioStack`, resource logic only) | `bin/app.ts` — `App`/`ScenarioStack` instantiation; the generator rewrites its import/instantiation once per scenario, never per trial | `cdk.out/ScenarioStack.template.json` | `build_command: npm run build`, `synth_command: npx cdk synth --no-lookups --quiet -o cdk.out` |
| `hcl_raw` | `main.tf` (resource blocks ONLY — no `provider` block; see below) | `provider.tf` — the `terraform{}`/`provider "aws" {}` block + `skip_*`/dummy-credential fixture lines (byte-copied from `arms/hcl-raw/environment/workspace/provider.tf`, never per-scenario content) | `plan.json` | `synth_command` not used; `plan_command: terraform init && terraform validate && terraform plan -out=plan.tfplan && terraform show -json plan.tfplan > plan.json` |
| `terraconstructs` | `lib/scenario-stack.ts` (class `ScenarioStack extends AwsStack`, resource logic only) | `main.ts` — `App`/`providerConfig` bootstrap (incl. the offline `skip_*`/dummy-credential fixture and the mock-STS `endpoints` pointer), imports and instantiates `ScenarioStack`; regenerated every run, mirroring `awscdk`'s `bin/app.ts` | `cdktf.out/stacks/<id>/plan.json` where `<id>` is the generator-assigned stack id, always equal to **`workspace_id`** (§0.1 — the AGENT-VISIBLE scenario name, which falls back to `id` when a spec declares none; this path is agent-visible in `preflight.sh` and in the agent's own `npx cdktn synth` output, and `Spec._terraconstructs_artifact_path_matches_workspace_identity` refuses a spec whose `artifact_path` disagrees with it) — **not** `cdk.tf.json`: `generator/gen.py::build_static_tiers_sh` always appends a real `terraform init && terraform plan && terraform show -json` step after `synth_command`, chdir'd into the synthesized stack's own directory, so this arm is graded in the same plan-JSON shape `hcl_raw` is (see §4.2) | `synth_command: npx cdktn synth`; `build_command` **must be unset** — gen.py always injects `npx tsc -p tsconfig.json` as an explicit first toolchain step with its own reward-0.0 branch (see the `build_command` note above §8.3) |

**`entry_file` vs. the non-agent-owned bootstrap file (finding G1, fixed
2026-08-06):** every arm's workspace ships both. `entry_file` is what the
generator's own skeleton leaves an empty `// TODO` in and what a normal
agent solution is expected to (fully) rewrite; the bootstrap file is
regenerated by the generator on every run but **never** treated as
`entry_file`, is byte-copied/regenerated untouched regardless of what the
agent writes, and the generated `instruction.md` explicitly tells the
agent not to modify it (§2.1's `ownership_note()`). `hcl_raw` and
`terraconstructs` did not always have this split — see §2.1 above for the
failure it fixes.

`json_fields` (optional, default `[]`): declares the keys the agent must
write into `/logs/agent/agent-output.json`, **only** when the oracle's
`structural_asserts` (§4) genuinely cannot disambiguate which synthesized
resource to check without an agent-declared name (e.g. the instruction lets
the agent pick a resource name, and more than one resource of that type could
plausibly exist). If a scenario's asserts can locate every resource by type +
static structural shape alone (the common case — see the toy spec), leave
this `[]` and the generated `instruction.md` omits the
`agent-output.json` fence entirely (§2.1's assembly template treats the fence
as conditional on this list being non-empty). Do not add fields here "just in
case" — every field here is a hard requirement the generated `tests/check`-
equivalent (`static_tiers.sh`) will treat as a `output_contract` criterion
(mirroring `create-eks-cluster`'s `output_contract` criterion), and a missing
key fails the tier unconditionally.

`deploy_command` (optional, default `null`): the arm's REAL deploy command
(e.g. `terraform apply -input=false -auto-approve`). Used by **exactly one**
thing: a multi-step step declaring `pre_invoke.deploy_prior: true` (§2.6),
where the harness deploys the previous step's work before this step's agent
runs. It is spec-declared per arm rather than inferred from an arm→command
map in the generator, because guessing a deploy command is how a credentialed
harness action silently deploys the wrong tree. Setting it with no
`deploy_prior` step anywhere is a hard spec error — a real deploy command that
nothing ever runs is a trap for the next reader.

### 2.5 `seeded_files` (optional, top-level, default `[]`)

```yaml
seeded_files:
  - path: <string, relative to /app/project, no leading "/" and no "..">
    content: <string, written verbatim>
```

Added by the `apigw-openapi` scenario (2026-08-06) — the first spec needing
to ship a **read-only reference input** into the agent's workspace that
isn't the empty `entry_file` skeleton and isn't a per-arm non-agent-owned
bootstrap file (§2.4's table). Use case: a small OpenAPI spec, a placeholder
build artifact (e.g. a Lambda deployment package Terraform's
`aws_lambda_function` needs `filename` to point at — HCL has no
`Code.fromInline()`-equivalent), or any other fixed, scenario-supplied
document the instruction asks the agent to *read* or *build against*
without authoring it itself.

Each entry is written **identically into every enabled arm's workspace**
(`ARM_WORKSPACE_SUBDIR[arm]/<path>`, i.e. the same tree `entry_file` is
relative to) by the generator, **after** `write_environment()`'s
copytree+entry_file-overwrite step, chmod'd read-only (`0o444`) — this is a
best-effort, host-filesystem-level signal that the file is not meant to be
edited (not a hard sandbox guarantee; the generated `instruction.md` also
says so explicitly, via `ownership_note()`'s extension for this field). A
seeded file is regenerated (overwritten) on every `make gen` run, exactly
like `entry_file`'s empty skeleton or a bootstrap file — it is spec-derived
content, never hand-edited in place (§0).

Writing the file into the workspace directory is **not sufficient on its
own**: the arm Dockerfiles deliberately COPY *named* workspace paths (never a
blanket `COPY workspace/ ./` — see `arms/*/README.md` "Generated-task
workspace split"), so a file the generator adds is in the Docker build
context but not in the image. The generator therefore also patches the
generated task's `Dockerfile` (`gen.py::patch_dockerfile_workspace_copies`,
the same patch-the-copied-arm-file mechanism as the `preflight.sh` patches),
appending one `COPY <workspace-subdir>/<path> ./<path>` per uncovered file
under the arm's own agent WORKDIR. Without that step a seeded file is visible
only on the host — including to the host-side gates, which is what masked the
gap — and never to the agent, even though `instruction.md` names it
(`docs/design/poisoned-workspace-design.md` §9-B1, fixed 2026-08-20). The
invariant is enforced repo-wide by
`generator/tests/test_dockerfile_workspace_coverage.py`: every git-tracked
file under any `environment/<workspace-subdir>/` must be covered by that
environment's Dockerfile COPY set.

Validation (`generator/spec_model.py`):
- `path` must not be absolute and must not contain a `..` segment (workspace
  escape).
- `path` must not equal any enabled arm's `output_contract.entry_file` or
  known bootstrap filename (`bin/app.ts` / `provider.tf` / `main.ts`,
  mirroring `generator/gen.py::ARM_BOOTSTRAP_FILE`) — a seeded file must
  never collide with a file the generator or the agent already owns.
- `content` must be non-empty.
- `path` values must be unique within the list.

Every seeded file's existence is a **spec-level fact, not an arm-specific
one** — there is no per-arm seeding, and no `applies_to`-style filter,
because the whole point is that the same reference input is available
identically across arms (an arm that has no use for a given seeded file — a
placeholder Lambda package only `hcl_raw` needs, since `awscdk`/
`terraconstructs` both have `Code.fromInline()` — simply doesn't reference
it; that asymmetry lives in the *solution*, not in what's seeded). If any
`seeded_files` entries are declared, the generator appends one sentence
per entry to the assembled `instruction.md` (via `ownership_note()`, §2.1)
naming its path and marking it read-only reference input — this text is
identical across arms (computed once, from spec-level `seeded_files`), so
it does not threaten prompt parity even though it is technically part of
the per-arm `own_note` (which is itself allowed to vary per arm, since it
sits after the language line in the assembly template — §2.1's ordering
note).


### 2.6 `steps` (optional, **TOP-LEVEL** — a sibling of `instruction`, default `null`)

Added 2026-08-20 by the prompt-decomposition pass
(`docs/prompt-decomposition-audit.md`; `DECISIONS.md` Amendments 26/27). It is
listed here, inside §2, because it is primarily an **instruction**
decomposition — but it is a top-level key, not a child of `instruction`.

```yaml
steps:                                   # omit entirely for a single-step scenario
  - name: "01-initial-deploy"            # ^[0-9]{2}-[a-z][a-z0-9-]*$ ; consecutive, ascending
    min_reward: 1.0                      # optional on a non-final step (default 1.0);
                                         # MUST be omitted on the last step — see
                                         # "the hard gate" below
    instruction:
      shared_body: |                     # THIS STEP's work
        ...
      per_arm:                           # optional; per-arm language line for THIS step
        awscdk:        { language_line: "..." }
        hcl_raw:       { language_line: "..." }
        terraconstructs: { language_line: "..." }
    oracle:
      structural_asserts:                # NAMES from oracle.structural_asserts
        - rest-api-exists                # required on every step but the last;
        - deployment-exists              # MUST be omitted on the last step
      live_check:                        # optional; inherits verifier.live_check
        enabled: true
        gating: true
    pre_invoke:                          # optional harness action, see below
      deploy_prior: true
      timeout_sec: 1800.0
```

**Why it exists.** A single prompt that says *"build X, then change it to Y"*
measures day-1 authoring **with perfect foreknowledge**, which is the one
condition a real day-2 change never has. An agent told about Y up front
designs X so Y is trivial, or authors the final shape in one pass — and a trap
that only fires on a *second* apply against an *existing* deployment never
fires at all. `steps` reveals the second intent only when it is due:
`steps/<name>/instruction.md` lives host-side and is read on demand at that
step's agent invocation, and the task directory is never uploaded to the
container. That is what makes the guarantee mechanical rather than a
convention.

**Minimum 2 steps.** A 1-step "multi-step" task is refused: it moves every
task checksum and equipping hash for no measurement gain (`DECISIONS.md`
Amendment 26 §6 explicitly declines to normalize single-step tasks).

**Prompt assembly.** Each step's prompt is
`step.instruction.shared_body` → the spec-level `instruction.shared_body` →
the language line → the ownership note → the live-credentials note → the
trailer → the JSON fence. Both bodies, because **sessions are fresh per step**
(Amendment 26 §1): constraints stated only at step 1 would be invisible to
every later step's agent. Step-work first, because it is what the agent is
being asked to *do*; the spec-level body reads as standing constraints that
qualify it — write it that way.

The spec-level `instruction.shared_body` of a multi-step scenario is therefore
**never delivered on its own**, and must not name a route, an integration
type, a revision, or anything else that belongs to one particular step.

**Per-arm language lines.** `steps[].instruction.per_arm.<arm>.language_line`
overrides `instruction.per_arm.<arm>.language_line` for that step only. This
is not cosmetic: `apigw-redeploy`'s spec-level awscdk line named
`MockIntegration` — the *day-2* integration type — which leaked the step-2
intent into the step-1 prompt on **one arm only**, a foreshadowing defect and
an arm-parity defect at once. Declare the line explicitly on every arm at
every step; the inheritance fallback exists for scenarios where no step
differs, not as the normal shape.

**Parity** (§8.2 point 2) is checked **per step**: everything before the
language line must be byte-identical across arms *for the same step*. Arms may
carry different per-step language lines; they may not carry different bodies.

**The oracle is a projection, never a second definition.**
`steps[].oracle.structural_asserts` is a list of **names** drawn from the one
spec-level `oracle.structural_asserts`. The generator emits one
`steps/<name>/tests/static_tiers.sh` per step running that projection.

- Every step but the last **must** name its subset. Inheriting the full suite
  would grade an intermediate state against the FINAL state's asserts, which
  no correct intermediate solution can satisfy.
- The last step **must omit** the key, i.e. run the **full** suite. That is
  what makes a multi-step scenario's terminal grading identical to what its
  single-step form graded, and what lets the reference solution and every
  `solution/broken/<catch>/` fixture keep proving exactly what they proved.
- An assert whose own `description` describes the later change (e.g.
  *"backing the day-2 /status route"*) is **step-N-only oracle text** and must
  live only in that step's projection.

**The `min_reward` hard gate.** Omitted, it defaults to `1.0` on every
non-final step: the next step's prompt never fires unless this one verified
green (`harbor/trial/multi_step.py::_should_stop_after_step`). A change
request whose starting state was never actually built is not a measurement of
anything. The final step **must omit** `min_reward` — there are no remaining
steps to gate, so the trial-level oracle is the gate; declaring it there is
**rejected at spec load** (`Spec._steps_wellformed`) rather than silently
dropped by the emitter, exactly as `oracle.structural_asserts` is rejected on
the final step. An author who genuinely wants an ungated intermediate step writes
`min_reward: 0.0` — always satisfied, and explicit, so "no gate" is never the
result of forgetting a key.

**`live_check` per step.** Omitted, a step inherits
`verifier.live_check.{enabled,gating}`. A step may only **narrow** the
spec-level check, never introduce one: `module`/`hand_authored`/
`agent_role_name`/`concurrency_mode` are spec-level facts (one container, one
account, one reset), and a step-level live check without them would ship the
generated not-implemented stub as that step's oracle. Each live-checked step
carries its **own hand-authored** `steps/<name>/tests/live_check.py` —
step 01's must not mention anything from step 02.

**`pre_invoke` — the declarative harness action.** `deploy_prior: true` emits
`steps/<name>/pre_invoke/pre_invoke.sh`, run before that step's agent with
`[scenario].pre_invoke_role_name` credentials staged
(`cdktn_bench/trial.py::CdktnMultiStepTrial._run_step_pre_invoke`). It runs
that arm's `output_contract.deploy_command`, which the spec must declare per
arm (§2.4) — the generator refuses to guess a real deploy command. It cannot
be declared on the first step (there is no prior work to deploy). `timeout_sec`
(default `1800.0`) is emitted as the task-level `[pre_invoke] timeout_sec`,
sized to the **largest** value any step declares, because that one value
applies to every step and aws-bench's own default of 600 s is far too short
for a real deploy (`DECISIONS.md` Amendment 26 draft addendum (a)).

**Opting out — the agent deploys instead.** Amendment 26 §2 makes the harness
the *default* deployer, and explicitly allows a spec to declare no
`pre_invoke` at all where the deploy loop **is** the measurement.
`apigw-redeploy` does exactly that, in both steps: its headline catch is
`predicted_tier_caught: "live"` and is discriminated only by *the agent's own*
second apply producing no new deployment. That opt-in works because Harbor
keeps ONE container alive across every step and uploads a step workdir only if
`steps/<n>/workdir/` exists (which the generator never emits), so a later
step's agent opens the very workspace, state and deployed stack its own
earlier self left behind. Full rationale:
`docs/prompt-decomposition-audit.md` §3.

**Regression guarantee.** A spec **without** `steps` generates byte-identically
to before this field existed. Every branch the generator grows for steps is
`if spec.steps:`-guarded.

---

### 2.7 `workspace_seed` (optional, **TOP-LEVEL**, default `null`) — BROWNFIELD

Added 2026-08-20 by the poisoned-workspace pass
(`docs/design/poisoned-workspace-design.md`; `DECISIONS.md` Amendment 28).

Every scenario before this one is **greenfield**: §2.4's empty `entry_file`
skeleton, a `TODO(agent)` comment, "create X". `workspace_seed` makes a
scenario **brownfield** — the workspace starts from working, plan-green,
already-deployed configuration that carries a latent pitfall, and the prompt is
a change request (or an observed incident symptom) against it.

| | Greenfield | Brownfield (`workspace_seed`) |
|---|---|---|
| starting `entry_file` | empty skeleton + `TODO(agent)` | working config with a latent pitfall |
| starting state | plan-green, resource-**free** | plan-green, resource-**bearing** |
| prompt | "create X" imperative | change request or incident symptom |
| agent's job | author from scratch | modify existing config |
| what is measured | tokens-to-green on greenfield | **tokens-to-green on brownfield** |
| where the trap fires | the agent's own authoring | the agent's *change* to code it did not write |

```yaml
workspace_seed:
  premise: |                     # REQUIRED. NL, arm-agnostic. See "prompt rules".
    …what already exists, stated as fact, never as a warning…
  entry_file:                    # REQUIRED. Exactly one body per ENABLED arm.
    awscdk: |                    #   written VERBATIM as that arm's entry_file
      …
    hcl_raw: |
      …
    terraconstructs: |
      …
  extra_files:                   # OPTIONAL, per arm, WRITABLE (0o644)
    hcl_raw:
      - path: variables.tf
        content: |
          …
  seed_asserts:                  # REQUIRED, >=1. The parity gate. Same
    - name: …                    # {op, expected, cfn_jsonpath, tf_jsonpath}
      description: …             # vocabulary as oracle.structural_asserts (§4.2).
      pins_catch: <catch-name>    # optional per entry; >=1 entry MUST set it
      applies_to: [awscdk, hcl_raw, terraconstructs]
      cfn_jsonpath: …
      tf_jsonpath: …
      op: exists | not_exists | eq | in | contains | regex | set_eq | absent_or_eq | not_regex
      expected: …
```

**`entry_file` is a per-arm map, and each body is the WHOLE file.** There is no
derivation path between the three (`docs/scenario-candidates.md:169-176`: no
public CDK→TF synthesizer exists), so the three seeds are hand-authored under
the same discipline as `solution/solve.sh` (§8.2 point 8). The generator writes
each body verbatim — **no header of any kind** — so the spec author owns the
imports and the class/blocks. `gen.py::seed_entry_body` checks the per-arm
structural contract at generation time instead (`export class ScenarioStack` on
the TS arms; no `provider "aws"`/`terraform {}` block on hcl_raw, which
`provider.tf` owns — finding G1).

**The seed is AGENT-WRITABLE (`0o644`).** This is the exact opposite of
`seeded_files` (§2.5), which are `0o444` read-only reference inputs. The two
blocks stay separate because their permissions and semantics are opposites; a
path may not appear in both (rejected by `spec_model`, since one would silently
overwrite the other's permission). `write_environment` asserts the writability
after every workspace write, and `--seed` re-checks it from the gate side: a
`0o444` regression here would make a legitimate agent edit fail with `EACCES`
and score a **correct** solution 0.0.

**The seed reaches the container for free.** `gen.py::patch_dockerfile_workspace_copies`
already appends a named `COPY` for every workspace file the arm's own COPY set
does not cover (§2.5). A seed lands at `entry_file`, which every arm Dockerfile
already COPYs, so a seeded task's Dockerfile stays byte-identical to its arm's;
`extra_files` at new paths pick up COPYs automatically. The repo-wide invariant
is enforced by `generator/tests/test_dockerfile_workspace_coverage.py`.

**Prompt rules** (the review-time obligation; `DECISIONS.md` Amendment 28 §3):

1. Two legal framings: **change request** ("our naming convention changed —
   rename X to Y and roll it out") or **incident** ("since this morning `/foo`
   returns the previous version's response; get the deployed service serving
   the current code"). An incident prompt states an observed symptom and a
   desired end state — never a diagnosis.
2. **Never** "find the bug", "fix the mistake", "review this config". Those turn
   a brownfield task into a code-review task and measure something else.
3. **The premise states facts, not warnings.** "This is deployed in this
   account" is a fact. "Careful, this group is in use" is a warning and a hint —
   the in-use-ness must be discoverable from the config, which is what a
   `seed_assert` pins.
4. **No mechanism naming**, extending §2.1's `instruction_concision` rule: never
   name the pitfall's mechanism (`create_before_destroy`, "replacement",
   "perpetual diff"), never name the property that carries it, never say the
   workspace contains a problem.
5. **The seed carries no comment a real production file would not.** Mechanically
   tripwired by `spec_model._seed_comment_violations`, which rejects
   `TODO`/`FIXME`/`XXX`/`HACK`/`NOTE:`/`careful`/`gotcha`, the generator's own
   skeleton banners (`Empty on purpose`, `Generated skeleton` — which is also how
   "a workspace_seed spec must not also ship the empty stub" is enforced), and
   `create_before_destroy` **in a comment line**. A tripwire, not a proof.
6. **The ownership note changes.** Greenfield says "you own only `<entry_file>` —
   write your entire solution there"; brownfield says "`<entry_file>` holds this
   project's existing configuration — change it as needed". The don't-touch
   clause for `provider.tf`/`bin/app.ts`/`main.ts` is unchanged and still
   load-bearing (finding G1).

**Parity is preserved by construction.** `premise` is spec-level and
arm-agnostic, and the generator inserts it *before* the per-arm language line —
i.e. inside the parity-checked shared prefix (`gen.py::shared_prefix`,
`check_parity.py`). It cannot break prompt parity even in principle.

**`seed_asserts` — what "the three seeds are equivalent" means.** **Not**
resource-count or resource-type parity: the whole thesis of this benchmark is
that one L2 construct decomposes into N Terraform resources, so a census check
would fail every honest seed. Equivalence is defined **behaviourally**:

1. every arm's seed **synth/plans green**, with no overlay — a seed that does not
   is a generation failure, not a hard scenario;
2. every `seed_assert` holds on every arm it declares `applies_to`, resolved
   through the same `jsonpath_jq` compilation and the same
   `_assert_lib.sh::assert_check` a real trial's tier-0 runs;
3. **coverage**: at least one entry must set `pins_catch`, naming the catch whose
   mechanism lives in the seed. Without that back-reference a seed can drift into
   being non-poisoned — still green, still parity-clean, no longer carrying the
   pitfall — and nothing would notice.

Run it with `make seed-parity SPEC=specs/<id>.yaml`
(`generator/check_reference_paths.py --seed`; exit 3 = greenfield/NOT_AUTHORED,
non-gating). Wired per spec into `make ci`. An `applies_to` that differs per arm
is expected and legal — CFN expresses a graph edge as an `Fn::GetAtt` intrinsic
where Terraform expresses it as a reference string, and CFN has no `lifecycle`
meta-argument at all. Do not perform `applies_to` gymnastics to make the arms
look identical: **the asymmetry is the artifact families', not the seeds'.**

The residual, human half is `premise` itself: a mechanical gate can prove "these
three configurations satisfy the same declared facts", never "these three
describe the same system". That is exactly the status `oracle.intent` already
has (§4.1), and `premise` is reviewed the same way.

**The mandatory do-nothing negative.** Every `workspace_seed` spec ships
`solution/broken/seed-unchanged/solve.sh` — a no-op that submits the seed
exactly as found — and `gates/oracle_falsifiability.py` requires it to score
**< 1.0**. This closes the one failure mode unique to brownfield: a change
request the seed already satisfies rewards doing nothing, and no other gate can
see it (`solution/solve.sh` scoring 1.0 proves the oracle *accepts* a correct
change, never that it *rejects* the absence of one). The fixture is
**generator-owned and overwritten on every run** — a deliberate, documented
exception to §8.2 point 8, because its content is entirely mechanical and the
one fixture whose purpose is to be un-weakenable must not be hand-editable.

`< 1.0` is **necessary but not sufficient**, and the gate enforces the second
half too: the run must also have produced a *graded artifact* (a tier-0 summary
in its output). `tests/static_tiers.sh` writes `0.0` for a broken toolchain as
well as for a rejected solution — `TF-PLAN FAILED`, `MISSING ARTIFACT`, the
mock-STS `tf-plan-mock-sts-unavailable` bail-out that script itself labels *"a
run-invalidating test-infrastructure condition, NOT a bad solution"*. Counting
those as proof would make the one un-fakeable check pass vacuously. Observed
for real (2026-08-20): a batch `make falsifiability` run reported `TF-PLAN
FAILED` for the terraconstructs do-nothing fixture from mock-STS port
contention between back-to-back fixtures, while the same fixture in isolation
failed honestly on `security-group-uses-the-new-team-prefixed-name`. Such a run
is now a loud FAIL telling the operator to re-run, not a quiet pass.

**Composition with `steps` (§2.6).** Allowed, and the two features occupy
disjoint parts of the task dir: the seed lives in `environment/` (step-1
material by definition — the agent is *supposed* to see it from turn one),
steps live in `steps/`. The seed is written once, never per step. The
no-foreshadowing rules apply to the seed exactly as to a step-1 prompt.

**Equipping.** `task.toml [metadata] workspace_seed_sha256` carries a sha256
over every arm's seed body + extra files (spec-wide: the three seeds are one
equivalence claim, so editing any one invalidates every arm's rows).
`gates/equipping.py::compute_equipping_hash` reads it back and folds it into the
existing `extra_cfg` manifest slot — no `HASH_SCHEME_VERSION` bump, and no
greenfield task's already-published hash moves. It is not redundant with
`image_digest`: that fallback-resolves to a bare tag string whenever docker is
offline or the image isn't built locally, at which point two different seeds
under one tag would hash identically (§3.4 of the design memo).

**Metric rule.** Brownfield tokens-to-green is a **separate stratum**. It is
never pooled with greenfield rows — the same refusal Amendment 26 §4 applies to
N-step vs 1-step and Amendment 27 §2 applies to `apigw-redeploy`'s two forms.

**Regression guarantee.** A spec **without** `workspace_seed` generates
byte-identically to before this field existed. Every branch the generator grows
for it is `if spec.workspace_seed:`-guarded, and this was verified by
regenerating every pre-existing spec and diffing (zero changed files).

---

## 3. `catches`

```yaml
catches:
  - name: <kebab-case, unique within the spec>
    taxonomy: typed-value-trap | graph-dependency | nested-attribute | anti-L2
    description: <string — the natural-language catch, no thresholds pasted into instruction.shared_body>
    predicted_tier_caught:
      awscdk: "0" | "0.5" | "1" | "live"
      hcl: "0" | "0.5" | "1" | "live"
      terraconstructs_override: "0" | "0.5" | "1" | "live" | null   # optional, default null
    applies_to: [awscdk, hcl_raw, terraconstructs]   # optional, default: all 3 (every enabled arm)
```

At least one entry required; real benchmark scenarios (Slice D) should carry
the three real-world catches plus one `anti-L2` catch per prereg §5 — the toy
spec is exempt (its header says so) and does not need taxonomy diversity.

- `taxonomy` is exactly the prereg §5 four-value enum. `anti-L2` is the
  falsifiability catch (H2) — only meaningful when the spec names a concrete,
  currently-un-surfaced L2 property (a real one, verified against the local
  `aws-cdk` clone at authoring time, per the build plan's seed-scenario
  table methodology); do not fabricate one for a fixture that isn't chasing
  H2 evidence.
- `predicted_tier_caught.awscdk` / `.hcl` are **required**, string-typed
  (`"0"`, `"0.5"`, or `"1"` — strings, not YAML floats, so `"0.50"` vs `"0.5"`
  parsing landmines can't happen). Tier `"0.5"` (embedded-expression
  evaluation, Amendment №1) only applies to catches inside a JSONata `{% ... %}`
  expression string; everything else is `"0"` or `"1"`.
- **`.hcl` means "the Terraform-shaped arms as a group"** — `hcl_raw` and,
  when enabled, `terraconstructs` — because both synthesize to plain
  Terraform and are graded by **the same** `terraform show -json` plan shape
  and **the same** Rego bundle (§4, §8); a catch caught by `validate`/`plan`
  for one is caught identically for the other **unless** terraconstructs'
  own typed TS surface intercepts it earlier (it happens: `arms/terraconstructs/README.md`
  §4 confirms `RetentionDays` is a real TS enum there too, so a
  typed-value-trap scenario built on it is caught at terraconstructs' `tsc`,
  not at its `terraform validate` — diverging from `hcl_raw`'s tier for the
  *identical* catch). `terraconstructs_override` exists for exactly this
  case: set it to the diverging tier when terraconstructs' own construct is
  independently typed for this property; leave it `null` (inherit `.hcl`)
  otherwise. **Before setting a non-null override, verify it by actually
  reading the relevant `terraconstructs` source file** — do not assume parity
  with `aws-cdk-lib`'s surface; `DECISIONS.md`'s "s3-lambda-log-retention
  catch is falsified by the pinned provider" entry is the standing lesson
  that predicted tiers must be evidence-checked, never assumed, before a
  scenario spec freezes.
- **`"live"`** (Slice G addition, `DECISIONS.md` "Amendment 12"): a catch
  whose mistake is invisible to *every* static tier by construction — the
  only discriminating signal is a real
  apply→modify→re-apply→curl loop (only meaningful alongside
  `verifier.live_check.enabled: true`, §5). Distinct from `"0.5"`
  (`tier05_jsonata` is itself a static/offline check, just host-side and
  non-gating): a `"live"` catch has no static evaluator to run against the
  artifact at all. `gates/oracle_falsifiability.py::check_arm`'s `"live"`
  branch requires the fixture's reward to stay `1.0` (the same static
  tiers a correct solution passes) AND its **offline** run to print the
  fixed marker `LIVE_ONLY_CONFIRMED_MARKER =
  "CDKTN_BENCH_LIVE_ONLY_CONFIRMED"`, mechanically earned (e.g. a two-plan
  diff proving a hash stayed frozen across revisions), not merely claimed
  in a comment — this keeps `make ci`/`make falsifiability` fully offline
  even for a scenario that declares a live-only catch.
- `applies_to` (optional, default: all three enabled arms — 100% backward
  compatible with every pre-Slice-G spec): restricts which arms
  `gates/oracle_falsifiability.py` requires a
  `solution/broken/<name>/solve.sh` fixture for. Exists because a catch's
  mistake can be structurally IMPOSSIBLE on some arm without a contrived
  escape hatch — e.g. a hand-omitted Terraform `triggers` block has no
  direct CDK/terraconstructs L2 equivalent (the L2 always computes one); an
  arm not listed here is reported `N/A` (non-gating), not `MISSING`. Most
  catches should leave this at its default; reach for it only when a
  mistake is genuinely arm-specific, the same bar `terraconstructs_override`
  above applies to tier divergence.

---

## 4. `oracle`

```yaml
oracle:
  intent: <string — natural-language, single source of truth for what "correct" means>
  structural_asserts:
    - name: <kebab-case, unique within the spec>
      description: <string>
      tier: "0" | "0.5" | "1"
      applies_to: [awscdk, hcl_raw, terraconstructs]   # subset of enabled arms; default = all enabled arms
      cfn_jsonpath: <string>     # required iff 'awscdk' in applies_to
      tf_jsonpath: <string>      # required iff 'hcl_raw' or 'terraconstructs' in applies_to
      op: exists | not_exists | eq | in | contains | regex
      expected: <any>            # shape depends on op; omitted for exists/not_exists
  rego_hints: [<string>, ...]        # optional, default []
  cfn_guard_hints: [<string>, ...]   # optional, default []
  tier05_jsonata:                    # optional, default null
    expressions_from: <string, JSONPath into the synthesized artifact locating every `{% ... %}` string>
    sample_inputs:
      - input: <object>
        expected_output: <object>
```

### 4.1 `intent`

The natural-language statement of correctness this whole scenario exists to
check — the thing a human reviewer reads to judge whether `structural_asserts`
+ the hand-authored `.rego`/`.guard` bundles (§8) actually encode what they
claim to. This is the text that lands in the generated
`oracles/<id>/intent.md` (§8) and is what the oracle-equivalence CI (Slice E)
uses as the reference when checking that the Rego and cfn-guard bundles
encode "the same intent at the same strictness" (prereg §3).

### 4.2 `structural_asserts`

One entry per independently-checkable structural fact, expressed **once**
against both artifact shapes — this *is* the oracle-equivalence mechanism,
not just documentation of it. `cfn_jsonpath` targets the `awscdk` arm's
synthesized CloudFormation template (`cdk.out/ScenarioStack.template.json`).
`tf_jsonpath` targets `terraform show -json`'s plan JSON — and because that
JSON schema is Terraform's own (not tool-specific), **the same expression
applies to both `hcl_raw` and `terraconstructs`** without needing a
per-arm override, **for attributes that are statically known at plan
time** (§4.2.1 below is the load-bearing exception to this — read it before
writing a new tier-"1" assert that targets an IAM policy, or any other
attribute whose value can depend on another resource's provider-computed
output). Where it holds, only the JSON *values* an assert reads differ
based on what the agent actually wrote, never the paths' shape — this is
stronger oracle-equivalence than the CFN side gets (which needs a real
second expression, `cfn_jsonpath`, because CFN and TF plan JSON are
structurally different documents).

#### 4.2.1 Plan-time-unknown attributes (correction, 2026-08-06)

**The claim above — "one `tf_jsonpath`, values differ, path shape never
does" — is FALSE for any attribute whose value can be plan-time UNKNOWN.**
This was found and fixed as benchmark-integrity finding G2, using
`specs/_toy/toy-ssm-parameter.yaml`'s `policy-actions-read-only` /
`policy-resource-scoped-not-wildcard` catches as the worked (and now
corrected) example — read that spec's own inline comments alongside this
section; they carry the full evidence trail this section summarizes.

**The mechanism.** `terraform show -json` PLAN output's `.planned_values`
tree only contains a value for an attribute Terraform can compute *before*
any resource is actually created. An attribute that is itself a static
echo of agent-supplied config (a name, a literal string) is always known.
An attribute a *provider* computes and only learns after `apply` (an ARN,
a generated ID, a computed hash) is `(known after apply)` at plan time —
absent from `.planned_values` entirely, not present-with-a-wrong-value.
Critically, this is **contagious through `jsonencode(...)` (hcl_raw) or
an equivalent JSON-serialization call (terraconstructs)**: if *any* value
embedded in the object being encoded is plan-time-unknown (e.g. an IAM
policy's `Resource` field built from `aws_ssm_parameter.foo.arn`), the
**entire** encoded JSON string becomes unknown — `values.policy` on
`aws_iam_role_policy` resolves to `null`, even though most of the
statement (the `Action` list, say) was itself perfectly static. Verified
directly against real `terraform show -json` output for both TF arms
(`aws_iam_role_policy.policy` referencing the created parameter's `.arn`):

```
$ jq '.planned_values.root_module.resources[]
      | select(.type=="aws_iam_role_policy") | .values.policy' plan.json
null
```

A tier-1 `tf_jsonpath` written against `.planned_values...values.policy`
for a check like this is not "correct but sometimes strict" — it is
**silently vacuous** against exactly the class of correct solution that
references another resource's computed output (an entirely normal,
arguably more idiomatic Terraform pattern than avoiding it). A Rego rule
written against it can never fire; this is functionally identical to
`default allow := true`, and nothing catches it, because tier-1 paths are
never executed by the generated `tests/static_tiers.sh` (tier-1 is
Rego/cfn-guard-graded — the path is documentation, not code, until this
finding's fix). This is exactly why `generator/check_reference_paths.py`
(`make check-paths SPEC=...`, added by this fix) exists: it resolves
**every** declared `structural_assert`, tier "0" and tier "1" alike,
against a real synthesized/planned artifact from a hand-authored,
known-correct reference fixture, so a dead path fails loudly at
generation/review time instead of shipping silent.

**The fix, in two parts:**

1. **Graph-edge / scoping checks** ("does this policy depend on / reference
   the resource this scenario creates, not a wildcard or something
   unrelated") should target `.configuration.root_module.resources[].
   expressions.<attr>.references` instead of
   `.planned_values...values.<attr>`. `.configuration...expressions` is
   populated from the **HCL source itself**, not from provider computation
   — the list of resource addresses an attribute's expression *references*
   is plan-time-known regardless of whether the referenced attribute's
   *value* is. Verified against both a correct fixture (references the
   created resource) and a deliberately-bad one (hardcoded literal, no
   reference at all):

   ```
   # correct (references aws_ssm_parameter.greeting, via .arn or .name):
   .configuration.root_module.resources[]
     | select(.type=="aws_iam_role_policy") | .expressions.policy.references
   -> ["aws_ssm_parameter.greeting.arn", "aws_ssm_parameter.greeting"]

   # bad (hardcoded Resource="*", no reference to anything):
   -> {} (no ".references" key at all -- zero references)
   ```

   This resolves to something for a correct solution and to nothing for
   the exact violation such a check exists to catch — the *opposite*,
   sound direction from the plan-time-unknown dead path. **Caveat:** the
   hop count from `aws_iam_role_policy` to the target resource can differ
   by HCL idiom even for two equally-correct solutions — a raw
   `jsonencode(...)`-authored policy references the target resource
   directly (one hop); a policy composed via a `data
   "aws_iam_policy_document"` block (idiomatic hand-written HCL, and
   `terraconstructs`' own `iam.Role.addToPolicy()` L2 helper compiles to
   exactly this) references *that data source*, which itself references
   the target resource one hop further. A single flat `tf_jsonpath` cannot
   express "resolve references transitively through zero-or-more
   `data.aws_iam_policy_document.*` hops" — that is Rego's job; the
   `tf_jsonpath` on such an assert documents the direct-reference case as
   guidance for whoever hand-authors the policy, not an exhaustive,
   mechanically-sufficient check. (This is, itself, a second reason "one
   path, both TF arms, done" doesn't fully hold for such checks — worth
   flagging in `rego_hints` whenever it applies, per the toy spec's own
   example.)

2. **Value-content checks** ("what exactly is granted") have no
   plan-time-known equivalent when the same encoded attribute also
   contains a plan-time-unknown reference — there is no way to ask
   Terraform's plan JSON for "just the parts of this JSON-encoded string
   that happen to be static." Three options, in order of preference:
   - Design the scenario so the reference solution's relevant attribute
     stays fully static (e.g. build a resource-ARN *pattern* from the
     target's own literal, agent-supplied `.name` — an echoed input,
     always known — rather than its provider-computed `.arn`). Verified:
     doing this keeps `values.<attr>` fully resolved, structure intact,
     for both TF arms. This is why `specs/_toy/toy-ssm-parameter.yaml`'s
     own `oracle.intent` asks for a wildcarded ARN *pattern*
     (`arn:*:ssm:*:*:parameter/...`) rather than the literal resolved ARN
     — that phrasing is not incidental, it is what keeps this tier-1
     check meaningful at all.
   - If the scenario's intent cannot be narrowed this way, split the
     assert like §4.2's opening paragraph now says: a tier-1 entry may
     need to be **two** `structural_asserts` (one `applies_to: [awscdk]`
     with a literal `cfn_jsonpath` check — CFN's synthesized template is
     always fully static, no "plan" concept, so it never has this problem
     — and one `applies_to: [hcl_raw, terraconstructs]` with the
     plan-time-known form), not one shared entry pretending both artifact
     families are checked the same way.
   - Otherwise, document the gap explicitly in the assert's `description`
     and a matching `rego_hints` entry (see the toy spec's
     `policy-actions-read-only` for the pattern): Slice D's Rego must
     treat "value unresolved AND the graph-edge check already passed" as
     **not independently verifiable from plan JSON**, not as a silent
     pass or an incorrect fail of a legitimately-correct solution. This is
     a known, standing v1 scope limitation (the oracle is synth/plan-only,
     never live/apply-time, per `DECISIONS.md`), not something a single
     scenario spec can fix on its own. **Made non-silent by a
     residual-findings fix (2026-08-06):** treating this as "not
     independently verifiable" must itself be *recorded*, not just
     tolerated — a `policy.rego` covering an assert like this may define
     an optional top-level `not_verifiable` set alongside its `deny` set,
     e.g.:
     ```rego
     not_verifiable contains msg if {
         # the graph-edge check passed but the plan-time value needed for
         # the value-content check is unresolved -- fires ONLY for this
         # case, never for a genuine violation (which `deny` already
         # catches) or a fully-verifiable pass (which stays silent here).
         ...
         msg := sprintf("...", [...])
     }
     ```
     A generated `tests/static_tiers.sh` (`generator/gen.py::build_static_tiers_sh`)
     evaluates `data.cdktn_bench.<pkg>.not_verifiable` after `deny` and,
     whenever it's non-empty, tees the detail to
     `/logs/verifier/tier1-not-verifiable` — mirroring the existing
     `tier1-unavailable`/`tf-plan-mock-sts-unavailable` non-silent-marker
     convention. This is **non-gating**: it never affects `tier1_status`
     or `/logs/verifier/reward.txt`, only whether the fact "this could not
     be checked" is ever recorded anywhere. `not_verifiable` is optional —
     a `policy.rego` that never defines it is treated as declaring no such
     gap (evaluates to empty, no marker written) — but any tier-1 assert
     that reaches this third bullet SHOULD define one, or the gap this
     bullet exists to document degrades right back into a silent one at
     grading time. See `oracles/rego/toy-ssm-parameter/policy.rego`'s own
     `not_verifiable` rule for the worked example, and
     `oracles/emit.py`'s generated policy skeleton for the scaffolded
     placeholder every new tier-1 policy starts from.

**Authoring rule going forward:** never mark a `structural_assert` tier
`"0"` for an attribute that *can* be plan-time-unknown depending on how a
correct solution references other resources — tier "0" entries are
executed directly by the generated `tests/static_tiers.sh` against every
trial, so a dead tier-0 path doesn't just mis-document a Rego rule, it
makes the tier itself silently unfalsifiable. Run `make check-paths
SPEC=specs/<id>.yaml` against a real reference fixture before trusting any
new tier-1 `tf_jsonpath` too — "the policy is the thing that actually
runs" (§4.2's tier description below) does not mean the `tf_jsonpath` spec
guiding it is exempt from ever being checked against reality.

`op`/`expected` pairs:

| `op` | `expected` | Meaning |
|---|---|---|
| `exists` | omitted | the path resolves to ≥1 node |
| `not_exists` | omitted | the path resolves to 0 nodes |
| `eq` | scalar | the *(single)* resolved value equals `expected` -- 0 or >1 resolved nodes FAILS outright (ambiguity is itself a failure, not "pick one") |
| `in` | list | every resolved value is a member of `expected` (array-valued matches are flattened one level first, since a property like IAM `Action` is sometimes a bare string and sometimes a list of strings across statements) |
| `contains` | scalar | a resolved string LITERALLY contains `expected` as a substring (never a regex -- `"."` in `expected` must never act as a wildcard), or a resolved list/array contains `expected` as a member |
| `regex` | string (pattern) | the resolved string value matches `expected` as a regex (the one op that IS pattern matching by design) |
| `set_eq` | list | every resolved value (flattened one level, same as `in`), taken as a SET, equals `expected` taken as a SET -- exactly, not a subset/superset. This is the "and nothing else" op the "scoped, not broader" catch family needs: `in`/`contains` only require every actual value to be *allowed*, so an otherwise-correct match plus one extra, unintended value (a second trusted principal, a second granted action) still passes them. Use `set_eq` wherever the natural-language intent is "trusts/grants ONLY \{X\}", not just "trusts/grants X". |
| `absent_or_eq` | scalar | the path resolves to 0 nodes, OR to exactly 1 node equal to `expected` (>1 resolved node FAILS, same ambiguity rule as `eq`). Added by a residual-findings fix (2026-08-06): a bare `not_exists` used for "an enum-typed property was left at its implied default" false-negatives an equally-correct solution that wrote the semantically-identical value *explicitly* instead of omitting it (arm idioms differ in how readily they emit explicit defaults, so this is a real per-arm scoring bias, not a theoretical one). Neither `not_exists` alone (rejects the explicit form) nor `eq` alone (rejects the omitted form) can express "either form is fine" -- use `absent_or_eq` for any "left at its implied default, not set to some OTHER wrong value" catch, never bare `not_exists`, whenever the property's implied default has a concrete literal value a correct solution could also legitimately spell out. |
| `not_regex` | string (pattern) | NONE of the resolved string values match `expected` as a regex (an unanchored search, same semantics as `regex` — matches ANYWHERE in the string, not a full-string match) -- 0 resolved nodes vacuously PASSES (nothing to violate), unlike `regex`'s own `>= 1 node` requirement. Added for `specs/sfn-jsonata.yaml`'s mode-mixing catch (the "no raw un-evaluated JSONPath string anywhere in this JSONata-mode ASL" fact, mirroring `tc-ai-pdlc-coding-features/tests/helpers.py::contains_jsonpath_artifact`'s own `r'"\$\.'` pattern): `regex` alone can only assert a pattern IS present, never that it is ABSENT, and no combination of the other seven ops can express "this string must never contain X" for an arbitrary substring (as opposed to "this key must be absent", which `not_exists` already covers structurally). Both evaluators implement it as the literal negation of `regex`'s own per-value match test -- `oracles/lib/structural.py::apply_op`'s `re.search`, `generator/gen.py`'s compiled-jq `test($e)` -- so no new regex engine/dialect is introduced. |

Every `cfn_jsonpath`/`tf_jsonpath` may contain one or more `|fromjson`
markers splitting the path into segments, e.g.
`$.values.container_definitions|fromjson[*].linuxParameters.swappiness`.
Each `|fromjson` decodes whatever the preceding segment resolved to as a
JSON string before continuing to resolve the next segment against the
decoded value. This exists because several `terraform show -json` plan
attributes the taxonomy's catches target store their value as a
JSON-encoded STRING rather than nested structure (`values.
container_definitions`, `values.assume_role_policy`, `values.policy` —
all `jsonencode(...)`'d in the HCL that produced them) — without
`|fromjson`, a path ending in e.g. `values.assume_role_policy.Statement`
resolves against the raw undecoded string and silently finds nothing, no
matter how correct the rest of the path is. Both evaluators implement this
identically: `generator/jsonpath_jq.py::jsonpath_to_jq` compiles it to a
literal jq `fromjson` filter; `oracles/lib/structural.py::resolve` resolves
segment-by-segment, `json.loads`-ing every node between segments (Rego and
cfn-guard need no such extension — `json.unmarshal`/native JSON parsing of
an embedded string is a normal, first-class operation in both, so this is
a tier-0/tier-0.5-evaluator-specific gap, not a Rego/cfn-guard one).

`tier`: `"0"` if checkable directly on the raw synth/plan artifact with no
extra tool (this is what the generated `static_tiers.sh` runs immediately
after synth/plan, before invoking cfn-guard/Rego); `"1"` if it's the kind of
graph/intent check better expressed as Rego/cfn-guard policy (in which case
this entry is the **spec** for that policy, cross-checked by the
oracle-equivalence CI — the policy file is still the thing that actually
runs); `"0.5"` is invalid here (that tier is `tier05_jsonata`-only, §4.3).

### 4.3 `rego_hints` / `cfn_guard_hints`

Free-form prose, **not executable** — bullet points guiding whoever
hand-authors `oracles/rego/<id>/*.rego` and `oracles/cfn-guard/<id>/*.guard`
(§8) toward the intended policy shape (e.g. "deny if any IAM policy Statement
Resource is `\"*\"` when a specific parameter ARN was created in this plan").
Every tier-`"1"` entry in `structural_asserts` should have at least one
corresponding hint in each list, since both a Rego rule and a cfn-guard rule
need to exist for it.

### 4.4 `tier05_jsonata` (optional, default `null`)

Present **only** for scenarios embedding a JSONata `{% ... %}` expression
(the `sfn-jsonata`-style scenario) — Amendment №1, `docs/iac-abstraction-aws-bench-plan.md`
lines 120–127.

```yaml
tier05_jsonata:
  expressions_from: <JSONPath string> | {cfn: <JSONPath string>, tf: <JSONPath string>}
  cases:
    - expression_path: <string — the exact path oracles.lib.tier05_jsonata.jsonata_expressions()
                         reports finding this expression at, e.g. "$.States.ComputeTotals.Output">
      input: <object>          # bound to $states.input for THIS expression's own evaluation
      expected_output: <any>   # compared to the evaluated expression's result via ==
```

**Correction (this doc previously described a stale, never-shipped shape —
`sample_inputs: [{input, expected_output}]` with no way to pin a case to a
specific expression.** The actually-implemented shape (`generator/spec_model.py`'s
`Tier05Jsonata`/`Tier05Case`, `oracles/lib/tier05_jsonata.py::run_tier05`) is
`cases: [{expression_path, input, expected_output}, ...]`, matched by
`expression_path` — **not** the cartesian product of every found expression
against every case (that shape
rejects a fully-correct multi-expression state machine the moment it has more
than one embedded expression: state A's expression evaluated against state
B's sample input, compared against state B's expected output, fails despite
A and B individually being correct — see `run_tier05`'s own docstring for the
fixed bug this replaced). Every declared case must match an expression that
actually exists in the artifact — a case whose `expression_path` resolves to
nothing FAILS loudly (a renamed/removed state, or a stale case, is a
spec/artifact drift, never silently ignored). **Correction (2026-08-06,
residual-findings fix, benchmark-integrity review finding "sfn-jsonata /
Tier 0.5 anti-L2 oracle — false-positives on equally-correct solutions"):**
the *converse* direction — an expression found in the artifact that no case
covers — is INFORMATIONAL ONLY (surfaced in `Tier05CaseResult`/`explain()`
output, `passed=True`), not a failure. This doc previously said "either
mismatch fails loudly"; that was wrong for this direction specifically —
`oracle.tier05_jsonata.cases` is authored against one reference
decomposition (this scenario's own reference `solve.sh`), and a correct
solution that decomposes an object-literal `Output`/`Arguments` value
differently (e.g. per-field `{% %}` sub-expressions instead of one
whole-object `{% %}` expression) legitimately introduces `{% %}` expressions
no case names — scoring that as an anti-L2 catch hit would contaminate the
H2 falsifiability signal this tier exists to produce with an oracle-shape
artifact instead of a real catch. See `oracles/lib/tier05_jsonata.py::run_tier05`'s
own docstring for the mechanics.

**Correction (2026-08-06, benchmark-integrity review finding "tier05_jsonata
materialize() container fallback accepts a fully-hardcoded literal"):** this
doc previously implied one case per `expression_path` (`generator/spec_model.py`
used to enforce it as a hard uniqueness constraint). Multiple cases MAY now
share the same `expression_path` — each one an independent `(input,
expected_output)` sample against that same expression, evaluated
independently by `run_tier05`. Author at least two such samples (different
inputs, different expected outputs) for any expression whose
`expression_path` names a container rather than a bare `{% ... %}` string
leaf (`run_tier05`'s case "2" — see its own docstring): a single sample lets
a fully hardcoded literal (zero `{% %}` expressions anywhere in the
container) satisfy `expected_output` by construction, indistinguishable from
a genuinely computed value; a second, differently-valued sample cannot also
be satisfied by that same literal. `oracles/lib/tier05_jsonata.py::run_tier05`
also independently refuses to materialize-and-compare a zero-expression
container at all (belt-and-suspenders — see its own docstring), but a
second sample is the scenario-authoring-side half of the same fix and should
be added regardless of that guard's presence.

`expressions_from` locates every `{% ... %}`-embedding ASL document in the
synthesized/planned artifact (e.g. a CFN `DefinitionString` property, or a
TF `aws_sfn_state_machine.definition` attribute) via a JSONPath resolved
through `oracles.lib.structural.resolve` (so `|fromjson` works here too, the
common case since both attributes are JSON-encoded strings). **Two shapes**:
a single string, when one path genuinely resolves against every arm's own
artifact (rare — CFN template JSON and Terraform plan JSON have structurally
different root shapes, `$.Resources[...]` vs.
`$.planned_values.root_module.resources[...]`, so this is realistically only
usable for a scenario checked against one artifact family); or a
`{cfn: <path>, tf: <path>}` mapping (the normal case for a real cross-arm
scenario) — `run_tier05` auto-detects which family a given artifact document
is by checking for a top-level `Resources` key (CFN) vs. `planned_values`
key (TF plan), and selects the matching path. `hcl_raw` and `terraconstructs`
share the `tf` path, same collapsing convention as `predicted_tier_caught.hcl`
(§3) and `tf_jsonpath` (§4.2) — both synthesize to the same `terraform show
-json` plan shape.

Every extracted expression is evaluated with `jsonata-python`, `$states.input`
bound to that CASE's own `input` (i.e. whatever that specific state would
actually receive as its effective input in a real execution — not one global
workflow input reused for every expression), identically across all
applicable arms (the ASL JSON is extractable from both CFN and TF plan
output, so this adds no arm asymmetry — same rationale as the amendment
itself). Leave `null` for every scenario that has no embedded expression
language; do not populate it "for completeness."

**Non-gating (SCHEMA.md §5's precedent, `DECISIONS.md` "Tier-0.5 runs
host-side, non-gating"):** Tier 0.5 never runs inside a generated
`tests/static_tiers.sh` and never affects `/logs/verifier/reward.txt` — no
arm image ships Python/`jsonata-python`. Run it host-side, post-hoc, via
`uv run python -m oracles.lib.tier05_jsonata <artifact.json> <spec.yaml>`
(the generator emits a `tests/TIER05.md` pointer at this exact command for
any scenario declaring this field). Because it never gates reward, a
scenario whose only mechanism for a given catch is Tier 0.5 (the anti-L2
falsifiability catch's own defining property — invisible to every synth/
plan/validate/policy tier by construction) needs its negative fixture proven
via the Tier 0.5 evaluator directly, not via `reward.txt` — see
`gates/oracle_falsifiability.py`'s tier-aware per-catch handling.

---

## 5. `verifier`

```yaml
verifier:
  budget:
    max_iters: 8
  live_check:
    enabled: false
    module: tests/live_check.py
    hand_authored: false
    agent_role_name: null
    concurrency_mode: null
    gating: false
```

- `budget.max_iters`: the `MAX_ITERS` feedback-cycle cap (prereg §4). `8` is
  the pre-registered default; a spec may lower it (never raise it without a
  logged amendment — this is a pre-registered budget, not a per-scenario
  knob to tune away a hard scenario).

  > **Not the same number as the runner's `MAX_ITERS`.** `DECISIONS.md`
  > Amendment 22 exists precisely to unpick this conflation:
  > `scripts/run-bench.sh` maps `MAX_ITERS` onto Claude Code's `--max-turns`,
  > which counts **agent steps**, not the pre-registration's feedback
  > **cycles** — one cycle (author → deploy → read error → amend) is many
  > steps — and its default is **100**, raised from 8 after the first live
  > trial hit `error_max_turns` at 8. This field is the prereg's *cycle*
  > budget; do not read the two as one knob. See `CLAUDE.md` "Turn budget".
- `live_check.enabled`: **`false` for every v1-shaped (synth/plan-only)
  spec** — the CONTEXT constraint this schema was originally written
  against ("v1 verifier is the STATIC tier stack ... NOT live-AWS
  check.py") still holds for the vast majority of scenarios. Relaxed from a
  hard-pinned `Literal[False]` to `bool` by the Slice G amendment
  (`DECISIONS.md` "Amendment 12", first exercised by `apigw-redeploy`; more
  than one spec sets it `true` today, so do not read this as an enumeration
  — `grep -l 'enabled: true' specs/*.yaml` under `live_check` is the answer):
  a scenario whose entire point
  is a day-2 apply→modify→re-apply→verify loop *inside one trial* cannot be
  meaningfully graded synth/plan-only, since the fact being tested (did the
  second deploy actually take effect) only exists at runtime. Setting this
  `true` is a real design decision, not a default — see `apigw-redeploy`'s
  own `[concurrency] mode = "mutating"` consequence below.
- `module`: a **path**, relative to the generated task's own `tests/`
  directory, naming the live-check hook. While `enabled: false`, the
  generator always scaffolds this as an inert not-implemented stub (§8),
  regenerated every `make gen` run — never invoked by the generated
  `tests/test.sh`.
- `hand_authored` (bool, default `false`): **must be `true` whenever
  `enabled` is `true`** (`spec_model.LiveCheck`'s own model validator
  rejects the alternative) — a spec cannot flip live checking on and leave
  the generator's inert stub as its real implementation. When `true`, the
  generator's write-tests step becomes destructive-safe for `module`
  (mirrors `solution/solve.sh`'s own "never overwrite hand-authored
  content" convention, §8.2 point 8) — write the real file into the
  generated task directory once, by hand, and `make gen` will never
  clobber it again.
- `agent_role_name` / `concurrency_mode` (both optional, default `null`):
  spec-driven overrides for what used to be two hardcoded literals in
  `generator/gen.py::build_task_toml` (`agent_role_name =
  "QALocalInvocationApplicationRole"`, `[concurrency] mode = "read-only"`).
  `null` (every pre-Slice-G spec) reproduces those old hardcoded values
  byte-for-byte. `concurrency_mode: "mutating"` is what actually triggers
  aws-bench's own post-trial scenario-account reset
  (`aws_bench/task/aws_trial.py`'s `ConcurrencyMode.MUTATING` handling,
  outside this repo) — required for any scenario whose agent phase performs
  real AWS mutations, or the deployed/modified resources are never reset
  between trials. `agent_role_name` must name a role capable of the
  mutations the scenario's instruction asks for; `apigw-redeploy` uses
  `QADeployApplicationRole` (`scenarios/anchor/scenario/cdk_app/stacks/
  qa_roles_stack.ts`) — a minimally-scoped role added by explicit operator
  authorization (`DECISIONS.md` "Adding a QADeployApplicationRole"),
  superseding the earlier `QALocalInvocationApplicationAdmin` (full
  `AdministratorAccess`) over-grant Amendments 12-15 used while no
  narrower role existed. See `docs/adding-scenarios.md` for how to pick
  among the three agent roles, and when/how to extend `QARolesStack` if a
  future scenario needs a permission none of the three grant.
- `gating` (bool, default `false`): **by default, a live check's result
  never gates `/logs/verifier/reward.txt`** (§8's Phase-2 forward-compat
  note, point 4 below) — written instead to a separate
  `/logs/verifier/live_check-result.json` for out-of-band analysis. This
  was originally an unconditional invariant ("this is the one thing
  Slice G's `enabled: true` spec does NOT change") until a fix-round-3
  review (`DECISIONS.md` Slice G amendment, 2026-08-07) pointed out that
  `apigw-redeploy`'s `triggers-incomplete-hash` catch is a
  `predicted_tier_caught: "live"` catch BY CONSTRUCTION — every static tier
  passes it identically to a correct solution — so leaving live_check
  non-gating meant the one catch this whole scenario exists to motivate
  could never cost a real trial any reward. `gating: true` requires
  `enabled: true` (`spec_model.LiveCheck`'s own model validator rejects the
  alternative — a live check that never runs cannot gate reward) and is
  read by `generator/gen.py::build_task_toml` to also write
  `SPEC_LIVE_CHECK_GATING = "true"` into `[verifier] env` (alongside
  `SPEC_LIVE_CHECK_ENABLED`); the generated `tests/test.sh` reads that var
  and folds `live_check.py`'s own JSON `.outcome` field (`"pass"` /
  `"fail_stale"` / `"not_verifiable"` — hand-authored `live_check.py`'s own
  contract, not schema-enforced) into `reward.txt` with AND semantics: the
  final reward is 1.0 iff the static tiers already say 1.0 AND `.outcome`
  is `"pass"` — both `"fail_stale"` and `"not_verifiable"` downgrade to 0.0,
  fail-closed (an unverifiable claim must never silently earn reward).
  `gating: true` is set by more than one spec today (it travels with
  `live_check.enabled`, and every live-checked scenario in the corpus gates
  on it) — the list is not enumerated here because it goes stale; the specs
  themselves are the register. Every spec that does NOT set it gains the same
  runtime branch as dead code (never entered, since `SPEC_LIVE_CHECK_GATING`
  is never set for them) — a strict no-op, same convention as `enabled`
  itself. The fixture-invoked shape (`--expect {ok,stale}`, called directly
  by `solution/solve.sh`/`solution/broken/*/solve.sh`) was, and remains, a
  SEPARATE, always-gating call shape independent of this flag — see that
  module's own docstring.

### 5.1 `verifier.idempotence` (optional, default disabled)

```yaml
verifier:
  live_check: { enabled: true, hand_authored: true, gating: true, … }
  idempotence:
    enabled: true      # default false
    gating: true       # default false; requires enabled
```

Added 2026-08-20 alongside §2.7 (`docs/design/poisoned-workspace-design.md` §5;
`DECISIONS.md` Amendment 28 §4). The question it answers is one no static tier
can: **after the agent's solution is green, does the agent's own toolchain
still report a pending change against what it just deployed?**

**It is a LIVE tier, and that is a blocking fact rather than a preference.**
`terraform plan -detailed-exitcode` returns `2` (changes present) for *any* plan
against empty state, and the generated static tier plans an empty working
directory — so a "second plan" is meaningless offline. Hence
`idempotence.enabled: true` **requires** `live_check.enabled: true`
(`spec_model.Spec._idempotence_requires_live_check`): no apply ⇒ no state ⇒
nothing to be idempotent about.

**Per-arm commands are injected unconditionally by the generator**, never read
from a spec key — the same "cannot go missing because a spec author forgot a
YAML key" discipline `TERRACONSTRUCTS_BUILD_COMMAND` uses
(`gen.py::IDEMPOTENCE_COMMAND`):

| Arm | Command | Converged | Pending |
|---|---|---|---|
| `hcl_raw` | `terraform plan -input=false -refresh=false -detailed-exitcode` | exit 0 | exit 2 |
| `terraconstructs` | `npx cdktn synth`, then a **post-synth re-probe of `terraform.tfstate`** (see below), then the same plan inside `cdktf.out/stacks/<id>/` (`<id>` = `workspace_id`, §0.1) | exit 0 | exit 2 |
| `awscdk` | `npx cdk diff --fail --no-lookups ScenarioStack` | exit 0 | exit 1 |

`cdk diff --fail` is the honest analogue for CloudFormation: "the toolchain's own
converged-state check reports no pending change against what is actually
deployed". A second synth + template self-diff is **not** an analogue — CDK
synth is deterministic, so that check is vacuous by construction and would
silently hand the awscdk arm a free pass.

`-refresh=false` on the TF arms for the same reason `build_static_tiers_sh`
already uses it on a post-apply working tree: a refreshing plan re-contacts AWS
through the arm's *offline* dummy-credential provider config and 403s, which
would report `pending_changes` for a reason unrelated to convergence.

**Three outcomes, mirroring `live_check`'s own contract**, written to
`/logs/verifier/idempotence-result.json` (plus the raw command output in
`/logs/verifier/idempotence.log`) whether gating or not:

- `converged` — exit 0;
- `pending_changes` — the arm's pending exit code;
- `not_verifiable` — anything else, **including the never-deployed case**
  (offline, or an agent that never applied). This case is caught by a
  **different mechanism per arm**, because the arms keep their converged state
  in different places, and getting it wrong would fake a `pending_changes`
  verdict for a run that never reached AWS:

  - **`hcl_raw` / `terraconstructs` — pre-flight file probe.** Before running
    anything the block probes for the arm's local state file
    (`terraform.tfstate`, resp. the synthesized stack's); absent ⇒
    `not_verifiable` with a reason, and no plan is run at all. Needed because
    an offline `terraform plan` with no state is *always* exit `2` — the same
    code as a genuine pending change.
  - **`awscdk` — post-flight completion marker.** This arm keeps no local state
    (`cdk diff` reads the deployed CFN stack), so no local file can answer the
    question and a pre-flight probe is impossible. Instead, exit `1` is believed
    as `pending_changes` **only if** `idempotence.log` also contains
    `Number of stacks with differences:`. Needed because `cdk diff --fail`
    exits `1` both for "the diff found changes" and for "the CLI failed before
    diffing anything". MEASURED on this arm's exact pin (`aws-cdk 2.1135.0`,
    no range) with credentials unresolvable: exit `1`,
    `no credentials have been configured`, and **no marker** — and dropping
    `--fail` gives the same exit `1`, so a `--fail`-less pre-flight does not
    discriminate either. `cdk-toolkit.js` prints that marker unconditionally on
    the line before `return diffs && options.fail ? 1 : 0`, so it is present on
    every *completed* diff and absent on every early error exit.

  - **`terraconstructs` — plus a POST-SYNTH re-probe** (added 2026-08-20, task
    #15 round 3, from a verifier note). This is the one arm where the
    pre-flight probe and the plan look at the *same directory* with a
    `npx cdktn synth` in between: the probe confirms
    `cdktf.out/stacks/<id>/terraform.tfstate` exists, then synth rewrites that
    very directory. If synth ever cleans it, the plan runs with **no state**,
    exits `2`, and would be recorded as a genuine `pending_changes` verdict —
    precisely the fake verdict the pre-flight probe exists to prevent,
    delivered through the one window the pre-flight probe cannot see through.
    So the state file is re-checked **inside** the command, after synth and
    before terraform is believed; a vanished state prints
    `IDEMPOTENCE_STATE_VANISHED:` and exits the reserved rc `9`
    (`gen.py::IDEMPOTENCE_STATE_VANISHED_RC`, distinct from every code
    terraform and cdk produce), which the generated block maps to
    `not_verifiable` with that reason. Emitted only for the arm whose command
    can raise it, so no other arm's `tests/test.sh` moves a byte. **Not yet
    exercised live** — cdktf's own behaviour toward an existing stack-dir state
    file is what the first live terraconstructs brownfield run settles.

  All mechanisms deliver the same guarantee, and it is the guarantee, not the
  mechanism, that is the contract: **offline this tier is skipped with a
  reason, never fake-passed, on all three arms.** See
  `gen.py::IDEMPOTENCE_STATE_PROBE` / `IDEMPOTENCE_COMPLETION_MARKER`
  (the empty string in either map means "this arm uses the other mechanism").

**`gating: true` is fail-closed and AND-composed** with `live_check.gating`, byte
for byte the same contract: final reward is 1.0 iff the static tiers say 1.0 AND
the live check's `.outcome` is `"pass"` AND this tier's outcome is `"converged"`.
Both `pending_changes` and `not_verifiable` downgrade to 0.0.

**Emission is generation-conditional, not a runtime-gated branch.** Unlike
`live_check`'s gating (a dead runtime branch every task carries), the idempotence
block is emitted into `tests/test.sh` **only** for a spec that opts in — because
`build_test_sh` is otherwise one static template shared by every task, and an
always-emitted block would move every existing task's bytes. Verified: with
`idempotence` disabled, every pre-existing task's `tests/test.sh` is byte-identical.

Multi-step composition: the block rides the **final** step's `[steps.verifier] env`
only. An intermediate step is expected to leave pending changes (the next step is
what applies them), and gating it there would abort every trial at the
`min_reward` gate.

---

## 6. `provenance`

```yaml
provenance:
  author: <string>
  date: <YYYY-MM-DD>
  prereg_section_refs: [<string>, ...]
```

Free-form but non-empty. `prereg_section_refs` cites the specific
`iac-abstraction-benchmark-prereg.md` sections (and/or
`docs/iac-abstraction-aws-bench-plan.md` Phase 1 table rows) this scenario
implements — for the four real seed scenarios this is how Slice E's
oracle-equivalence CI report ties a generated task dir back to the
pre-registered design. For `specs/_toy/*.yaml`, state plainly that the fixture
is **not** a prereg scenario (see the toy spec's own entry).

---

## 7. Full annotated example

[`specs/_toy/toy-ssm-parameter.yaml`](_toy/toy-ssm-parameter.yaml) exercises
every field in this document at minimum cardinality (2 catches, one of each
optional-field shape populated at least once, `terraconstructs` enabled to
exercise the 3-arm generator path, `tier05_jsonata: null` to exercise the
"absent" path). It is deliberately boring — a create-only SSM parameter plus
a scoped-read IAM role — precisely so a generator bug shows up as "the
generator did something wrong" and not "the scenario was hard." **Never
register it as a benchmark scenario**: it has no `anti-L2` catch, its
`predicted_tier_caught` values are illustrative and explicitly not
provider-schema-verified (see the file's own header and Amendment 3's
"s3-lambda-log-retention catch is falsified by the pinned provider" lesson
for why that verification step matters and was deliberately skipped here).

---

## 8. Generated layout

```
tasks/<scenario-id>/
    awscdk/
        task.toml
        instruction.md
        environment/            # byte-copy of arms/awscdk/environment/, entry_file overwritten
            Dockerfile            # unmodified — see arms/awscdk build-context contract
            preflight.sh
            docker-compose.yaml   # `services:\n  main: {}`, same as upstream convention
            workspace/
                ...                # unmodified except lib/scenario-stack.ts (added/overwritten)
                                    # and bin/app.ts (import + instantiation rewritten once)
        tests/
            test.sh                # thin wrapper: exec static_tiers.sh; if $SPEC_LIVE_CHECK_ENABLED=true
                                    # (from this task's own [verifier] env, i.e. verifier.live_check.enabled
                                    # is true for this spec) and live_check.py exists, also run it
                                    # (informational only, §5)
            static_tiers.sh        # generated per arm: build step (awscdk: build_command;
                                    # terraconstructs: gen.py-injected `npx tsc -p tsconfig.json`)
                                    # -> synth_command ->
                                    # structural_asserts (tier "0") -> cfn-lint -> cfn-guard
                                    # (tier "1") -> writes /logs/verifier/reward.txt
            live_check.py           # scaffolded stub iff verifier.live_check.module names it;
                                    # never called while live_check.enabled == false
        solution/
            solve.sh                # writes a known-good lib/scenario-stack.ts, then runs the
                                    # same static_tiers.sh the agent's trial would run
        pre_invoke/                # present iff instruction.placeholders has a pre_invoke_random
            pre_invoke.py            # entry — never for file-seeding, see §2.2
            pre_invoke.sh
    hcl-raw/
        ...                        # same shape; environment/ byte-copy of arms/hcl-raw/environment/,
                                    # entry_file (main.tf) seeded resource-blocks-only; provider.tf
                                    # (offline provider bootstrap, non-agent-owned) copied unmodified
                                    # alongside it -- see §2.4, finding G1
    terraconstructs/               # present iff arms.terraconstructs.enabled == true
        ...                        # same shape; environment/ byte-copy of arms/terraconstructs/environment/,
                                    # entry_file (lib/scenario-stack.ts) seeded resource-logic-only;
                                    # main.ts (App/provider bootstrap, non-agent-owned) regenerated
                                    # alongside it every run -- see §2.4, finding G1

oracles/
    <scenario-id>/
        intent.md                  # oracle.intent, verbatim — the human-readable single source
                                    # of truth referenced by both policy bundles below
    rego/<scenario-id>/
        policy.rego                 # hand-authored from oracle.structural_asserts (tier "1") +
                                     # oracle.rego_hints; graded against hcl_raw's AND
                                     # terraconstructs' `terraform show -json` plan output
    cfn-guard/<scenario-id>/
        policy.guard                 # hand-authored from the same structural_asserts + cfn_guard_hints;
                                      # graded against awscdk's synthesized CFN template

specs/<scenario-id>.yaml            # the source; this file
```

### 8.1 A deliberate deviation from directory grouping some earlier notes implied

Earlier planning language (and this task's own brief) suggested one flat
`oracles/<scenario-id>/{intent.md, policy.rego, policy.guard}` directory per
scenario. That's **not** what this doc specifies, on purpose: Slice A already
scaffolded `oracles/rego/README.md` and `oracles/cfn-guard/README.md` as
top-level, oracle-type-first directories, each explicitly documented as "One
`.rego` bundle per scenario catch... populated in Slice D" / "One `.guard`
ruleset per scenario catch... populated in Slice D." Moving the policy files
under a scenario-first `oracles/<id>/` tree would silently contradict two
already-committed READMEs for no functional gain (the content addressed is
identical either way — this is purely a grouping choice). This schema keeps
`policy.rego` / `policy.guard` where Slice A already said they'd go
(`oracles/rego/<id>/`, `oracles/cfn-guard/<id>/`) and adds **only**
`oracles/<scenario-id>/intent.md` as new, scenario-first, shared-by-both-
policies content — satisfying the spirit of "one place to find everything
about this scenario's oracle" (the intent doc) without relocating what Slice
A already placed. Flagged here explicitly — see the response accompanying
this document for the same note; overrule by editing this section directly
if the flat grouping was actually intended.

### 8.2 Generation rules (what the generator must enforce, checklist)

1. `tasks/<id>/<arm>/` exists for `awscdk` and `hcl_raw` always; for
   `terraconstructs` iff `arms.terraconstructs.enabled == true`. A disabled
   `terraconstructs` produces **no directory at all**, not an empty/stub one
   — `arms/terraconstructs/README.md` §4's "excluded from this arm" scenarios
   (e.g. `sfn-jsonata`) must not appear under `tasks/sfn-jsonata/terraconstructs/`.
2. `instruction.md` is assembled per §2.1's template; the generator diffs the
   shared portion (everything before the language line) across all generated
   arms for the same scenario and fails if they differ post-placeholder-
   substitution — this is the mechanical parity check the plan promises,
   not a manual review step.
3. `environment/` is a **byte-copy** of the corresponding `arms/<arm>/environment/`
   directory, then `entry_file` (and, for `awscdk`, `bin/app.ts`) is
   overwritten. Every other file is untouched — no re-pinning versions, no
   editing the Dockerfile, at generation time. If an arm's toolchain pin needs
   to change, that happens in `arms/<arm>/` first (own PR/commit), and
   regenerating a scenario picks it up automatically on the next generator run.
4. `task.toml [metadata].id` (a UUID): if a `task.toml` already exists at the
   target path, **reuse its existing UUID**; only mint a fresh `uuid4` for a
   path that has never been generated before. Regenerating an existing
   scenario (e.g. after an instruction wording fix) must not spuriously
   change the task's identity.
5. `task.toml [scenario].scenario_id = "anchor"` for every v1 generated task
   (the only scenario that exists); `agent_role_name` defaults to
   `"QALocalInvocationApplicationRole"` (read-only) and `[concurrency] mode`
   defaults to `"read-only"` — correct for every scenario whose
   `verifier.live_check.enabled` is `false` (no generated task calls a
   mutating AWS API, which is what lets generated tasks run concurrently
   against the shared `anchor` scenario without a reset cycle). A spec may
   override both via `verifier.live_check.agent_role_name`/
   `.concurrency_mode` (§5, Slice G addition) — required for any scenario
   whose agent phase performs real AWS mutations (`apigw-redeploy` is the
   first: `agent_role_name = "QADeployApplicationRole"`,
   `mode = "mutating"` — see `docs/adding-scenarios.md` for the
   role-selection rule and the maintenance procedure for extending
   `QARolesStack`).
6. `pre_invoke/` is generated **iff** `instruction.placeholders` contains a
   `source: pre_invoke_random` entry — never for any other reason, in
   particular never to seed starter files into the agent's workspace (that
   happens at Docker-image-build time via `environment/`, per the CONTEXT
   constraint that starter files "ship in the arm's Docker image, not via
   S3" — the same reasoning extends to "not via pre_invoke" for a fully
   offline task, since pre_invoke and the agent run in different containers
   and only share the `/logs/pre_invoke/placeholder.json` → `{{token}}`
   channel).
7. `oracles/<id>/intent.md` is `oracle.intent` verbatim (§8.1).
   `oracles/rego/<id>/policy.rego` and `oracles/cfn-guard/<id>/policy.guard`
   are hand-authored (not generated) from `oracle.structural_asserts` +
   `oracle.rego_hints`/`cfn_guard_hints` — the generator scaffolds an empty
   file with a header comment pointing back at the spec if one doesn't exist
   yet, but does not attempt to synthesize policy logic itself.
8. `solution/solve.sh` per arm is hand-authored (like every `aws-bench-datasets`
   solution) to write a **known-good** `entry_file`, then invoke the same
   `tests/static_tiers.sh` the real trial runs — this is what the build
   plan's Phase 2 exit criterion ("reference solutions score 1.0 in all
   cells") checks.
9. A spec declaring `steps` (§2.6) emits §8.3's layout instead of a root
   `instruction.md` + `tests/` oracle. Every other rule above is unchanged —
   in particular rule 3 (`environment/` is still a byte-copy; a step never
   gets its own workspace) and rule 4 (the `[metadata].id` UUID is still
   reused).

---

### 8.3 Multi-step generated layout (`steps:`, §2.6)

```
tasks/anchor/<scenario-id>-<arm>/
    task.toml                       # + multi_step_reward_strategy = "final"
                                     # + [[steps]] (name, min_reward on non-final steps
                                     #   only, [steps.agent], [steps.verifier] incl. env)
                                     # + [pre_invoke] timeout_sec, iff any step declares one
                                     # + [metadata] scenario_title (the whole-arc title;
                                     #   [task] description carries workspace_title, §0.1)
    environment/                    # UNCHANGED — one workspace, shared by every step
    steps/
        01-<slug>/
            instruction.md          # this step's prompt (per arm)
            tests/                  # this step's oracle: _assert_lib.sh, static_tiers.sh
                                     # (that step's assert projection), test.sh,
                                     # policy.{rego,guard}, live_check.py if live-checked
            pre_invoke/pre_invoke.sh # iff the step declares pre_invoke (never on step 01)
            solution/solve.sh        # reference solution for THIS step (non-final steps only)
        02-<slug>/
            instruction.md
            tests/
    tests/
        README.md                   # the ONLY file here — see below
    solution/                       # UNCHANGED, task-root: the whole-scenario reference
        solve.sh                     #   solution (= the FINAL step's reference) and every
        broken/<catch>/solve.sh      #   negative fixture, graded against the FINAL oracle
    (no root instruction.md)
```

**No root `instruction.md`.** Harbor sets `Task.instruction = ""` whenever
`[[steps]]` is present, and `gates/equipping.py` folds `steps/*/instruction.md`
into the equipping hash *only in the absence of a root one*. A leftover root
`instruction.md` would silently revert the hash to the single-step key while
the agent never saw that text, so the generator **deletes** it rather than
tolerating it.

**The shared root `tests/` holds no oracle.** Harbor uploads it during **every**
step's verification and only empties `/tests` at the start of the **next**
step's verification — i.e. after that step's agent has already run
(`harbor/verifier/verifier.py::_resolve_tests`,
`harbor/trial/multi_step.py::_reset_shared_step_verifier_dirs`). Anything
step-specific placed there is readable inside a later step's agent phase. The
generator writes a single step-agnostic `README.md` saying so, and **hard-errors**
rather than deleting a hand-authored `live_check.py` it finds there — that is
answer-key material, and only the author can say which step owns it.

**Reference solutions.** The task-root `solution/` tree is unchanged and stays
the whole-scenario reference: `gates/oracle_falsifiability.py` runs it and every
`solution/broken/<catch>/` fixture against the **final** step's oracle, which
§2.6 guarantees is the full tier suite — so those rows prove byte-for-byte what
they proved before the decomposition. Each **non-final** step additionally gets
`steps/<name>/solution/solve.sh`, required to score 1.0 against its own subset
oracle; that is the new obligation the decomposition creates (an unsatisfiable
intermediate oracle would abort every trial at the `min_reward` gate before the
next prompt ever fired). The final step has no `steps/<name>/solution/` — its
reference is the task-root one.

---

## 9. Open questions (for the human, not for an implementing agent to guess past)

These are flagged, not silently resolved, because each has a real decision
behind it that the schema above commits to one answer for — recorded here so
a reviewer can find and override any of them in one place.

1. **§8.1 directory grouping.** This schema keeps `policy.rego`/`policy.guard`
   under `oracles/rego/<id>/` and `oracles/cfn-guard/<id>/` (matching Slice
   A's already-committed READMEs) and adds a new `oracles/<id>/intent.md`,
   rather than moving everything under one flat `oracles/<id>/` tree as an
   earlier note phrased it. No functional difference either way — purely a
   directory-grouping call. If the flat grouping was actually intended,
   override by editing §8/§8.1 and moving the two placeholder READMEs.
2. **`predicted_tier_caught.hcl` as "the TF-shaped arms as a group," with a
   `terraconstructs_override` escape hatch (§3).** This reads the user's
   two-key `{awscdk, hcl}` shape as intentionally collapsing `hcl_raw` and
   `terraconstructs` into one predicted tier by default (since they share one
   Rego oracle and, per §4.2, literally the same `tf_jsonpath` expressions),
   with the override existing only for the confirmed case where
   terraconstructs' own typed surface diverges. An alternative reading is
   that `hcl` was shorthand for `hcl_raw` specifically and terraconstructs
   should have always been a required third key. Either is implementable;
   this schema picked the collapsing reading because it matches how the
   oracle is actually structured (§4.2) and because Amendment 3's own
   terraconstructs research already found the divergent case exists and
   named it precisely (the log-retention enum) — the override exists to
   carry exactly that finding.
3. **`instruction.placeholders` scope.** v1's only real placeholder need
   (per the anchor scenario exporting nothing) is `literal` and occasionally
   `pre_invoke_random`. `scenario_export` is speced (§2.2) purely as
   forward-compat for a hypothetical future non-anchor scenario or the
   Phase 2 state track — no v1 spec should use it, and the generator does not
   validate it beyond syntax (it can't, per §2.2). Confirm this is
   acceptable scope now, rather than deferring the whole placeholder
   mechanism until it's actually needed.
4. **`live_check` never gates v1 reward, even where `enabled: true` (§5,
   now real as of `apigw-redeploy` / `DECISIONS.md` "Amendment 12", not
   just "some future spec").** This schema treats flipping
   `live_check.enabled` as strictly additive/observational — confirmed,
   not just proposed: `apigw-redeploy`'s `tests/test.sh`-invoked
   `live_check.py` run still never writes `/logs/verifier/reward.txt`
   (only `/logs/verifier/live_check-result.json`). The genuinely GATING use
   of the same module is a separate call shape entirely
   (`live_check.py --expect {ok,stale}`, invoked directly by
   `solution/solve.sh`/`solution/broken/*/solve.sh`, never by the generated
   `tests/test.sh`) — worth reviewing if a future spec wants the
   verifier-invoked path itself to gate reward, since that would be the
   "replace the static tiers as the reward source" reading this point
   originally flagged as unconfirmed, and still is.
