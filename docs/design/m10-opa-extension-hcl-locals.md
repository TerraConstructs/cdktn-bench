# Can the `hcl2json` + locals-aggregation shell step go away?

Question from the owner (2026-09-11): drop the shell step that resolves
Terraform `locals` indirections for the tier-1 Rego oracle, and — since the
regorus route is closed (`docs/design/m10-regorus-spike-results.md`: stay on
OPA 1.19.0) — does OPA offer a Go extension point that would leave the static
oracle as Python + Rego + Go with no bash.

**Short answer.** Three separate things are tangled in that one question and
they have three different answers.

1. **The HCL parse cannot go.** No Terraform-native path exposes `locals`, and
   the values this oracle needs are plan-time-unknown anyway (§2).
2. **Evaluating locals is the wrong tool for this job** — the resolver wants
   the unevaluated reference, not a value (§3).
3. **The shell around the parse can go today, cheaply, with no new binary and
   no custom OPA** (§5, design A). OPA *does* support Go builtins in a custom
   binary and the API is real (§4), but spending that on this step buys one
   binary and costs a repo-wide toolchain fork.

## 1. What runs today

`oracle.hcl_traversal: true` (`specs/SCHEMA.md:1630`) is set by exactly one
spec, `specs/s3-notification-authoritative-singleton.yaml:3686`. It makes the
generator emit an extra step into the `hcl_raw` arm's
`tests/static_tiers.sh` — `generator/gen.py:2213` `build_hcl_merge_block()`,
rendered at `tasks/anchor/s3-notification-authoritative-singleton-hcl-raw/tests/static_tiers.sh:61-234`:

* ~25 lines of bash: `command -v hcl2json`, a library-present check, a
  `python3 - "$ARTIFACT" "$HCL_MERGED" <<'HEREDOC'`, the `ARTIFACT` swap, and
  the `TOOL_MISSING` / `LIB_MISSING` / `PARSE_FAILED` status;
* ~140 lines of **Python** inside that heredoc: glob `*.tf` and run the pinned
  `hcl2json` 0.6.9 per file, load `*.tf.json` raw, re-parse every
  `jsonencode(...)` body through the same parser under a reserved
  `#jsonencode` key, merge it all into the plan document under `_hcl`.

The generator's own comment says why that body is Python rather than a jq/shell
loop, and warns that the emitted program must stay escape-free because it
crosses two levels of quoting (`generator/gen.py:2199-2212`) — that hazard
alone argues for getting it out of a heredoc. Parser skew (`hcl2json` rejects
a `.tf` terraform accepted) is `ENGINE_ERROR`, "the oracle did not run", never
a score (`specs/SCHEMA.md:1774`).

The consumer is `oracles/rego/lib/hcl_traversal.rego` (952 lines): it reads
`input._hcl` as `{filename: document}` (`:159`), normalises `hcl2json`'s
list-of-blocks `locals` and terraform JSON syntax's object spelling (`:217`),
flattens every node to `[path, value]` pairs (`:246`), tokenizes the
`"${...}"` source strings `hcl2json` returns for any expression it cannot
reduce (`:461`), follows `local.*` hops to a terminal (`:606`, `:661`), and
classifies every symbol resolved / ambiguous / unresolvable (`:686`, `:833`).

**Why the plan JSON alone was insufficient.** `terraform show -json` emits no
`locals`, so `.configuration.root_module.resources[].expressions.<attr>.references`
records only that the argument was *set to* `local.x` and nothing about what
`local.x` holds (`specs/SCHEMA.md:1634`). Two executed defects came out of
that: a false PASS (an ARN of the wrong resource laundered through a local)
and a false FAIL (a DRY hoist the oracle could not follow).

**Asymmetry between arms.** terraconstructs synthesizes `cdk.tf.json` (JSON
already, no `locals` block at all) so it loads the library but parses nothing
(`generator/gen.py:2415`); awscdk grades a CloudFormation template. Only
`hcl_raw` has HCL source, so this touches one arm and, today, one spec.

## 2. Terraform-native alternatives: none of them work

* `terraform show -json` **has no `locals` key**, confirmed against the JSON
  Output Format doc (developer.hashicorp.com/terraform/internals/json-format);
  `configuration.root_module` carries `outputs`, `resources`, `module_calls`,
  `variables`, `provider_config` only. The gap is a known, still-open
  Terraform issue (hashicorp/terraform#24059, with #35674 closed onto it —
  filed by someone trying to validate `local.role_arn` with OPA).
  An expression object carries `constant_value` **or** `references`, never
  both, and `references` is a flat union with multi-step traversals unwrapped
  — the same flatness that made the `jsonencode(...)` launder possible.
* `planned_values` *does* carry the resolved value when a local reduces to a
  constant — but "any unknown values are omitted or set to null,
  indistinguishable from absent" (same doc), and this scenario's referents are
  exactly the plan-time-unknown ARNs (`specs/SCHEMA.md:1323`, "Plan-time-unknown
  attributes"). So `planned_values` answers a question this
  oracle is not asking.
* `terraform console` evaluates for real, but needs an initialised module,
  prints HCL-ish text rather than JSON, and would need one invocation per
  symbol — and it would again return "(known after apply)" for the ARNs.
* `terraform-config-inspect`'s `tfconfig.Module` has `Variables`, `Outputs`,
  `ManagedResources`, `DataResources`, `ModuleCalls`, `ProviderConfigs` — and
  **no `Locals` field**. Dead end.
* `terraform providers schema -json` is provider schemas only; `terraform-json`
  (tfjson) is typed structs over the same plan format and inherits the gap.

## 3. `hcl.eval_locals(dir)` would be the wrong builtin

The obvious Go builtin — parse `*.tf` with `hclparse`, evaluate the `locals`
blocks against an `hcl.EvalContext` seeded with variable defaults, return JSON —
is buildable (`hclparse.NewParser().ParseHCLFile`, `body.PartialContent` with a
`locals` block header, `block.Body.JustAttributes()`, `attr.Expr.Value(ctx)`,
`ctyjson.SimpleJSONValue`), with the usual caveats: ordering between locals,
cycle detection, and Terraform's own function set living in `internal/` and so
not importable (only `go-cty/cty/function/stdlib` and
`hashicorp/go-cty-funcs` approximations).

It is the wrong tool here. **Every value this resolver cares about is a
reference to a resource attribute that does not exist until apply.** Evaluated,
`local.arns.media_bucket` is unknown; unevaluated, it is
`"${aws_s3_bucket.media.arn}"`, which is precisely what
`hcl_traversal.rego:461` tokenizes and what makes the three-valued verdict
possible. Source-preserving parsing is the requirement; evaluation would
throw away the answer. Note this is also why `hcl2json`'s `-simplify` flag
must stay off — the pinned CLI defaults it to `false`
(tmccombs/hcl2json v0.6.9 `main.go`).

## 4. OPA extension points, verified against v1.19.0

Read from the tagged source, not from memory:

* **Go builtins, global.** `rego.RegisterBuiltin1..4` / `RegisterBuiltinDyn`
  (`v1/rego/rego.go:747-816` at tag v1.19.0) take a `*rego.Function`
  (`Name`, `Description`, `Decl *types.Function`, `Memoize`,
  `Nondeterministic`) and call `ast.RegisterBuiltin` + `topdown.RegisterBuiltinFunc`
  (`v1/ast/builtins.go:22`, `v1/topdown/builtins.go:91`). Names may contain
  `.`, so `hcl.parse_dir` is a legal name. `rego.Function1..4`
  (`v1/rego/rego.go:817+`) are the per-`rego.New` variants and do **not**
  affect the CLI.
* **`opa eval` sees them.** `cmd/eval.go` evaluates through
  `github.com/open-policy-agent/opa/v1/rego` and, absent `--capabilities`,
  type-checks against `ast.CapabilitiesForThisVersion()` (`cmd/eval.go:874-880`),
  which copies the global `ast.Builtins` slice (`v1/ast/capabilities.go:156`).
  A globally registered builtin is therefore visible to `eval`, `check`,
  `test` and `build` of that binary with no capabilities file, and
  `opa capabilities --current` on it emits a JSON that includes the builtin —
  which is what a stock `opa` or an editor would need via `--capabilities`,
  since an unknown function is a hard `rego_type_error` at compile time
  whether or not `--strict` is on (`--strict` only adds unused-local and
  unused-import checks).
* **The custom binary is the documented pattern.** OPA's own `main.go` is 20
  lines importing `github.com/open-policy-agent/opa/cmd` and calling
  `cmd.RootCommand.Execute()`; the "Extending OPA" docs page's section
  "Adding Built-in Functions to the OPA Runtime" shows exactly that `main`
  with a `rego.RegisterBuiltin2` call before it, built with `go build`.
* **Plugins do not apply.** `plugins.Manager.Register` /
  `runtime.RegisterPlugin` are manager-scoped and config-driven (decision
  logs, discovery, bundles); `cmd/eval.go` never constructs a plugin manager.
  Plugins are an `opa run` / server-mode mechanism.
* **WASM is not a route.** A compiled wasm policy exports a `builtins()` table
  the *host* must implement, so the builtin would be re-implemented in the
  embedding SDK. We do not use the wasm target.
* **Import paths.** The canonical packages are `github.com/open-policy-agent/opa/v1/{rego,ast,types}`;
  the unversioned `opa/{rego,ast,types,cmd}` paths still exist at 1.19.0 as
  type-alias shims, which is what the docs example and the sketch below use.
* **Binary and build.** Stock `opa_linux_arm64_static` 1.19.0 is 56 969 368
  bytes (`docs/design/m10-regorus-spike-results.md` §1); a custom build is the
  same order — `CGO_ENABLED=0 go build -trimpath -tags=opa_wasm` in a pinned
  `golang:` stage matching upstream's own `.go-version` (1.26.5 at this tag)
  with committed `go.mod`/`go.sum`, sha256 recorded. But that is *our* sha, not
  one cross-checkable against an upstream `checksums.txt` — the property the
  Dockerfile comment credits `hcl2json` with having and `opa` with lacking
  (`arms/hcl-raw/environment/Dockerfile:115-121`).

Sketch, registration and parse in one:

```go
func main() {
	rego.RegisterBuiltin1(
		&rego.Function{
			Name:             "hcl.parse_dir",
			Decl:             types.NewFunction(types.Args(types.S), types.A),
			Nondeterministic: true, // reads the filesystem
		},
		func(bctx rego.BuiltinContext, arg *ast.Term) (*ast.Term, error) {
			var dir string
			if err := ast.As(arg.Value, &dir); err != nil {
				return nil, err
			}
			out := map[string]any{}
			paths, _ := filepath.Glob(filepath.Join(dir, "*.tf"))
			for _, p := range paths {
				src, err := os.ReadFile(p)
				if err != nil {
					return nil, err
				}
				// Same parser and same shape as the pinned CLI -- Simplify stays
				// false. Returning an error ABORTS eval (the ENGINE_ERROR path);
				// a builtin that went undefined instead would fail OPEN.
				js, err := convert.Bytes(src, p, convert.Options{})
				if err != nil {
					return nil, err
				}
				var doc any
				_ = json.Unmarshal(js, &doc)
				out[filepath.Base(p)] = doc
			}
			v, err := ast.InterfaceToValue(out)
			return ast.NewTerm(v), err
		},
	)
	if err := cmd.RootCommand.Execute(); err != nil { // OPA's own main.go, verbatim
		os.Exit(1)
	}
}
```

`github.com/tmccombs/hcl2json/convert` is a real exported package
(`convert.Bytes`, `convert.File`, `convert.ConvertFile`, `convert.Options{Simplify}`),
Apache-2.0 — so any Go route reuses the *identical* parser and
`hcl_traversal.rego` needs no change at all. That is true for design B and
design C equally.

## 5. Three designs

| | A — merge in a real Python file | B — custom `opa` with `hcl.parse_dir` | C — one small Go tool of ours |
|---|---|---|---|
| bash removed | the heredoc and its escaping hazard; ~25 lines of status shell stay | the whole merge block (the policy calls the builtin) | the heredoc **and** the glob/subprocess loop; ~6 lines of status shell stay |
| binaries in the `hcl_raw` image | terraform, opa, hcl2json, jq, python3 (unchanged) | terraform, **custom** opa, jq, python3 | terraform, opa, **ours**, jq, python3 |
| pinning | unchanged: upstream binary + published `checksums.txt` | our build, our sha, no upstream cross-check | our build, our sha, no upstream cross-check |
| blast radius | one spec's tier-1 step | **every scenario on every arm** runs the forked engine | one spec's tier-1 step |
| maintenance | none | track OPA releases; rebuild + re-verify on each bump | track hcl2json / hcl v2; rebuild on each bump |
| host/CI | unchanged (`ci/run-ci.sh:16`, `oracles/tests/test_hcl_traversal.py:78-82` find tools on PATH) | dev machines and CI must stop using brew/stock `opa` | dev machines and CI need one more tool, skippable like today |
| Rego changes | none | none (same parser, same shape) — but the glob moves into the policy, inverting `specs/SCHEMA.md:1743` "the glob is in the shell, never in the policy" | none |
| effort | ~0.5 day | 3–4 days + a per-release treadmill | 1.5–2 days |

Two things worth stating plainly. First, **the current toolchain is already
Python + Rego + Go**: `hcl2json` is a Go binary, `opa` is a Go binary, and the
merge logic is already Python. The only non-conforming element is the shell
*wrapper*, and it is ~25 lines. Second, design B's apparent elegance — the
policy calls `hcl.parse_dir(".")`, `input` stays plan JSON, no merged document,
no `oracle-input.json` — costs the property the merge design was built around:
a Rego builtin that cannot find a file is undefined rather than an error, which
fails **open**. A custom builtin can be made to error instead, but the
fail-closed reasoning then lives in Go we maintain rather than in a shell
`if` anyone can read, and it is exercised only by the one spec that opts in.

## 6. Recommendation

**Take A now. Do not build a custom OPA binary for this.**

Move the embedded program to a generated `tests/hcl_merge.py`, written by the
same generator branch that writes `hcl_traversal.rego` into `tests/`, invoked
as `python3 "$DIR/hcl_merge.py" "$ARTIFACT" "$HCL_MERGED"`. That deletes the
heredoc (and the documented two-level-quoting escape hazard), makes the merge
step readable, lintable and unit-testable from `oracles/tests/`, and changes
no binary, no pin, no Rego and no reward contract. The residual shell is the
`command -v` / status ladder, which goes away with the generated-bash rewrite,
not with this change.

Keep C on the shelf: the right shape *if* the `hcl2json` binary or the
`#jsonencode` subprocess fan-out ever needs to go, since it reuses
`tmccombs/hcl2json/convert` and leaves `hcl_traversal.rego` untouched — but it
swaps a 4.1 MB upstream binary with published checksums for a ~6 MB one of ours
without them, so it needs a second reason before it is worth doing.

Reject B. A forked `opa` sits on the critical path of **every** graded scenario
on every arm to serve **one** opt-in step on one arm; it replaces an upstream
release with a binary we build, adds an OPA-release treadmill to a pin the repo
deliberately froze at 1.19.0, makes every developer machine and `ci/run-ci.sh`
stop using stock `opa`, and buys nothing C does not buy at a third of the cost.

**Effort: A ≈ 0.5 day** — generator change, `make gen-all`, a falsifiability
replay of the one spec's reference plus its six broken fixtures, and a
byte-for-byte diff of the produced `/logs/verifier/oracle-input.json` against
today's (the parity gate: same merged document, or it does not land).

## 7. The bash that remains, and whether it can go

Removing this heredoc barely dents the shell surface: each task ships a
generated `tests/static_tiers.sh` (332 lines here) and `tests/test.sh` (192),
plus `tests/_assert_lib.sh` (178), and 20 specs × 3 arms carry copies. That is
the real target, and it is feasible: the harness contract is only "`tests/test.sh`
exists and `/logs/verifier/reward.txt` is written", so `test.sh` can shrink to
an `exec python3 "$DIR/verify.py"` and everything above it — the toolchain
ladder, the three-valued assert loop, the tier-1 gate — becomes a generated
Python module. The three-valued operator semantics already have a Python
reference (`oracles/lib/structural.py`, pinned against the bash by
`oracles/tests/test_op_parity.py`), and the M10 plan to compile tier 0 to Rego
(`docs/design/m10-one-rego-engine.md` §3) overlaps with it, so the two should
be sequenced together rather than done twice. `docs/design/shell-inventory.md`
already classifies what would move. Not designed here.
