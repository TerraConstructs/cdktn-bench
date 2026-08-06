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
difficulty: <1|2|3>
services: [<string>, ...]        # boto3 service ids, matches aws_services convention
arms: {...}                       # §1
instruction: {...}                # §2
seeded_files: [{...}, ...]        # §2.5, optional, default []
catches: [{...}, ...]             # §3
oracle: {...}                     # §4
verifier: {...}                   # §5
provenance: {...}                 # §6
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Kebab-case, matches `^[a-z][a-z0-9-]*$`. Becomes the directory name under `tasks/`, `oracles/rego/`, `oracles/cfn-guard/`, and `oracles/<id>/` (§8). Must equal the spec's own filename stem (`specs/<id>.yaml`), enforced by the generator at load time — this is what lets the generator refuse to run against a renamed-but-not-moved file. |
| `title` | string | yes | Short human title, shown in any results viewer. Not used in `instruction.md` — the instruction body is `instruction.shared_body`, not `title`. |
| `difficulty` | int, `1`–`3` | yes | 1 = single-resource, 2 = multi-resource wiring, 3 = cross-service (prereg §5 difficulty gradient). The generator maps this to `task.toml [metadata] complexity`: `1→Atomic, 2→Sequential, 3→Orchestrated` — a generator convention, not a spec field; do not add a `complexity` field to the spec. |
| `services` | list[string] | yes, ≥1 | boto3 service client ids (e.g. `ssm`, `iam`, `lambda`), lower-case. Written into every generated `task.toml [metadata] aws_services`. Purely descriptive in v1 (no live boto3 call ever validates against it — that upstream `test/aws_service_catalog.ts` check is aws-bench-datasets' own CI, not ours), but keep it accurate; a later live-check phase (§5) will care. |

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
  build_command: <string, optional — only awscdk needs this (tsc compile step)>
  synth_command: <string>          # or `plan_command` for hcl_raw
  json_fields: [{name: <string>, description: <string>}, ...]   # optional, default []
```

| Arm | `entry_file` | Non-agent-owned bootstrap file | `artifact_path` | commands |
|---|---|---|---|---|
| `awscdk` | `lib/scenario-stack.ts` (class `ScenarioStack`, resource logic only) | `bin/app.ts` — `App`/`ScenarioStack` instantiation; the generator rewrites its import/instantiation once per scenario, never per trial | `cdk.out/ScenarioStack.template.json` | `build_command: npm run build`, `synth_command: npx cdk synth --no-lookups --quiet -o cdk.out` |
| `hcl_raw` | `main.tf` (resource blocks ONLY — no `provider` block; see below) | `provider.tf` — the `terraform{}`/`provider "aws" {}` block + `skip_*`/dummy-credential fixture lines (byte-copied from `arms/hcl-raw/environment/workspace/provider.tf`, never per-scenario content) | `plan.json` | `synth_command` not used; `plan_command: terraform init && terraform validate && terraform plan -out=plan.tfplan && terraform show -json plan.tfplan > plan.json` |
| `terraconstructs` | `lib/scenario-stack.ts` (class `ScenarioStack extends AwsStack`, resource logic only) | `main.ts` — `App`/`providerConfig` bootstrap (incl. the offline `skip_*`/dummy-credential fixture and the mock-STS `endpoints` pointer), imports and instantiates `ScenarioStack`; regenerated every run, mirroring `awscdk`'s `bin/app.ts` | `cdktf.out/stacks/<id>/plan.json` where `<id>` is the generator-assigned stack id, always equal to `id` (the spec's own scenario id) — **not** `cdk.tf.json`: `generator/gen.py::build_static_tiers_sh` always appends a real `terraform init && terraform plan && terraform show -json` step after `synth_command`, chdir'd into the synthesized stack's own directory, so this arm is graded in the same plan-JSON shape `hcl_raw` is (see §4.2) | `synth_command: npx cdktn synth` |

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

---

## 3. `catches`

```yaml
catches:
  - name: <kebab-case, unique within the spec>
    taxonomy: typed-value-trap | graph-dependency | nested-attribute | anti-L2
    description: <string — the natural-language catch, no thresholds pasted into instruction.shared_body>
    predicted_tier_caught:
      awscdk: "0" | "0.5" | "1"
      hcl: "0" | "0.5" | "1"
      terraconstructs_override: "0" | "0.5" | "1" | null   # optional, default null
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
```

- `budget.max_iters`: the `MAX_ITERS` feedback-cycle cap (prereg §4). `8` is
  the pre-registered default; a spec may lower it (never raise it without a
  logged amendment — this is a pre-registered budget, not a per-scenario
  knob to tune away a hard scenario).
- `live_check`: `enabled` **must be `false`** for every v1 spec — this
  benchmark's v1 oracle is synth/plan-only per the CONTEXT constraint ("v1
  verifier is the STATIC tier stack ... NOT live-AWS check.py"). `module` is
  a **path**, relative to the generated task's own `tests/` directory,
  naming the hook the generator scaffolds as an inert stub (§8) — never
  invoked by the generated `tests/test.sh` while `enabled: false`, and never
  contributing to `/logs/verifier/reward.txt` even in a future run where it's
  flipped on (its result, if ever executed, is written to a separate
  `/logs/verifier/live_check-result.json` for out-of-band analysis, per the
  Phase 2 forward-compat note in §8). Flipping this to `true` for a real
  scenario is a Phase 2 decision (prereg §11), not something the generator
  or a spec author does unilaterally in v1.

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
            test.sh                # thin wrapper: exec static_tiers.sh; if $CDKTN_BENCH_LIVE_CHECK=1
                                    # and live_check.py exists, also run it (informational only, §5)
            static_tiers.sh        # generated per arm: build_command -> synth_command ->
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
   (the only scenario that exists); `agent_role_name = "QALocalInvocationApplicationRole"`
   (read-only — no generated v1 task ever calls a mutating AWS API, since
   `verifier.live_check.enabled` is always `false` in v1, see §5);
   `[concurrency] mode = "read-only"` for the same reason, which is what lets
   generated tasks run concurrently against the shared `anchor` scenario
   without a reset cycle.
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
4. **`live_check` never gates v1 reward, even if `enabled: true` is set on
   some future spec (§5).** This schema treats flipping `live_check.enabled`
   as strictly additive/observational until a Phase 2 decision explicitly
   changes the reward contract — worth confirming that's the intended
   meaning of "leaves an optional live_check.py hook (disabled by default)
   for later AWS-enabled runs" versus a stronger reading where enabling it
   was meant to replace the static tiers as the reward source outright.
