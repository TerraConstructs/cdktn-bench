# Plan normaliser: survey before building

Status: research memo, 2026-09-21. Input to `docs/design/tf-modules-arm.md`
milestone 3 ("plan normaliser with the zero-drift parity gate"). Nothing here
is scheduled; §5 is the recommendation and the price.

All Terraform claims below were verified empirically against a locally built
module-shaped plan (Terraform **v1.15.8**, `format_version` **1.2**, no
provider needed: `terraform_data` plus the builtin `terraform_remote_state`
data source), scratch at `…/scratchpad/norm/{tf,tf2,plan.json,plan2.json,plan3.json,proto.py}`.

## 1. What Terraform itself gives us

Source: `internals/json-format.mdx` (from `hashicorp/web-unified-docs`,
`content/terraform/v1.14.x`), plus the fixtures.

* **Values side recurses, addresses are absolute.** `planned_values.root_module`
  has `resources[]` and `child_modules[]`, each child "the same structure as the
  root_module object" plus an absolute `address`. Nesting is real recursion:
  `module.outer` carries `resources: []` and a nested `child_modules[0].address ==
  "module.outer.module.inner"`. Instance keys sit in the module segment verbatim:
  `module.many[0]`, `module.keyed["k1"]`, `module.fe["a"].module.inner`. A
  resource also carries `index` when `count`/`for_each` is on the *resource*, and
  `module_address` (on `resource_changes`; omitted at root).
* **`planned_values` cannot express "unknown".** Doc, verbatim: "Any unknown
  values are omitted or set to null, making them indistinguishable from absent
  values; callers which need to distinguish unknown from unset must use the
  plan-specific or configuration-specific structures described in later
  sections." Confirmed: a resource whose `input` is unknown has no `input` key
  in `values` at all, while `resource_changes[].change.after_unknown` is
  `{"id":true,"input":true,"output":true}`. **Our three-valued grading is only
  possible from `resource_changes`.** (`proposed_unknown`, documented as a
  values-representation of knownness, is *not emitted* by 1.15.8 `show -json` —
  do not build on it.)
* **`resource_changes[]` is already flat and complete.** Doc: "All resources in
  the configuration are included in this list." Each entry has the full `address`
  (module and instance keys included), `module_address`, `mode/type/name/index`,
  `change.{after,after_unknown,after_sensitive}`. Verified at every nesting depth
  and — importantly — after an apply, where all five resources reappear with
  `actions: ["no-op"]`: it is not a changed-only list.
* **`change.after` == `values`, byte-for-byte.** Verified over every resource in
  both fixtures, including nested-object shapes and explicit `null`s; `after` is
  declared as a `<value-representation>` in the doc, i.e. the same schema.
* **Gaps in `resource_changes` vs `planned_values`:** (a) a data source **read at
  plan time** appears in *neither* — it lands in
  `prior_state.values.root_module.resources[]` with `mode: "data"` (verified); a
  *deferred* read appears in both with `actions: ["read"]`. (b) `delete` entries
  have `after: null` where `planned_values` omits the resource. (c) `deposed`
  objects make `address` non-unique; the doc's unique key is `address` +
  `deposed`. (d) `planned_values` alone carries `schema_version`,
  `provider_name`, `sensitive_values`.
* **Configuration side is module-local and unexpanded.** `configuration.root_module`
  has `resources[]`, `outputs`, `variables`, `module_calls`; each
  `module_calls.<call>` has `expressions` (the caller's arguments),
  `count_expression`/`for_each_expression`, and `module` (recursively
  root_module-shaped). Note a doc/impl divergence: the key is **`source`**, not
  the documented `resolved_source` (fixture, and `terraform-json` `config.go:180`
  `Source string \`json:"source,omitempty"\``). Child resource `address` is
  module-**local** (`terraform_data.inner`); only `provider_config_key` is
  prefixed (`module.outer.module.inner:terraform`). There are **no module
  instances** here: one `module_calls.many` for two `module.many[0..1]`.
* **`references` semantics.** Doc: "Multi-step references will be unwrapped and
  duplicated for each significant traversal step… Callers should only use string
  equality checks here". Verified: a module output read gives
  `["module.a.out_direct", "module.a"]`; an attribute gives
  `["terraform_data.root_res.id", "terraform_data.root_res"]`; an output gives
  `["terraform_data.inner.output", "terraform_data.inner"]`. Partial refs (`data`,
  `module` alone) are excluded, and `upper(var.name)` still yields `["var.name"]`
  — functions do not erase references.
* **Two config-side blind spots, both documented or observed.** Doc note:
  "Expressions in `dynamic` blocks are not included in the configuration
  representation." And observed: `for_each = toset([...])` on a module call emits
  **no `for_each_expression` key at all** (only `expressions` and `source`),
  whereas `for_each = { a = "x", b = "y" }` emits
  `for_each_expression.constant_value`. So config alone cannot always tell that
  a module call repeats; the values side always can.
* **Terraform does expose resolved cross-module edges — in the graph, not JSON.**
  `terraform graph -type=plan` emits DOT with variable and output nodes and their
  edges (verified, `scratchpad/norm/graph.dot`): `…inner.terraform_data.deepest ->
  …inner.var.deep -> module.outer.var.mid -> terraform_data.seed`, and downstream
  `terraform_data.sink -> module.outer.output.mid_out -> …inner.output.deep_out`.
  Transitive closure therefore yields resource→resource edges across boundaries.
  Two reasons it is not the answer: **DOT only** ("The graph is presented in the
  DOT language" — no `-json`), and **node-level, not attribute-level** — it never
  says *which* argument holds the reference, which is exactly what every
  graph-edge rule in `oracles/rego/` asserts. It also needs an init'd working
  directory. Keep it as an optional cross-check oracle, not as input.
* **`terraform plan -json`** is only the machine-readable UI log
  (`planned_change`/`change_summary` events, `internals/machine-readable-ui.mdx`):
  no configuration, no `after_unknown`, no module tree. `terraform show -json
  <planfile>` stays the only source.

## 2. What already flattens or traverses plan JSON

Everything surveyed falls into four bands. **Nobody exposes a callable, importable
cross-module reference resolver; exactly one project has the logic at all.**

**Band 1 — types only, no traversal.** `hashicorp/terraform-json` (Go, MPL-2.0,
v0.28.0 2026-07-10, active): `tfjson.StateModule` is `Resources` +
`ChildModules` + `Address`; `ConfigModule.ModuleCalls` (`config.go:84`) embeds
`Module *ConfigModule`; `Expression.References` is raw `[]string`;
`Change.AfterUnknown interface{}` is a lossless pass-through. A grep for
`func .*(walk|flatten|traverse)` finds nothing outside `sanitize/`. Sentinel's
`tfplan/v2` `resource_changes` is likewise already flat with `module_address` and
a string-or-int `index`, and `tfconfig/v2` `module_calls` hands back raw
`references` with no resolution — no resolved cross-module edge in either.

**Band 2 — values-side hoist; no usable cross-boundary rewrite.**

| tool | lang / licence / state | flatten helper | refs across modules | `count`/`for_each` | `after_unknown` |
|---|---|---|---|---|---|
| **checkov** 3.3.19 | Py, Apache-2.0, active (2026-09-17) | `plan_parser.py::_find_child_modules` (recursive) + `_get_module_call_resources` (walks `module_calls.<n>.module`) | **no** — `_add_references` picks the first ref `not startswith(("var.","local."))`, discarding every cross-boundary one, and tags it as `references_`/`__address__` | count only: `COUNT_PATTERN = r"\[?\d+\]?$"` in `_sanitize_count_from_name` never matches `["k"]`, so string-keyed `for_each` modules get `conf=None` and lose reference enrichment entirely | collapsed to the sentinel string `"true_after_unknown"` by `_eval_after_unknown`, and **only** under env `EVAL_TF_PLAN_AFTER_UNKNOWN`. Checkov's real module/variable resolution is in its HCL graph builder, which the plan path runs with `render_variables=False` (`plan_runner.py`); the two are only merged in `deep_analysis_plan_graph_manager.py` when HCL *source* is also supplied |
| **infracost** v0.10.45 | Go, Apache-2.0, active (2026-09-09) | `providers/terraform/parser.go:465` `parseResourceData` recurses `child_modules`; **and the cleanest existing address→config join anywhere**: `ConfLoader.GetModuleConfJSON(names)` builds the gjson key `module_calls.<a>.module.module_calls.<b>` and `GetResourceConfJSON(addr)` looks up `resources.#(address=…)` after `removeAddressArrayPart` | `parseConfReferences` links across boundaries for the cost graph, not general rewriting | yes, and the most robust address parsing surveyed: `getModuleNames`, `addressCountIndex`, `addressKey`, a quote-aware `splitAddress` | not modelled |
| **trivy** v0.74.0 (tfsec folded into it, last push 2026-03) | Go, Apache-2.0, active | `pkg/iac/scanners/terraformplan/tfjson/`: `PlanFile.ToFS()` calls `buildPlanBlocks(PlannedValues.RootModule, ResourceChanges, Configuration.RootModule)` and **re-emits a synthetic `main.tf`** for the normal HCL scanner. Models `Module.ChildModules` + `ConfigurationModule.ModuleCalls`, so it recurses. (Its separate `snapshot/` scanner reads the binary `.tfplan` and recovers the original HCL — a different mechanism entirely) | inherited from the HCL evaluator, not from the JSON | child-module name comes from a plain `strings.Split(address, ".")` with no bracket stripping, so `module.foo["k"]` misses `ModuleCalls["foo"]`; no `for_each` fixture in `testdata/` | **impossible**: its `Change` struct is literally `{After map[string]any}` — `after_unknown` is never deserialised |
| **tf-summarize** | Go, MIT, active | `terraformstate/terraform_state.go` `GetAllResourceChanges` — `plan.ResourceChanges` only; zero hits for `child_modules` | n/a | n/a | n/a |
| **tfparse** 0.6.21 | Py-over-Go, Apache-2.0 | parses **HCL**, not plan JSON; its Go side imports trivy's HCL parser, so its module resolution is trivy's | n/a | n/a | n/a |
| **terrasafe** / **python-terraform** / **terraform-plan-parser** | Py GPLv3 (stale 2021) / Py MIT (CLI wrapper, 2019) / npm TS | `resource_changes` only, needing no recursion / no plan parsing at all / regex over `plan` *text* | no | — | no |

**Band 3 — the one Python project that resolves across boundaries.**
`terraform-compliance` 1.15.1 (MIT, active 2026-09-07,
`terraform_compliance/extensions/terraform.py`). Its value hoist is exactly the
union recommended below: `_parse_resources()` unions `prior_state` data sources +
`values.root_module`/`child_modules` (through a generic recursive
`seek_key_in_dict`) + the flat `resource_changes` (`values = change.after`), keyed
by `address`; `strip_iterations()` (`common/helper.py:626`) strips **any**
bracketed segment, so `[0]` and `["k"]` both normalise. And
`_find_resource_from_name`/`_mount_references` really do resolve `module.X.out`:
they walk the `module_calls` chain (splitting `module_address` pairwise,
`split('[')[0]`-ing each segment to reach nested calls), read
`module_calls.<X>.module.outputs.<out>.expression.references`, **re-qualify those
module-local refs against the module's full, iteration-suffixed address**, and
dedupe the `aws_x.y.arn`/`aws_x.y` pair. Three limits:
`_fetch_resource_by_a_variable` resolves `var.x` only against
`root_module.module_calls[…]`, so multi-level `var` chains are not followed; the
resolved refs get mounted into the resources' `values` dicts (Regula's shape
mistake again); and `remember_after_unknown()` aggregates unknowns per resource
**type**, not per attribute.

**Band 4 — Rego idioms.** The OPA Terraform tutorial
(`openpolicyagent.org/docs/terraform`, `terraform_module.rego`) is the canonical
recursion: `walk(input.planned_values, [path, value])` then match
`path[count(path)-1] == "resources"` with `path[count(path)-3] == "child_modules"`.
Styra's plan-policy docs use the same idiom. `conftest` ships no
Terraform-specific helper. None of these touch `configuration`.

## 3. Regula, the fullest implementation

`fugue/regula`, Apache-2.0, **archived** (last commit `259c10a` 2024-09-03 "Add
archival note"; last release v3.2.1, 2023-02-16). The flattening is in Rego, not
Go: `rego/lib/fugue/resource_view/terraform.rego`, 338 lines. Its algorithm is
the right one:

* `planned_values_module_resources` — the values hoist (a comment records that
  they replaced a naive whole-tree `walk()` for speed).
* `configuration_modules` — `walk(input.configuration)` matching the
  `[…, "module_calls", NAME, "module"]` path shape (`count(path) % 3 == 0`),
  returning per-module `vars` (input name → the caller's single reference).
* `module_qualify(module_path, x)` → `module.<a>.module.<b>.<x>`;
  `configuration_module_outputs` + a `data.util.resolve` fixpoint for transitive
  output chains; `configuration_resolve_ref(outputs, module_path, vars, ref)` with
  four cases (`var.x` that hits an output, `var.x` that does not, a qualified
  output ref, a module-local resource ref).
* `filter_refs` — the non-obvious nugget: it collapses Terraform's parent/child
  duplication, keeping `module.a.out` (dropping bare `module.a`) but keeping
  `aws_s3_bucket.b` (dropping `aws_s3_bucket.b.arn`). Its comment cites "plan
  format 0.2" as where the duplication began.
* `resource_changes_unknowns(address, prefix)` — walks `after_unknown` for `true`
  leaves, used as the join key.

Three reasons **not to vendor it as-is**: (1) `resource_view_patches`
`json.patch`-es the resolved *reference strings* into the value slots
`after_unknown` marked unknown, deliberately destroying the
missing/unknown/known distinction; (2) it is silently wrong on indexed modules —
`planned_values_resources` keys by `resource.address`
(`module.many[0].terraform_data.inner`) while `configuration_references` keys by
`module_qualify(path, address)` (`module.many.terraform_data.inner`), so every
`count`/`for_each` module misses the join with no diagnostic; (3) `count(refs) ==
1` guards mean a conditional, a `merge()`, or an unpassed variable simply
vanishes, where `oracles/rego/lib/hcl_traversal.rego` exists precisely to refuse
those loudly (`unresolvable`/`ambiguous`).

## 4. Feasibility: the prototype already works

`scratchpad/norm/proto.py`, ~70 lines, no dependencies, hoists both sides and
rewrites references over both fixtures:

| root-frame rewrite | raw `references` | resolved |
|---|---|---|
| `terraform_data.sink.input` | `module.outer.mid_out`, `module.outer` | `module.outer.module.inner.terraform_data.deepest{,.output}` |
| `module.outer.module.inner…deepest.input` | `var.deep` | `terraform_data.seed{,.output}` (two hops: `var.deep`→`var.mid`→root) |
| `module.fe.module.inner…deepest.input` | `var.deep` | unresolved (`each.value`) |
| `terraform_data.consumer2.input` | `module.many[0].out_func` | unresolved (indexed call) |
| `terraform_data.root_res.input` | `local.computed` | unresolved → `hcl_traversal` |

One design lesson: resolve **after** `filter_refs`, or the bare `module.a` half
of every pair marks the slot unresolvable even when the real reference resolved.

## 5. Recommendation

**(a) Is `resource_changes[]` a sufficient value-side hoist?** For values and for
three-valued grading, yes, and it is strictly *better* than `planned_values`:
`after_unknown` is the only place unknown-vs-absent survives, `change.after` is
byte-identical to `values`, no-ops are included, and it needs zero recursion. It
is not a complete *replacement* — it lacks plan-time-read data sources (in
`prior_state` only; a gap that already exists today and is not a module problem),
`schema_version`, `provider_name`, `sensitive_values`, and represents deletes as
`after: null`. Since the values recursion is ten lines, do both: hoist
`planned_values` by recursion (keeping existing asserts' shape and the extra
fields) and carry `x_after_unknown`/`x_actions` onto each hoisted resource from
`resource_changes`, joined on `(address, deposed)`. That also lets the verifier
finally distinguish missing from unknown on the *existing* arms, which
`planned_values` alone never could.

**(b) What to vendor for the reference rewriting?** Nothing wholesale — no
library exposes it as a callable (§2). Port three pieces by hand, all credited:
Regula's resolution algorithm per §3 (`module_qualify`,
`configuration_resolve_ref`, `filter_refs`, ~150 lines of Python, its three bugs
fixed, Apache-2.0); terraform-compliance's output-chain walk and its
re-qualification of module-local refs against the iteration-suffixed module
address, plus `strip_iterations` (MIT — the only Python prior art, and the only
one that gets `["k"]` right); and infracost's address→config-node join
(`GetModuleConfJSON`/`GetResourceConfJSON`, ~20 lines, Apache-2.0), the cleanest
answer to "given `module.many[0].aws_x.y`, find its config node" — the step
Regula gets wrong and checkov and trivy get wrong for `for_each`.

**(c) Minimal normaliser shape.** A pure `normalize_plan(plan: dict) -> dict` in
`oracles/lib/` beside `structural.py` (the tier-0 evaluator), called once before
jq runs and handing the *same* document to `opa`:

* `planned_values.root_module.resources` ← every resource at every depth,
  each gaining `x_module_path` (list of call segments *with* instance keys,
  e.g. `["fe[\"a\"]", "inner"]`), `x_module_address`, `x_after_unknown`,
  `x_actions`. `child_modules` is left in place (additive, not destructive).
* `configuration.root_module.resources` ← every config resource at every depth:
  `address` requalified to `module.<call>.…` (call names, **no** instance keys —
  the config side has none), `x_module_path`, per-slot
  `expressions.<attr>.references` rewritten to root-frame addresses,
  `x_references_raw` preserving the original list verbatim, and
  `x_unresolved: [<reason>, …]` when any component could not be rewritten.
  `module_calls` is left in place.
* Each hoisted config resource also gets `x_module_instances` — the instance
  addresses seen on the values side for its module path — so a rule can see that
  one config node governs two planned resources instead of guessing.
* **No `x_` key is added to a root-module resource**, so a module-free plan
  normalises to itself byte-for-byte and the zero-drift parity gate over every
  existing `hcl_raw`/`terraconstructs` fixture is a plain equality assert.

**Cases that must stay unresolvable, never guessed:** `count`/`for_each` on a
module call (one config node, N value instances, and refs through
`count.index`/`each.key`/`each.value` name an instance the config cannot select);
an indexed module output read in the caller (`module.many[0].out`); `for_each =
toset(...)` on a module call, where Terraform emits no `for_each_expression` at
all; `dynamic` blocks, absent from the configuration representation entirely;
module outputs with `constant_value` and no references, or with several
(conditional, `merge`, `coalesce`) — mark ambiguous, as `hcl_traversal` already
does; an input the caller never passes, so the child falls back to
`variables.<x>.default`, which is the arm doc's "module hides the trapped
attribute behind a default" case and must change the catch's tier rather than be
papered over; `local.*` (hand to `hcl_traversal`, which owns it); `path.module` /
`terraform.workspace` / `self`; `depends_on` and provider passing, which are
edges the normaliser does not model; and `deposed` objects, which need the
`(address, deposed)` key or they collide.

**Effort.** Normaliser plus unit tests over hand-built module fixtures: ~1.5
days. Parity gate over every existing Terraform fixture (byte-for-byte
identity) plus wiring into the tier-0 driver and the `opa` input: ~0.5 day.
Teaching `hcl_traversal.rego` to consume `x_references_raw` /
`x_unresolved` instead of refusing `module.*` and `var.*` by name: ~1 day, and
it is the risky half, since its refusal messages are part of the graded
contract. Total **~3 days**, and it is a prerequisite for the modules arm, not
part of it. The `terraform graph -type=plan` closure is a separate, optional
~0.5-day cross-check oracle and should not be on this path.
