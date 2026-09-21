# How Terraform static analysers grade a resource inside a called module

Research memo, 2026-09-21. Input to `docs/design/tf-modules-arm.md` §1 (the plan
normaliser) and ROADMAP §7 open decision 4. Proposes no code change.

The question: an agent writes `module "alb" { source =
"terraform-aws-modules/alb/aws" ... }` and the trapped attribute (`ssl_policy`,
`server_side_encryption_configuration`) is set by a module input, a module
default, or a module-internal local — nothing about it is visible in the
caller's HCL. How does each tool reach it, and where does it say the violation
is?

Versions read: checkov 3.3.19 (`92ca010`, 2026-09-17); trivy `b830ddf`
(2026-09-18, checks from the `trivy-checks` v1.12.2 OCI bundle); tflint master
`d5d0da2` + `tflint-ruleset-aws` `5fbc911` + `tflint-plugin-sdk` `9dad97c`
(2026-09-19/20); terrascan v1.19.9; kics v2.2.0. Paths below are in-repo paths
of those trees, cloned to scratch.

## 1. Two families, and one hybrid

* **HCL evaluators** — Checkov, Trivy, TFLint, Terrascan, Regula: they locate or
  fetch the module's `.tf` source, bind the caller's arguments to the module's
  `variable` blocks and evaluate the body. They see module-internal defaults and
  locals, *but only if the module bytes are present*.
* **Plan-JSON readers** — Sentinel `tfplan/v2`, OPA/conftest, KICS plan mode,
  Regula `-t tf-plan`, Checkov `--framework terraform_plan`, Trivy `tfjson`:
  Terraform has already evaluated, so modules arrive flattened with final values
  and no source lines at all.
* **The hybrid**: Trivy's *plan snapshot* scanner reads the binary
  `terraform plan -out=tfplan`, which embeds the full `.tf` source of the root
  config **and every module** plus the module manifest; it reconstructs a
  virtual filesystem (`pkg/iac/scanners/terraformplan/snapshot/snapshot.go`,
  `writeManifest`) and runs the ordinary evaluator over it with
  `OptionWithDownloads(false)` — module-resolved HCL evaluation, zero network.
  The only tool-shipped mechanism that gets both halves offline.

## 2. Checkov

**Download.** `--download-external-modules` / `DOWNLOAD_EXTERNAL_MODULES`, into
`--external-modules-download-path` (default `.external_modules`,
`common/util/consts.py:3`). `ModuleLoaderRegistry.load()`
(`terraform/module_loading/registry.py:35-134`) skips every loader with
`is_external=True` when the flag is off (86-88); only `LocalPathLoader` is
non-external. `RegistryLoader` lists registry versions and picks by constraint
(`versions_parser.py`: `=,!=,>,>=,<,<=,~>`); git/github/bitbucket loaders take
tokens from env. `CHECKOV_EXPERIMENTAL_TERRAFORM_MANAGED_MODULES=True` reuses an
existing `.terraform/modules` instead (root folder only). **Without the flag, or
on any download failure, the module is silently dropped**: `TFParser._load_modules`
(`tf_parser.py:205-311`) gets `content_path=None` and `continue`s (259-260), so
the module's resources never become vertices and the policy cannot fire —
indistinguishable from compliant.

**Graph.** `TerraformLocalGraph._build_edges_for_vertex`
(`graph_builder/local_graph.py:368-381`) creates, per `module` vertex, an edge
*from* each of the module's own `variable` vertices *to* the module call,
labelled `"default"`. `TerraformVariableRenderer.evaluate_vertex_attribute_
from_edge` (`variable_rendering/renderer.py:108-118`) then overwrites that
variable's `default` with `destination_vertex.attributes[<var name>]`, the
caller's argument; no argument → no edge → the module's own default stands.
Outputs are wired back by `_connect_module` (506-539), and
`_get_dest_module_path` (541-557) returns `""` for an undownloaded external
module.

**Attribution.** `Record` carries two locations (`common/output/record.py:44-108`):
`file_path`/`file_line_range` point into `.external_modules/.../main.tf` at the
offending block, while `caller_file_path`/`caller_file_line_range` point at the
`module "alb" {}` block in the user's file (`terraform/runner.py:354-377`).

**Plan mode.** `parse_tf_plan()` (`plan_parser.py:507-551`) with
`_find_child_modules()` (325-377) recurses `child_modules` to unbounded depth and
flattens every resource into one list; the only trace of nesting is
`resource["address"]` stored as `TF_PLAN_RESOURCE_ADDRESS`.
`plan_utils.create_definitions()` (16-58) files the whole flattened dict under
**one key, the plan file's own path**, so every finding's `file_path` is
`tfplan.json` with JSON line numbers. No module loader runs (checkov#2682:
`--download-external-modules` is inert under `--framework terraform_plan`) and
graph edges present in HCL mode are missing (#1469). `--deep-analysis` with
`--repo-root-for-plan-enrichment` builds a second, real HCL graph and merges it
by resource address (`deep_analysis_plan_graph_manager.py:53-76`) — the only
route to module-source resolution in plan mode. `(known after apply)` is dropped
unless `EVAL_TF_PLAN_AFTER_UNKNOWN` is set (`_eval_after_unknown`, 228-243).
There is no `--max-module-depth`, and `for_each` on modules runs through
`foreach/module_handler.py` inside a `try/except … continue`. Docs:
<https://www.checkov.io/7.Scan%20Examples/Terraform.html>,
<https://www.checkov.io/7.Scan%20Examples/Terraform%20Plan%20Scanning.html>.

## 3. Trivy (tfsec/defsec lineage)

**Download — no `terraform init` required.** `loadModule()`
(`pkg/iac/scanners/terraform/parser/load_module.go`) first tries
`loadModuleFromTerraformCache()`, reading `.terraform/modules/modules.json` if
present and matching on `Block.ModuleKey()`; otherwise it runs its own resolver
chain `Local → Cache → Remote → Registry` (`parser/resolvers/*.go`): registry
sources hit `registry.terraform.io`, resolve the constraint, then fetch with
`hashicorp/go-getter` into `$TMPDIR/.aqua/cache` keyed by md5(`source:version`).
`AllowDownloads` defaults **true** and `--offline-scan` is not wired into it.
`--tf-exclude-downloaded-modules` does **not** stop the download or the
evaluation — it registers a results filter marking a finding `StatusIgnored`
when its range has a non-local source prefix
(`scanners/terraform/options.go:45`). An unfetchable module is logged ("Maybe
try 'terraform init'?") and skipped: again a silent false negative.

**Evaluation.** `parser/evaluator.go` is a real evaluator with a fixed point:
`EvaluateAll()` (127) expands `count`/`for_each`/`dynamic`, then
`evaluateSubmodules()` re-runs children up to `maxContextIterations = 32` (25,
174) until inputs stop changing. `ModuleDefinition.inputVars()`
(`load_module.go:27`) evaluates the caller's `module` block attributes into
`map[string]cty.Value` and `evaluateVariable()` (475) prefers
`e.inputVars[label]` over the module's own `default`; outputs are exported back
as `module.alb.*` (110, 260-261). Unknowns are handled by `IsKnown()` checks —
a `for_each` over an unknown local defers expansion
(`shouldDeferForEachExpansion`, 653-707); unresolvable values become `cty.NilVal`
and the block is skipped.

**Attribution.** `NewBlock()` (`pkg/iac/terraform/block.go:81-90`) sets
`metadata.WithParent(moduleBlock.GetMetadata())`, so every block parsed inside a
submodule carries a parent chain terminating at the caller's `module "alb"`
block, serialised for Rego by `Metadata.ToRego()`
(`pkg/iac/types/metadata.go:79-93`). The primary filename still sits inside the
module dir (`Range.GetFilename()` joins the source prefix). Checks are
module-blind: `executor.Execute()` adapts root plus all submodules together and
`Modules.GetResourcesByType` (`pkg/iac/terraform/modules.go:35-42`) concatenates
across modules.

**Plan JSON.** `terraformplan/tfjson/parser.go:buildPlanBlocks()` walks
`module.ChildModules` (79) and takes values from `resourceChanges[].After`
(`getValues`, 247) — no re-evaluation — flattening into one synthetic `main.tf`
and disambiguating same-named resources with an md5 of the module address
(`moduleResourceName`, 225-234); module structure is otherwise lost. Snapshot
mode is the richer path (§1). Docs:
<https://trivy.dev/docs/latest/guide/coverage/iac/terraform/>; trivy#4618,
#5416, PR #11200.

## 4. TFLint

**Read-only about modules.** `--call-module-type=all|local|none` (config
`call_module_type`, default `local`) replaces the old `--module`/`--no-module`.
`terraform/module_mgr.go` reads `.terraform/modules/modules.json` with the
comment "Unlike Terraform, it does not install from the registry and is
read-only"; `terraform/loader.go:moduleWalkerFunc` errors `"%s" module is not
found. Did you run "terraform init"?` for a remote source absent from the
manifest. So **TFLint cannot inspect a remote module whose source is not
downloaded** — stated in
<https://github.com/terraform-linters/tflint/blob/master/docs/user-guide/calling-modules.md>.
`--recursive` is unrelated: it re-runs TFLint per subdirectory as independent
roots.

**Evaluation.** `terraform/config.go:buildChildCtx` (mirrored in
`tflint/runner.go:NewModuleRunners`) evaluates each `module` block attribute in
the caller's context to build the child's `VariableValues`;
`evaluationData.GetInputVariable` falls back to the module's own `Default`.
`terraform/lang/data.go` has no `GetResource`: every reference to a resource,
data source or module output evaluates to `cty.UnknownVal(cty.DynamicPseudoType)`
(`lang/eval.go:161-217`), surfaced to rules as `tflint.ErrUnknownValue` /
`ErrNullValue` / `ErrSensitive` and checked with `errors.Is`.

**Plugin API.** Rulesets are separate binaries over gRPC
(`hashicorp/go-plugin` v1.8.0). Rules call
`runner.GetResourceContent(type, schema, opt)` — sugar over `GetModuleContent` —
with `ModuleCtx` `SelfModuleCtxType` (default) or `RootModuleCtxType`, plus
`ExpandMode` for `count`/`for_each` (`tflint-plugin-sdk/tflint/option.go`). The
host decides what "self" is: `BuildRunners` creates one `Runner` per module-call
instance and `cmd/inspect.go` calls `ruleset.Check(...)` once per runner, always
passing the root runner too. So a plain `Self` call, while the host iterates the
ALB module's runner, returns resources **declared inside the registry module**
with `var.*` already bound; `RootModuleCtxType` is for root-level lookups like
`provider "aws"`.

**Attribution — and a hard failure mode.** `Runner.EmitIssue`
(`tflint/runner.go:226-252`): for a non-root module it calls
`listModuleVars(r.currentExpr)`, finds `var.*` references *in the source text at
the flagged range*, and re-roots the issue to that input's declaration in the
caller with a `Callers:` chain. If the flagged expression holds no direct `var.`
reference — a hard-coded module default, or `local.x` even when that local
derives from a variable — **the issue is discarded and nothing is reported**.
The doc says so: "If an issue within a child module is detected in an expression
that does not reference a variable (var), it will be discarded." Deep checking
left core in v0.23.0 (`cmd/cli.go:136`) for `plugin "aws" { deep_check = true }`
(live read-only AWS calls). There is no plan-JSON mode at all.

## 5. Others, briefly

* **Terrascan** v1.19.9, **archived 2025-11-20**. HCL mode uses Terraform's own
  `configs` parser (`pkg/iac-providers/terraform/commons/load-dir.go`) plus its
  own `go-getter` downloader, so `init` is optional (`--use-terraform-cache`
  prefers `.terraform/modules`). Violations attribute to the module's own file —
  the downloaded URL lands in the `file` field (PR #867). Its regex-based
  `RefResolver` bails on non-literal defaults, `count`/`for_each` and data
  sources; the plan-JSON provider hard-codes `source: ""`.
* **KICS** v2.2.0 parses each `.tf` independently; a `module` block is an opaque
  blob and remote modules are never downloaded. Instead ~20 official registry
  modules are hardcoded in `assets/libraries/common.json` and mapped
  input→resource-attribute by `get_module_equivalent_key()` (`common.rego:318`),
  `terraform-aws-modules/alb/aws` among the keys ("does not support unofficial
  or custom modules", docs.kics.io). Plan mode (`pkg/parser/json/tfplan.go`)
  walks `ChildModules` into the HCL parser's shape, so queries run unchanged and
  findings point at the plan file.
* **Snyk IaC** docs state verbatim that for HCL scanning "external modules are
  not supported"; the recommended escape is scanning `terraform show -json`
  (`--scan=planned-values` for full resolved state). Open component:
  `github.com/snyk/policy-engine`.
* **Regula**, **archived 2024-09-03**, superseded by `snyk/policy-engine`: its
  HCL loader forks Terraform's `configload` with registry discovery disabled, so
  docs require `terraform init` first; `-t tf-plan` recurses `planned_values`
  and `child_modules[].resources` into one flat object keyed by
  `resource.address` (`lib/fugue_resource_view.rego`), reported as
  `module.alb.aws_lb.this[0]`.
* **OPA/conftest over plan JSON** has no module machinery; the policy author
  walks. Canonical pattern from <https://www.openpolicyagent.org/docs/terraform>
  ("Working with Modules"): `walk(input.planned_values, [path, value])` matching
  `reverse_index(path, 1) == "resources"` with `root_module` at index 2 or
  `child_modules` at index 3. `resource_changes[]` needs no walk.
* **Sentinel `tfplan/v2`**: `resource_changes` is a flat map keyed by full
  address with `module_address`, `change.after`, `change.after_unknown` — a
  module resource differs from a root one only by that field. `tfconfig/v2` adds
  `module_calls` (source, version constraint, argument expressions) and
  per-module `variables` keyed `module_address:name` **including the module's own
  `default`**. Offline runs need mocks exported from a TFC/TFE run.

## 6. What the plan JSON itself gives, and loses

Per <https://developer.hashicorp.com/terraform/internals/json-format>:
`planned_values.root_module` nests `child_modules[]` recursively with addresses
like `module.child.aws_instance.foo[0]`; `resource_changes` is flat and each
entry carries `module_address` ("omitted if the instance is in the root
module"); `configuration.root_module.module_calls.<name>` carries
`resolved_source`, `expressions` (the caller's arguments, with `references`) and
a recursive `module` object that "represents the configuration of the child
module itself, using the same structure as the root_module object" — i.e. the
module's own `resources`, `variables` (with `default`) and `outputs`. Unknown
leaves appear as `after_unknown: true`, sensitive ones as `after_sensitive`.

So the plan holds both halves the question asks about: final values (flat, with
`module_address`) and the symbolic chain `module-internal resource expression →
var.X → module_calls.<call>.expressions.X → caller's expression`. What it does
not hold is any source range — no file, no line, anywhere. Attribution to the
caller's line belongs to the HCL evaluators alone, and each spells it
differently: Checkov a second `caller_file_path`, Trivy a metadata parent chain,
TFLint a re-rooting that silently drops the no-`var.` case.

## 7. Synthesis for this benchmark

1. **The families split exactly along the offline requirement.** Every HCL
   evaluator needs the module bytes at analysis time, and Checkov, Trivy and
   TFLint all respond to a missing (or unresolvable) module by *silently
   producing no finding*. For a grader whose contract is three-valued that is
   the worst available failure: an unresolvable input reported as "held". None
   of them exposes a distinguishable "could not resolve" verdict at rule
   granularity, so adopting one as the grading engine would mean proving module
   presence for every trial as a precondition.
2. **Plan-JSON normalisation remains the right pattern**, as
   `tf-modules-arm.md` §1 proposes, and this survey strengthens the case: it is
   what Sentinel, OPA/conftest, KICS-plan and Regula all do; it is
   byte-deterministic; module source is needed at *plan* time (inside the trial,
   which has network) and never at grading time; and a module-free plan
   normalises to itself, which is a checkable parity gate. `resource_changes` is
   already flat with `module_address`, so the normaliser's real work is
   `planned_values.child_modules` hoisting plus configuration-side reference
   rewriting.
3. **The three-valued mapping falls out of the plan format.** `after_unknown`
   leaf `true` → **unresolvable**, not contradicted; a key absent from `after`
   with no unknown marker → resolved "no node"; `after_sensitive` →
   unresolvable. This has to be explicit, because the current tier-0 contract
   drops `null` before the op runs and would read an unknown as absent. A module
   instantiated twice yields two `child_modules` entries and therefore two
   nodes, which `eq` contradicts by design — the `hcl_modules_override` column
   and per-catch `applies_to` in `tf-modules-arm.md` §1 are the answer there,
   not a normaliser change.
4. **Caller attribution should come from the configuration section, not from a
   tool.** Pairing `module_calls.<call>.expressions.<input>.references` with the
   module-internal `expressions.<attr>.references = ["var.<input>"]` is enough
   to say "this value came from the input you wrote", which is all a catch
   message needs; the plan has no lines to point at, and the existing `_hcl`
   merge (hcl2json, `conftest-hcl-traversal-spike.md`) already supplies
   caller-side source text. Note the trap TFLint fell into: when the module
   hard-codes the trapped value or routes it through an internal local there
   *is* no caller reference, and the honest verdict is that the catch does not
   apply on this arm — not that it held.
5. **No tool ships a reusable "plan with modules flattened" or "module-resolved
   HCL graph" as a supported library.** Checkov's
   `TerraformGraphManager.build_graph_from_source_directory` is importable but
   undocumented, in no `__all__`, and has changed shape across majors. Trivy's
   `parser.New(fs, src, …).ParseFS/EvaluateAll() → terraform.Modules` is
   genuinely exported and is the closest thing to a module-resolved-HCL library,
   but it sits in the single `trivy` go.mod with no API guarantee and has
   already moved once from `defsec`. TFLint's `terraform` package is a de facto
   internal MPL fork of Terraform core, with plugin authors sent to the gRPC SDK
   instead; Sentinel's imports are runtime-bound; third-party flatteners
   (`schubergphilis/flatplan`) are CLI tools without parity guarantees.
   **So the normaliser is ours to write and ours to pin — there is
   nothing to vendor**, which also keeps the one-engine decision intact: no
   second engine and no Go dependency in the verifier image.
6. **One mechanism worth stealing.** Trivy's snapshot scanner shows that
   `terraform plan -out=tfplan` embeds every module's `.tf` source plus the
   module manifest, and that an evaluator can be aimed at that with downloads
   disabled. If a future catch needs module-internal *source* rather than values
   at grading time, the binary plan file kept as a trial artefact is the offline
   carrier, and grading needs no module mirror at all (the mirror in
   `tf-modules-arm.md` §2 is still needed for authoring).
