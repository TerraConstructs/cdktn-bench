# Spike: can `terraform console -plan` replace the bench's own HCL parsing?

Status: **measured; NO for the graded question, YES for one narrow new
capability.** Executed 2026-09-24, host `terraform 1.15.8`. Every workspace was
staged exactly as `gates/artifact_collector.py` /
`gates/oracle_falsifiability.py::_run_solve` stage one — `environment/workspace`
flattened into a scratch root — under `gates/aws_stub.py::running_stub` and, for
the module workspace, `gates/tf_registry.py::arm_env("hcl_modules", …)`. No real
AWS call was made. Transcripts: scratch `console/exp{1..11}.py`.

The question: can Terraform's own evaluator replace `tests/hcl_merge.py`
(`generator/gen.py::HCL_MERGE_PY`, `specs/SCHEMA.md` §4.6) — hcl2json over the
agent's `.tf` plus the `#jsonencode` re-parse — so `local.*` resolution stops
being our parser's job?
**It turns on one distinction.** `hcl_merge` + `oracles/rego/lib/
hcl_traversal.rego` resolve a symbol to a **referent identity**
(`_resolved()`, `hcl_traversal.rego:791`: `referent`, `referent_path`,
`instance`, `attr_path`); `terraform console` resolves it to a **value**. Every
ARN the s3-notification oracle grades is provider-computed, so console returns
the same `(known after apply)` for the reference solution and for every
laundering fixture — it cannot see the hop the oracle exists to see.
---

## 1. Mechanics

| Property | Measured behaviour |
|---|---|
| **Expressions per invocation** | **Only ONE result is printed — the LAST line.** `'"a"\n"b"\n"c"'` → `"c"`. The only batching is **one composite expression** (`{a = …, b = …}`), which does print every member. |
| Errors | rc=1, diagnostic on **stderr**, **nothing on stdout**, and the whole invocation is lost regardless of the bad expression's position. Diagnostics always say `line 1` (each line compiles as its own input). |
| Error hardening | `try()`/`can()` rescue **dynamic** errors (`Unsupported attribute` → `try(…,"NO")` = `"NO"`) but **not static reference errors** (`Reference to undeclared local value / resource / module / input variable` stays rc=1 through `try()`). A composite batch cannot be made total. |
| `-json` | **Does not exist** (`flag provided but not defined: -json`). Output is the REPL's `cty` rendering. |
| Format hazards | `"key" = value` objects, trailing commas, and markers that are neither JSON nor HCL: `tolist([…])`, `toset([…])`, `tostring(null)`, `tomap(null) /* of string */`, `(sensitive value)`, `(known after apply)` (unquoted, so distinguishable from the quoted *string* `"(known after apply)"`). |
| **Parse-free readout** | Wrap the expression in `jsonencode(...)`: stdout is one JSON string literal, so `json.loads(json.loads(line))` recovers the document. Round-trip verified on newlines, tabs, quotes, `>`/`&`, `é`, an emoji, floats, `true`, `null`. The only readout needing no parser of ours. |
| `-plan` required | Without it every resource attribute is `(known after apply)` (no state), literals included. `-plan` is **boolean**: `-plan=plan.tfplan` → `invalid boolean value "p2.tfplan" for -plan`, so **a saved plan cannot be reused** and every call re-plans. |
| Provider auth | Required, because it really plans: with `AWS_*` scrubbed, rc=1 `No valid credential sources found` + IMDS attempts, plus a **stdout** `Warning: Due to the problems above, some expressions may produce unexpected results.` |
| Wall time | `console -plan` 1.08–1.23 s, flat in stdin length (1 vs 40 lines: 1.12 s vs 1.09 s — only the last is evaluated). Bare `plan -out` on the same workspace 1.34–2.07 s; on the module workspace `plan` 6.4 s vs `console -plan` 1.1–1.6 s. **One invocation ≈ one plan.** |
| Prompting | None observed, but `console` rejects `-input=false`, so an undefaulted `variable` would prompt. Not reproduced (no arm workspace declares one). |
| Determinism | Byte-identical across 3 runs of the same set, both workspaces. |
---

## 2. Coverage — root workspace (`s3-notification-authoritative-singleton`, hcl_raw)

Reference `solution/solve.sh`, staged and planned green.

| Expression | `console -plan` | `hcl_merge` + `hcl.*` |
|---|---|---|
| `local.arns` | `{ "audit_topic" = (known after apply), "media_bucket" = (known after apply) }` | the source strings `"${aws_s3_bucket.media.arn}"` / `"${aws_sns_topic.audit.arn}"` |
| `local.arns.media_bucket` | `(known after apply)` | `hcl.slot` → `resolved`, `referent = aws_s3_bucket.media.arn`, `instance = ["aws_s3_bucket","media"]`, `attr_path = ["arn"]` |
| `aws_s3_bucket.media.arn`, `aws_sns_topic.audit.arn` | `(known after apply)` | n/a (plan carries the reference) |
| `aws_s3_bucket.media.bucket`, `aws_sns_topic.audit.name`; `keys(local.arns)` | literals and key sets resolve | same, from the plan / parsed `locals` |
| `aws_sns_topic_policy.audit.policy` (the graded `jsonencode` body) | `(known after apply)`; `jsondecode(…)` of it too | `hcl.resource_jsonencode(…)` → the **full re-parsed document**, leaves still `"${local.arns.…}"`, so `Statement[*].Condition.*["aws:SourceArn"]` is addressable **by position** |
| `aws_iam_role.ingest.assume_role_policy` (all-literal `jsonencode`) | known JSON; `jsondecode(…).Statement[0].Principal` → `{ "Service" = "lambda.amazonaws.com" }` | same document, unresolved leaves |
| `aws_lambda_permission.allow_s3_invoke.source_arn` | `(known after apply)` | the graded slot, via `hcl.slot(expressions.source_arn.references)` |

### Broken fixtures — the decisive measurement

Every `local.*` symbol in each laundering fixture's source was evaluated.
**Without exception the answer was `(known after apply)`:**
`lambda-permission-scoped-to-the-topic-arn-behind-a-local` (2 symbols),
`…-to-a-decoy-bucket-behind-a-local` (2), `sns-topic-policy-attached-to-a-
lambda-arn-behind-a-local` (3), `…lambdas-own-arn-behind-a-5-hop-chain`
(`local.a`…`local.e`, all 5), `…behind-a-dotted-key-local` (2), and
`tf-json-source-arn-laundered-through-an-object-spelled-local` (2, in
`main.tf.json` — console reads that natively, one branch the merge needed).
`sns-topic-policy-not-scoped-to-bucket` and `inline-…-named-only-in-the-sid`
declare no locals; their catch is *inside* a `jsonencode` body, which console
reports whole-unknown. `all-wiring-hidden-inside-a-module` was not measured (its
`solve.sh` also writes a module dir this spike's heredoc extraction did not
stage); §3 shows module internals are unaddressable anyway.

**Console's answer for the correct hoist and for the wrong-resource hoist is the
same string.** The false-PASS defect §4.6 exists to close is undetectable from
values at any granularity — that is what "evaluate against the planned state"
means when the value is provider-computed.
---

## 3. Coverage — module workspace (`s3-bucket-hardening-decomposition`, hcl_modules)

Reference `main.tf` (`terraform-aws-modules/kms/aws` 4.2.2 + `s3-bucket/aws`
5.16.1) plus a root `local.sse` carrying a module output and passed *into* the
second module call; offline registry via `arm_env`.

| Address | Result |
|---|---|
| `module.archive` | **an object of the module's declared OUTPUTS only** (15 keys), unknowns per leaf |
| `keys(module.archive)` | the output names — enumerable |
| `module.archive.s3_bucket_arn`, `module.archive_key.key_arn` | `(known after apply)` — addressable, unknown |
| `module.archive.aws_s3_bucket.this[0].arn` / `.aws_s3_bucket.this` | **rc=1 `Unsupported attribute … does not have an attribute named "aws_s3_bucket"` — module-internal resources are NOT addressable from root. Confirmed.** |
| `module.archive.bucket` (an **input** to the call) | rc=1 `Unsupported attribute` — module inputs have no root address |
| `module.archive.aws_s3_bucket_versioning_status` | **`"Enabled"`** — an output derived from an input crosses the boundary **known** |
| `module.archive_key.key_policy` | a **fully known** IAM document rendered *inside* the module — a document `hcl_merge` can never see |
| `local.key_arn` (= a module output); `local.sse` (object holding one) | evaluated, not refused: `(known after apply)` at the leaf, `sse_algorithm = "aws:kms"` known beside it |

This is a capability the bench lacks: `hcl_traversal.rego`'s header declares
`module.x.out` UNRESOLVABLE by design, `docs/design/tf-modules-arm.md` §1 lists
indexed/multi-reference outputs and default-fallback inputs as honestly
unresolvable, and `normalise_plan` (`generator/verify_py.py:600`, emitted into
every task's `tests/tiers.py`) marks them `x_unresolved: {module_output,
module_input_chain, module_input_default, …}`. Console resolves the *known*
subset and refuses the rest loudly — but it never opens module internals, so it
cannot substitute for the hoist `normalise_plan` performs.
---

## 4. Plan-time unknowns: granularity

Purpose-built workspace: `locals.definition` is an ASL object with literal
Pass/Choice/Fail/Succeed states plus one **Task** whose `Arguments.FunctionName`
is `aws_lambda_function.enrich.arn`, and `aws_sfn_state_machine.order_batch.
definition = jsonencode(local.definition)`. The plan confirms the blindness:
`after_unknown.definition == true`, `change.after.definition == null`, and
`planned_values…values` carries **no `definition` key at all** — so the assert's
`…values.definition|fromjson.QueryLanguage` (`specs/sfn-jsonata.yaml:331`) is
UNRESOLVABLE, exactly as `oracles/rego/sfn-jsonata/policy.rego`'s
`unknown_definition` fail-closed deny states.

**Unknownness is per-LEAF; containers stay known.**

| Expression | Result |
|---|---|
| `local.definition` | whole object prints; only `States.Enrich.Arguments.FunctionName` is `(known after apply)` |
| `keys(local.definition.States)`; `{for k,v in … : k => v.Type}` | all five state names / types, known |
| `local.definition.QueryLanguage` | **`"JSONata"`** |
| `…States.ComputeTotals` (Pass), `…States.CheckBudget` (Choice) | fully known — `{% … %}` string verbatim, `Choices[0].Condition` intact |
| `local.definition.States.Enrich` (Task) | known object with **one unknown leaf**; `Type`/`Resource`/`Next`/`Payload` all known |
| `jsonencode(…States.ComputeTotals)` | clean JSON string; double-`json.loads` exact |
| `jsonencode(…States.Enrich)`, `jsonencode(local.definition)`, `aws_sfn_state_machine.order_batch.definition`, `jsondecode(that).QueryLanguage` | **`(known after apply)`** — `jsonencode` is not unknown-tolerant: one unknown leaf makes the whole encoding unknown |
| `jsonencode({for k,v in local.definition.States : k => v if v.Type != "Task"})` | **fully known JSON** for all four non-Task states |
| `[for k,v in … : k if v == null]` (predicate over an unknown) | `(known after apply)` — an unknown-length collection collapses whole |

Rule: **read known subtrees by address, or by a `for` whose *predicate* touches
only known values; never wrap an unknown leaf in `jsonencode`.**

**Enough for the sfn live check?** Yes for what it tests.
`tasks/anchor/sfn-jsonata-hcl-raw/tests/live_check.py` submits only a **Pass**
(`ComputeTotals`) and a **Choice** (`CheckBudget`) to `TestState`, passes **no
`--role-arn`** ("Pass and Choice need none, and passing one would additionally
require iam:PassRole"), creates no resources, and no `CASES` entry exercises a
Task. Both bodies come back fully known, so an ARN placeholder on an untested
Task state is irrelevant to it. (No AWS call was made here.)

**Tier 0?** `local.definition.QueryLanguage` is known, so
`query-language-is-jsonata` **does** get a resolvable path from console subtree
evaluation in the very case `x_after_unknown.definition: true` marks blind. The
caveat: it grades the **local**, not the resource attribute. They coincide only
because `definition = jsonencode(local.definition)` is the identity; an agent
writing `merge(local.definition, {...})` breaks that, and the expression to
evaluate would have to be re-derived per artifact.
---

## 5. Integration sketch (if adopted)

* **Where.** One step in the generated `tests/static_tiers.sh`, beside or in
  place of `python3 "$DIR/hcl_merge.py"`, in the agent's project dir with
  `.terraform` already initialised.
* **Cost.** The verifier's existing `plan.tfplan` **cannot** be reused: every
  expression is a fresh plan. With no batching but one composite expression
  (which dies whole on the first bad sub-expression), a policy reading *n*
  positions costs *n* plans — ~8 extra for s3-notification, ~1.1 s each
  locally and 6.4 s-scale on the module arm.
* **Env.** Whatever the plan already runs under (live credentials in a trial,
  `running_stub()` on the host). No new pinned binary (vs hcl2json's 4.1 MB) and
  no hcl2json/terraform parser skew, retiring `ENGINE_ERROR`'s first cause.
* **Document shape.** Replace `_hcl` with `_resolved`: keyed by the
  **expression string the policy declares**, each entry `{"expr", "status":
  "known"|"unknown"|"error", "value": <decoded JSON>, "stderr"}`. Produce every
  entry via `jsonencode(<expr>)` and read it with a double `json.loads`;
  map `(known after apply)`, `(sensitive value)` and rc≠0 onto the non-`known`
  statuses. The expression set has to be declared as a data document the shell
  reads, because Rego can neither shell out nor glob — the same constraint
  that already puts the `.tf` glob in the shell.
* **Policies.** `hcl.slot`'s three-valued contract survives
  (`status` → `resolved`/`unresolvable`), but there is **no referent** for
  `referent`/`instance`/`attr_path`, so every rule in
  `oracles/rego/s3-notification-authoritative-singleton/policy.rego` that
  compares a referent to an instance (`slot_names_arn_of`, `instance_addr`,
  the decoy-instance rules around lines 1312–1437) has nothing to compare and
  would be deleted, abandoning the catches it implements.
* **Gates.** `gates/hcl_merge_bytes.py` generalises directly (byte-compare
  `/logs/verifier/oracle-input.json` per fixture against a git-recovered
  baseline); zero drift adds `verifier_parity.py` (reward bytes + logs sha256 +
  parsed stdout lines) and `tier0_parity.py`, on `plan_normaliser_parity.py`'s
  model. **But parity is not provable here:** §2 shows verdicts *change* on six
  broken fixtures, so the gate reports drift by construction.

### Risks

1. **No referent, only values** (§2) — fatal for the identity contract.
2. **One error kills the invocation**, and static reference errors are
   unrescuable by `try()`/`can()`. The agent owns the file, so `local.<typo>`
   or a renamed resource turns a graded position into rc=1-with-empty-stdout,
   which must map to a loud status and never to a pass.
3. **One plan per expression**, un-amortisable.
4. **Provider auth at plan time**, plus a stdout `Warning:` line on failure a
   naive reader could mistake for a value.
5. **Prompting**: `console` rejects `-input=false`; an undefaulted `variable` in
   agent code could block the verifier. Not reproduced, not mitigated.
6. **Output format**: only the `jsonencode(...)` route avoids re-parsing.
---

## 6. Recommendation

**Do not replace `hcl_merge`. Complement it, narrowly, and only when a spec
needs it.**

* **Replace — NO.** `hcl_merge` yields a *referent*; console a *value*; every
  ARN this oracle grades is plan-time-unknown. Measured on all six laundering
  fixtures and the reference: identical `(known after apply)`. Adopting console
  deletes the rules that catch the original false PASS, costs one plan per
  expression, and fails its own parity gate.
* **Complement — YES, for one thing.** `console -plan` is the only mechanism
  measured that reads **known subtrees around an unknown leaf**: it recovers
  `QueryLanguage` and whole Pass/Choice bodies from a `definition`
  `planned_values` omits and `x_after_unknown` can only mark blind. It is also
  the only thing that reads a known `module.x.out` VALUE chain, which
  `hcl_traversal.rego` and `normalise_plan` both refuse on principle.
  **Narrowed by Amendment 46 phase 6 slice B**, which needed the module-output
  hop and did not need console for it: the REFERENCE a module output holds is in
  the plan's own configuration
  (`module_calls.<c>.module.outputs.<out>.expression.references`), so
  `module.media.s3_bucket_arn` resolves to
  `module.media.aws_s3_bucket.this[0].arn` with no evaluation at all. What stays
  out of reach -- and what this memo's ruling still governs -- is the VALUE, and
  a `local` inside an installed module body, which no configuration key carries.
* **Sequencing.** Neither use is needed today: `sfn-jsonata`'s reference
  definition is all-literal and its policy already denies the unknown case
  fail-closed. Cite this memo when a spec first *needs* a known subtree out of
  an unknown attribute; such a spec owes the composite-expression batching, the
  error-status mapping (risk 2) and a byte gate of its own.
