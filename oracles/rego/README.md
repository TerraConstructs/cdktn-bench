# oracles/rego

Rego/OPA policies graded against `terraform show -json` plan output, for the
`hcl-raw` and `terraconstructs` arms (both synthesize to Terraform).

One `.rego` bundle per scenario catch (see `docs/iac-abstraction-aws-bench-plan.md`
Phase 1 seed-scenario table for the planted catches these need to assert on).
Populated in Slice D, validated by the oracle-equivalence CI in Slice E.

## `lib/` — shared policy libraries (added 2026-08-23)

`oracles/rego/lib/*.rego` holds Rego a scenario policy may **import** rather
than copy. Before this directory existed there was no mechanism at all: one
self-contained `policy.rego` per scenario, and the only way to reuse anything
was to paste it.

How it reaches a running trial:

1. `generator/gen.py::write_tests_dir` **copies** the library file into the
   task's own `tests/` beside `policy.rego`, for the arm/spec combination
   whose generated script actually loads it. A task directory stays
   self-contained — registry-style dataset consumption fetches only that
   task's path, never sibling `oracles/**`.
2. The generated `tests/static_tiers.sh` loads it with a second `-d`:
   `opa eval -d "$POLICY" -d "$HCL_LIB" 'data.cdktn_bench.<pkg>.deny' …`
3. The copy is listed in `_GENERATED_TESTS_FILES`, so turning the opt-in back
   off removes the stale copy rather than leaving a task claiming a grader its
   script no longer loads.

| file | package | who loads it |
|---|---|---|
| `hcl_traversal.rego` | `cdktn_bench.hcl` | any spec with `oracle.hcl_traversal: true` (`specs/SCHEMA.md` §4.6) — on **both** TF-shaped arms (`hcl_raw` and `terraconstructs`), because one `policy.rego` grades both and the moment it says `import data.cdktn_bench.hcl` every arm loading it needs the file. The **`_hcl` merge** that feeds it is `hcl_raw`-only; conflating the two scopes is an executed false FAIL in either direction (SCHEMA.md §4.6, "TWO SCOPES"). |

**Read a library's own header before writing a rule against it.**
`hcl_traversal.rego`'s header carries a three-valued contract that is binding
on every caller (`resolved` / `ambiguous` / `unresolvable`; the last two both
DENY), the arity gate that must not be re-implemented at the call site, and
the three executed defects — two silent PASSes and one silent FAIL — that
dictate its shape.

Its regression suite is `oracles/tests/test_hcl_traversal.py`, which runs
**one OPA process per shape and checks the exit code**. That is not a style
choice: a totality assertion that evaluates every shape inside one query
cannot see a runtime error, because the error aborts the assertion itself. A
suite written the other way missed the same defect twice.

**Round 14 (2026-08-24) added two lessons to that header, both from executed
defects, and both about places totality does NOT automatically extend to:**

* **A `deny` rule’s MESSAGE must be total too.** A `msg` expression that goes
  undefined does not deny — the rule silently does not fire. Two helpers in a
  first draft (`hcl.slot(…).reason`, absent on a `resolved` verdict; a
  `count()` over an undefined set) each did exactly that.
* **`locals` has two on-disk spellings.** `hcl2json` emits a list of blocks;
  terraform’s own JSON syntax (`main.tf.json`, loaded raw by the harness)
  emits an object. Reading only the list spelling silently dropped every local
  in a `.tf.json` and scored a correct solution 0.0 with a deny message the
  artifact contradicted. `locals_blocks` now reads both.

**Round 17 (2026-08-24) added two more, both from executed defects, and both
about the same failure: a guard that reads like a check and is not one.**

* **`hcl.resource_jsonencode` can hand you a NON-OBJECT, and this library's
  own header used to say otherwise.** `policy = jsonencode(local.doc)`
  re-parses *fine* — `locals { v = local.doc }` is valid HCL — and the
  recovered body is the **string** `"${local.doc}"`. A caller that took the
  entry raw found a "document", never reached its unreadable branch, and
  graded an ordinary DRY hoist as a document with zero statements: **REWARD
  0.0 on a fully correct solution**, with a deny message the artifact
  refutes. **Guard `is_object(...)` on the recovered body**, then use
  `hcl.deref_local` (added the same round) to read what a lone `local.`
  symbol actually holds. `deref_local` is UNDEFINED for an ambiguous, cyclic
  or non-`local.` expression, so the fail-closed branch stays reachable.
* **`some` and `every` are not interchangeable when the data models two
  different logical connectives.** An IAM condition position OR-s its
  values and AND-s across positions. A rule that used `some` for both
  accepted `"aws:SourceArn": [<the wired bucket>, "arn:aws:s3:::*"]` as
  scoping, at **REWARD 1.0**, on all three document routes and on the CFN
  arm. Before writing a quantifier over a collection, say out loud what the
  collection MEANS.

**A residual to know about when you write the next `data`-block rule.**
`terraform show -json`'s `.configuration` reports a `condition`'s `values` as
`{"references": [...]}` with **every literal dropped**, so it cannot tell
`[x, "*"]` from `[x]`. The arity and the literals are in `.planned_values`
(one entry per value, `null` for an unknown), and
`s3-notification-authoritative-singleton`'s plan-path fallback reads both.
On an arm that supplies parsed source, read the source.

**Round 15 (2026-08-24) added a third, and it is the one to internalise:**

* **A PARSE THAT SUCCEEDS AND THEN THROWS INFORMATION AWAY IS THE SILENT
  SHAPE.** `instance_of` used to be `array.slice(segs, 0, 2)` — the first two
  segments of a referent path. The tokenizer parses `["key"]` deliberately, so
  `aws_s3_bucket.b["media"].arn` and `aws_s3_bucket.b["decoy"].arn` both
  resolved cleanly and then collapsed to the *same* instance: a Lambda
  permission scoped to the decoy `for_each` key scored **reward 1.0** on a
  broken artifact, and so did its correct twin. The numeric `[0]` spelling
  never parsed at all, which is why it was loud — and the library's own
  residual list generalised from the loud half and called the whole family
  refused. `instance_of` now takes the referent's **source string** (never the
  lossy segment array) and carries the key; verdicts expose `instance` and
  `attr_path` so callers never re-derive either. **Corollary for any new
  library helper: if a value is derived from a string, derive every field of
  it while the string is still in scope.**

**Round 16 (2026-08-24) added two more, and the first is the single easiest
way to write a dead safety guard in Rego:**

* **A COMPREHENSION OVER AN UNDEFINED BODY IS THE EMPTY COLLECTION, NOT
  UNDEFINED.** `parse_traversal(t) := [seg | some m in _parse_ms(t); seg :=
  _segment(m)]` looks like it goes undefined when `_parse_ms` does. It does
  not — it returns `[]`, which is *defined*. Every `not parse_traversal(x)`
  guard in the library was therefore **always false**, and the tokenizer's
  entire refusal path was dead code: untokenizable references were silently
  dropped from their slot instead of refusing it, and opaque expressions got
  a factually false reason. Write the comprehension as
  `f(t) := out if { xs := g(t); out := [ ... | some x in xs ] }` so the rule
  body has to succeed first. **And pin the guard on the SHIPPED entry point:**
  the old test called `hcl.resolve` on a bare symbol and never asserted the
  reason, so it passed for four rounds while the path it named was dead.
  Its sibling, found in the same round: **`not object.get(x, "k", null)` is
  ALWAYS FALSE.** `object.get` returns its default when the key is missing,
  and `null` is *truthy* in Rego — so an "if this key is absent" guard written
  that way never fires. Write `object.get(x, "k", null) == null`. The
  generalisation: **in Rego, a guard built out of a TOTAL builtin is a prime
  candidate for being always false, and neither of these is visible in
  review — only in execution.**
* **PROVENANCE IS NOT POSITION.** `s3-notification-authoritative-singleton`
  graded an IAM policy document by asking whether *some reference anywhere in
  it* resolved to the wired bucket. A bucket reference interpolated into a
  statement's `Sid` satisfied that, and **one cosmetic line took a checked-in
  0.0 fixture to reward 1.0**, on every arm at once. If the graded question is
  "is this grant conditioned on X", the rule has to read the CONDITION, not
  the document. Where the artifact hides the position inside an opaque
  expression (`policy = jsonencode({...})`), recover it — the harness re-parses
  that body with the same `hcl2json` and exposes it as
  `hcl.resource_jsonencode` — rather than settling for a test that cannot
  distinguish a `Sid` from a `Condition`.
