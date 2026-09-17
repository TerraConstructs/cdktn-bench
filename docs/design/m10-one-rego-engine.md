# M10 — one Rego engine for every tier

Design memo for ROADMAP M10. Two decisions, taken in the order that makes the
second one cheaper: an engine evaluation first, the tier-0 translation second.
Nothing here changes a graded row; every step below is gated on parity
fixtures before any current path is removed.

## 1. What runs today

| tier | source | executable | engine in the verifier image |
|---|---|---|---|
| 0 | `oracle.structural_asserts` (JSONPath subset + op + expected) | `generator/jsonpath_jq.py` compiles each path to a jq filter; `tests/_assert_lib.sh::assert_check` applies the op | `jq` (67 KB) |
| 1 | `oracles/rego/<id>/policy.rego`, `oracles/rego-cfn/<id>/policy.rego`, `oracles/cfn-guard/<id>/policy.guard` | `opa eval -f raw -I -d policy.rego data.cdktn_bench.<pkg>.deny`; `cfn-guard validate` on awscdk unless `awscdk_tier1_engine: rego` | `opa` 1.19.0 (57 MB static), `cfn-guard` 3.2.0 on awscdk only |

Corpus at 20 specs: 117 tier-0 asserts over nine ops (`eq` 43, `exists` 31,
`contains` 17, `set_eq` 8, `regex` 6, `not_exists` 4, `absent_or_eq` 3, `in` 3,
`not_regex` 2), 48 tier-1 asserts, 29 Rego policies, all `import rego.v1`.
Builtins the policies use: `object.get`, `count`, `sprintf`, `sort`,
`startswith`/`endswith`, `walk`, `regex.match`, `regex.find_n`,
`regex.find_all_string_submatch_n`, `concat`, `split`, `json.unmarshal`,
`json.marshal`, `contains`, `object.union`, `object.keys`, `lower`,
`trim_prefix`/`trim_suffix`, `sum`. No `net.*`, `io.jwt.*`, `crypto.*`,
`time.*`, `http.*`, `glob.*`.

The tier-0 verdict is three-valued and that is the property M10 must not
lose: `assert_check` returns 0 (resolved, held), 1 (resolved, contradicted) or
2 (unresolvable: jq error, unknown op). jq `null` results are dropped before
the op runs, so an absent key and an explicit `null` both resolve to "no
node"; `eq` demands exactly one node; `set_eq` flattens one level, dedupes and
compares as a set; `in` flattens one level; `absent_or_eq` accepts zero or one
node; `not_regex` passes vacuously on zero nodes; `contains` is a substring on
strings and membership on lists. `oracles/tests/test_op_parity.py` already
pins the bash implementation against the Python reference
`oracles/lib/structural.py` per op, which is the harness the translation
extends.

## 2. Decision B first: evaluate `microsoft/regorus`

Facts (verified 2026-09-10 against the repository, crates.io, PyPI, npm):

* Rust crate `regorus` 0.12.0 (released 2026-09-01, cadence 4–8 weeks, active,
  Microsoft-owned, used by Azure Policy preview and ACI confidential
  computing). Rego v1 default, v0 behind a flag. Claims OPA v1.2.0 conformance
  on every non-builtin suite; the failing suites are `net.*`, `io.jwt.*`,
  `graphql`, `providers.aws`, `rego.metadata`, template rendering. None of
  those builtins appear in this repo's policies.
* Output of `regorus eval` matches `opa eval --format json`'s
  `{"result":[{"expressions":[...]}]}` shape per the project's own diff
  example. `--coverage` produces a line-coverage report (which policy lines
  ran), something OPA's CLI does not give the verifier today.
* Project numbers, not ours: ~10× faster than `opa eval` on their ACI policy
  (4.6 ms vs 45 ms), 6.3 MB binary (1.9 MB without default features) against
  our 57 MB OPA.
* **No release binaries, no PyPI wheel, no npm package.** The CLI is a cargo
  *example* (`cargo install --example regorus --git … --tag regorus-v0.12.0`),
  so the verifier image needs a Rust build stage pinned by tag and commit, and
  the CLI's flag and exit-code stability is that of an example, not a
  supported binary. Exit codes for undefined results are undocumented.
* Composite licence (MIT AND Apache-2.0 AND BSD-3-Clause via vendored code).

**The spike.** One multi-stage Dockerfile builds the pinned CLI and copies the
stripped binary into a bookworm-slim stage; on the host the same binary is
built once under the session scratch directory. Then, for every scenario with
a Rego policy, the existing falsifiability runs are replayed under both
engines: the reference and every broken fixture's artifact (`plan.json` or
the CFN template) is evaluated against its policy with `opa eval` and with
`regorus eval`, and the `deny` and `not_verifiable` sets are compared
byte-for-byte after sorting. Exit codes, stderr on undefined results, and
`--coverage` output are recorded for one scenario each of the three policy
families (`rego`, `rego-cfn`, `hcl_traversal`).

**Decision rule.** Zero divergences across all 29 policies and their fixtures,
documented exit-code semantics, and a build that pins tag + commit with the
binary's sha256 recorded, is the condition for a DRAFT amendment that swaps
the verifier image's engine. Any divergence is a finding written up in
`docs/`, and the verifier stays on OPA 1.19.0. The `hcl2json` + locals
aggregation shell (`build_hcl_merge_block`) is out of scope for the spike: a
stateful Rust extension would need a fork or a crate of our own, which is a
maintenance cost the bench should not take on for one scenario.

Estimated effort: one day, offline, no harness change.

## 3. Decision A: tier 0 compiled to Rego from the same YAML

Goal: one assert source (the spec YAML), one language for both static tiers,
no bash between the spec and the verdict, and the three-valued outcome
preserved exactly.

**Shape.** The generator emits `tests/tier0.rego` per arm alongside
`policy.rego`, package `cdktn_bench.<pkg>.tier0`, with one rule set per
verdict class keyed by assert name:

```
held contains name if { … }
contradicted contains name if { … }
unresolvable contains name if { … }
```

`static_tiers.sh` queries the three sets once and derives `tier0_pass`
exactly as today (`held` complete and `contradicted`/`unresolvable` empty),
printing the same per-assert lines and the same `== summary:` line so
`observed_tier()`, `grading_proof` and the result schema do not move.

**Path compiler.** `jsonpath_jq.py` gains a sibling `jsonpath_rego.py` (or a
second backend in the same module) over the identical grammar:

| JSONPath fragment | Rego |
|---|---|
| `$` | `input` |
| `.Field` | `x.Field` (undefined when absent; explicit `null` filtered by `v != null` to match jq's null-drop) |
| `[*]` | `x[_]` |
| `..Field` | `walk(x, [p, v]); p[count(p)-1] == "Field"` |
| `[?(@.F=='V')]`, nested `@.F.G`, `\|\|` | comprehension with the conditions OR'd as separate rule bodies |
| `[?(@=='V')]` | `x[_] == "V"` |
| `\|fromjson` | `json.unmarshal(v)` when `is_string(v)`; otherwise the assert is **unresolvable** |

Node collection is a comprehension `vals := [v | …]` per assert; the op rules
reproduce `assert_check` clause for clause (multiplicity for `eq`, one-level
flatten for `in`/`set_eq`, set comparison after dedupe, substring vs
membership for `contains`, vacuous `not_regex`). The unresolvable class is the
hard part, because Rego turns most errors into undefined silently: a
`fromjson` on a non-string, a filter applied to a non-object, and an unknown
op are the three cases jq reports as errors today, and each gets an explicit
rule rather than falling through to "no node".

**Parity gate before anything is removed.**

1. `oracles/tests/test_op_parity.py` grows a third implementation column and a
   matrix per op covering: zero nodes, one node, many nodes, explicit null,
   absent key, nested arrays, non-string under `fromjson`, invalid JSON under
   `fromjson`, unknown op. All three (bash/jq, Python reference, Rego) must
   agree on the three-valued outcome for every cell.
2. Every existing falsifiability artifact (reference and broken fixtures of
   all 20 specs) is graded by both compilers; per-assert outcomes and
   `tier0_pass` must be identical. This is a `make` target, run in `make ci`.
3. A spec-level switch `oracle.tier0_engine: jq | rego` (default `jq`) lets
   the translation land dark; flipping the default and deleting the jq
   backend are separate amendments, the second only after a live battery has
   graded under Rego.

Engine for tier 0 is whichever tier 1 uses after Decision B, so the order
matters: if regorus wins the spike, the tier-0 rules are written and tested
under it from the start.

Estimated effort: compiler and rules two to three days; parity fixtures one
day; the live battery reuses an existing read-only scenario.

## 4. What this does not change

* Prompts, catches, `predicted_tier_caught`, the live and teardown tiers.
* cfn-guard on awscdk where `awscdk_tier1_engine` is `cfn_guard`; a later
  amendment may retire it once every awscdk policy has a Rego twin, which is
  a separate decision with its own strictness-parity proof.
* The result schema and every published row.
