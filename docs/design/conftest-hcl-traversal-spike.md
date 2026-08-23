# Spike: can Conftest's HCL2 parser give a Rego policy the traversal
# information `terraform show -json` loses?

**Status:** timeboxed spike, complete; **three rounds of adversarial
verification, three executed defects in the prototype's own safety
contract** (§5.7, §5.8, §5.9 — the last one falsifies the totality claim
earlier revisions of this memo made, and is the single most important thing
in it). **Date:** 2026-08-23.
**Verdict: ADOPT NARROWLY — but adopt `hcl2json`, not `conftest`.**
The capability is real and it fixes both proven defects. Conftest is the
wrong packaging of it, and the parser gives *less* than the question
assumed: **no static traversal analysis at all, only re-lexable source
text**.

Everything below was executed. Prototype and scratch live in `/tmp/spike`
(deliberately outside the repo); nothing in `oracles/`, `specs/`, `tasks/`,
`arms/` or `generator/` was touched.

---

## 0. TL;DR

| question | answer |
|---|---|
| Does Conftest expose HCL **static traversal analysis** (`hcl.Expression.Variables()`)? | **No.** It returns the raw expression *source*, re-wrapped as `"${...}"`. A policy must re-lex it itself. |
| Can a Rego policy still resolve `local.arns.media_bucket` → `aws_s3_bucket.media.arn`? | **Yes**, by re-lexing, and reliably for the shapes that matter. |
| Does it fix defect (a), the false PASS? | **Yes** — executed: reward 1.0 → correct **0.0**, at any laundering depth (12-hop chain executed). The first two versions of this claim were true only up to 4 hops; see §5.8. |
| Does it fix defect (b), the false FAIL? | **Yes** — executed: reward 0.0 → correct **1.0**. |
| Do we need the conftest binary? | **No.** Conftest's HCL2 parser *is* `tmccombs/hcl2json`, whose standalone binary produces **byte-identical** output at **4.1 MB** vs conftest's **68 MB**. |
| Does the engine have to change? | **No.** `opa 1.19.0` stays; the harness pre-merges the parsed HCL into the existing `plan.json` input under one new key. |
| Benefit to `awscdk` / `terraconstructs`? | **None.** Confirmed by synthesis, both arms. |
| Did the prototype's own safety contract hold on first submission? | **No — and not on the second, or the third.** Three rounds of adversarial verification each found an executed defect: a missing arity gate (§5.7, silent PASS), a chain deeper than the 4-hop unrolling that made `verdict` UNDEFINED (§5.8, silent PASS), and a dot-joined `_leaf` key that raised an `eval_conflict_error` and **aborted the whole evaluation** (§5.9, silent FAIL on a *correct* solution). **Read §5.7, §5.8 and §5.9 before the recommendation.** |
| Is `verdict` "total by construction"? | **Only against UNDEFINEDNESS, and that is a narrower claim than this memo made for two revisions.** A Rego `default` guarantees a rule is *defined* for every argument. It guarantees nothing if a rule that `verdict` **depends on** raises a runtime error: evaluation aborts before any clause — `default` included — can apply, and the query emits nothing at all. §5.9 executed exactly that. The claim is retracted where it was unqualified and restated with its limit everywhere it appears. |

---

## 1. Both defects reproduced first

Method: the `_run_solve` sandbox pattern by hand — `environment/workspace/`
copied to `/tmp/spike/base`, `main.tf` written from the fixture, then
`terraform plan` → `terraform show -json` → the exact tier-1 command
`opa eval -f raw -I -d policy.rego 'data.cdktn_bench.s3_notification_authoritative_singleton.deny' < plan.json`.
Terraform 1.15.8, hashicorp/aws 6.58.0, opa 1.19.0 — the pinned versions.

**Control.** The checked-in reference solution → `deny == []` → reward 1.0. ✅

**(a) FALSE PASS — reproduced.** Reference solution, one token changed
(`media_bucket = aws_lambda_function.ingest.arn`), plus an ordinary,
*correct* IAM read grant on the real bucket:

```hcl
locals { arns = { media_bucket = aws_lambda_function.ingest.arn, audit_topic = aws_sns_topic.audit.arn } }
resource "aws_lambda_permission" "allow_s3_invoke" { source_arn = local.arns.media_bucket ... }
resource "aws_iam_role_policy" "ingest_read" {  # ordinary, correct, unrelated
  policy = jsonencode({ ... Resource = "${aws_s3_bucket.media.arn}/*" })
}
```

The S3 invoke permission is scoped to the **Lambda's own ARN**. Result:
`deny == []`, **reward 1.0**. The unrelated read grant is what does it: it
puts `aws_s3_bucket.media ["arn"]` into the plan's `relevant_attributes`,
which is the only positive evidence the round-12 policy has, and that
evidence is *configuration-wide*, not per-slot.

**(b) FALSE FAIL — reproduced.** Fully correct solution; the topic ARN is
hoisted into a local for the policy attachment and written directly in the
notification (both idiomatic, both correct):

```hcl
locals { audit_topic_arn = aws_sns_topic.audit.arn }
resource "aws_sns_topic_policy" "audit" { arn = local.audit_topic_arn ... }
resource "aws_s3_bucket_notification" "media" { topic { topic_arn = aws_sns_topic.audit.arn ... } }
```

Result: **reward 0.0**, with a message that is factually false about the
artifact:

> `aws_sns_topic_policy.audit: ... no slot that WIRES a topic in this
> configuration carries any of them ... nothing in this plan connects that
> symbol to an aws_sns_topic this configuration creates.`

The round-12 "corroboration" rule requires the *same symbol* to appear in a
topic-wiring slot. Spelling one slot directly defeats it. Both defects have
the same root cause: the oracle is reasoning about *symbols* because it
cannot reach *referents*.

---

## 2. THE HARD BOUNDARY — what the parser actually exposes

**This is the spike's central finding, and it refutes the hypothesis's
premise.** HCL's Go API *does* expose static traversal analysis
(`hcl.Expression.Variables()`), but **Conftest does not use it and does not
surface it**. `tmccombs/hcl2json` walks the body, and for any attribute it
cannot reduce to a literal it emits the **raw source range of the
expression**, re-wrapped in `${...}`. A Rego policy gets a *string*, not a
traversal list.

Verbatim `conftest parse` output for the seven required cases
(conftest 0.69.0; `hcl2json` 0.6.9 output is byte-identical):

```json
{
  "locals": [
    {
      "simple": "${aws_s3_bucket.media.arn}",
      "nested": { "media_bucket": "${aws_s3_bucket.media.arn}" },
      "cond":   "${var.condition ? aws_s3_bucket.a.arn : aws_s3_bucket.b.arn}",
      "fmt":    "${format(\"%s/*\", aws_s3_bucket.media.arn)}",
      "merged": "${merge(local.a, local.b)}",
      "compr":  "${{ for k, v in var.buckets : k => v.arn }}",
      "chain":  "${local.nested.media_bucket}"
    }
  ]
}
```

Per case — *"does the parsed representation give you the traversal(s)?"*:

| case | parsed as | traversals given | what a policy can honestly conclude |
|---|---|---|---|
| `simple` | `"${aws_s3_bucket.media.arn}"` | **one, but as text** | the whole string is exactly one `${traversal}` → **RESOLVED** to `aws_s3_bucket.media.arn` |
| `nested` | a real JSON **object** | structure preserved; each leaf is one `${traversal}` | `local.nested` itself → **UNRESOLVABLE** (a container, not a value); `local.nested.media_bucket` → **RESOLVED** |
| `chain` | `"${local.nested.media_bucket}"` | one, as text, pointing at another local | **RESOLVED** by walking the locals table (2 hops here) |
| `cond` | one string containing the whole conditional | **several**, only by re-lexing | **AMBIGUOUS** — 2 candidate referents (+ the predicate), nothing picks one |
| `fmt` | `"${format(...)}"` | one traversal appears, but it is **not the value** | **UNRESOLVABLE** — the value is `<arn>/*`, not the arn |
| `merged` | `"${merge(local.a, local.b)}"` | two, neither of which is the value | **UNRESOLVABLE** — opaque function |
| `compr` | `"${{ for k, v in ... }}"` | none usable | **UNRESOLVABLE** — comprehension |

**So: a raw string you have to re-parse yourself, in every case except
`nested`'s object structure.** The single genuinely favourable property is
that the wrapper is unambiguous — a literal `"$${x}"` stays escaped as
`"$${x}"` and `"${a}/*"` keeps its trailing text, so
*"the whole string is `${` + one traversal + `}`"* is a sound test for
"this attribute **is** that reference".

Two further shapes worth recording (also verbatim):

```json
"literal":     "arn:aws:s3:::someone-elses-bucket",          // literals survive unwrapped
"interp":      "${aws_s3_bucket.media.arn}/*",               // distinguishable from bare
"literal_dlr": "a literal $${not_an_expr} here",             // escape preserved
"splat":       "${aws_s3_bucket.media[*].arn}",
"idx":         "${aws_s3_bucket.media[0].arn}",
"jsonenc":     "${jsonencode({ Resource = aws_sns_topic.audit.arn })}"
```

**Consequence, stated plainly: adopting this means hand-writing an HCL
expression lexer in Rego regexes.** It is a small lexer for the shapes that
matter, and it is bounded because the *classifier* is conservative — anything
it does not recognise is UNRESOLVABLE and therefore DENIES — but every new
spelling an agent invents is a new patch. §5 measures that treadmill.

---

## 3. Deliverable 1 — the prototype, and the three-valued contract

`/tmp/spike/policy/traversal.rego` (library, package `cdktn_bench.hcl`) +
`/tmp/spike/policy/policy_v2.rego` (the two slots the defects live in).
~150 lines total. Every symbol lands in exactly one bucket:

```
resolved(sym)     -> exactly one canonical referent traversal
ambiguous(sym)    -> N>1 candidate traversals, none selected statically
unresolvable(sym) -> 0 traversals / opaque / literal / container / missing /
                     cyclic / chain that never reaches a concrete reference
```

**Ambiguous and unresolvable both DENY, naming the symbol and quoting the
expression.**

> **This claim was false twice, in the same way, and both times the failure
> was a silent PASS.** Adversarial verification found (1) a missing arity
> gate on rule 2, so a slot with 0 or N>1 references never reached the
> resolver; then (2) a chain deeper than the resolver's 4-hop unrolling,
> which made `verdict` itself UNDEFINED — the fourth bucket this section
> used to say did not exist. Both were reached by the *absence* of a
> matching rule, and in the output a missing verdict is indistinguishable
> from a pass. **§5.7 and §5.8 have the full record; do not read this
> section without them.**
>
> The enumeration approach is what kept failing, so it is no longer what
> holds the contract up. `verdict` carries a Rego `default` clause, so it is
> **total against undefinedness**: for every argument, *if evaluation
> completes*, `verdict` is defined, and an unenumerated shape lands in
> `unresolvable` and DENIES.
>
> **RETRACTION (round 13).** Two earlier revisions of this memo stated that
> flatly, as *"total by construction — the language guarantees it is defined
> for every possible argument"*. **That is false as written, and it is the
> claim the whole recommendation rests on.** `default` protects against a
> rule being *undefined*. It does not protect against a rule `verdict`
> depends on raising a **runtime error**. A verifier executed a three-line
> valid `locals` block that made `_leaf` raise `eval_conflict_error`;
> evaluation aborted, `opa eval` printed nothing to stdout and exited 2, and
> the harness scored a **fully correct** solution 0.0 with no deny message.
> `default` never ran, because nothing ran. **§5.9 has the full record and
> the structural fix; read it with §5.7 and §5.8.**
Executed classification of the seven cases (verbatim prototype output):

```
simple   raw="${aws_s3_bucket.media.arn}"                    -> {"kind":"resolved","referent":"aws_s3_bucket.media.arn"}
nested   raw={"media_bucket":"${aws_s3_bucket.media.arn}"}   -> {"kind":"unresolvable","reason":"symbol names a container, not a single value"}
nested.* raw="${aws_s3_bucket.media.arn}"                    -> {"kind":"resolved","referent":"aws_s3_bucket.media.arn"}
chain    raw="${local.nested.media_bucket}"                  -> {"kind":"resolved","referent":"aws_s3_bucket.media.arn"}
cond     raw="${var.condition ? ... : ...}"                  -> {"kind":"ambiguous","candidates":["aws_s3_bucket.a.arn","aws_s3_bucket.b.arn","var.condition"]}
fmt      raw="${format(\"%s/*\", aws_s3_bucket.media.arn)}"  -> {"kind":"unresolvable","reason":"opaque expression"}
merged   raw="${merge(local.a, local.b)}"                    -> {"kind":"unresolvable","reason":"opaque expression"}
compr    raw="${{ for k, v in var.buckets : k => v.arn }}"   -> {"kind":"unresolvable","reason":"opaque expression"}
```

**simple, nested and chain resolve; the other four are correctly refused.**
Re-executed unchanged after the §5.9 fix (`resolved` verdicts additionally
carry `referent_path`, the segment array, which is what the calling policy
now type-matches on instead of re-splitting the rendered string).
(Wart, recorded not hidden: `cond`'s candidate list includes the predicate
`var.condition`. The verdict is unaffected — it is AMBIGUOUS either way —
but the message over-reports.)

Design notes that matter:
* **Chain walking is unbounded and cycle-safe.** Rego forbids recursive
  rules, so the first prototype hand-unrolled 4 `local.` hops — and fell off
  that ceiling into UNDEFINED (silent pass), not into UNRESOLVABLE. It now
  builds the locals reference graph with `walk()` and takes the transitive
  closure with `graph.reachable`, which is non-recursive, has **no depth
  limit**, and terminates on cycles by construction. Executed: a 12-hop
  chain resolves; a 3-node cycle and a self-loop return UNRESOLVABLE without
  hanging (§5.8).
* **`var.*` is always UNRESOLVABLE.** A locals resolver has no business
  claiming to know a variable's value.
* **Fail-closed is explicit.** With no `.tf` supplied at all, every symbol
  falls to UNRESOLVABLE *and* a dedicated rule fires
  (`"no .tf source was supplied to the policy — symbol resolution is
  impossible, denying rather than guessing"`). Executed. This matters
  because **`parse_config_file` on a missing file is UNDEFINED, not an
  error** — a policy that merely calls it and moves on fails *open*.

---

## 4. Deliverable 2 — applied to the real defects

Executed, both routes (conftest-as-engine and opa+hcl2json), identical results:

| artifact | old oracle | prototype | correct? |
|---|---|---|---|
| reference solution (control) | 1.0 | **PASS** | ✅ |
| **(a)** wrong-type ARN behind a local + unrelated read grant | **1.0 (false pass)** | **DENY → 0.0** | ✅ **fixed** |
| **(b)** topic ARN hoisted for one slot, direct in another | **0.0 (false fail)** | **PASS → 1.0** | ✅ **fixed** |
| **(a) laundered through a 5-hop local chain** (verifier's evasion) | **1.0 (false pass)** | **DENY → 0.0** | ✅ **fixed in §5.8** |
| **(a) at 5 hops + a correct topic policy** (defeats round-12 entirely) | **1.0 (false pass)** | **DENY → 0.0** | ✅ **fixed in §5.8** |

The last two rows are the verifier's evasion artifacts. **Round-12 is silent
on both** — which is why the additive-merge argument in the recommendation
cannot lean on round-12 to catch what resolution misses; on this shape it
catches nothing. Depth is no longer what separates "fixed" from "not fixed":
executed at 1, 4, 5 and 12 hops, all DENY.

The deny message for (a) is now a true statement about the artifact:

> `aws_lambda_permission.allow_s3_invoke: source_arn is`
> `` `local.arns.media_bucket` ``, `which resolves to`
> `` `aws_lambda_function.ingest.arn` `` `-- not the .arn of an aws_s3_bucket`
> `this configuration creates`

**The round-12 "irreducible residual" is not residual any more.** The
`THREE USES` shape that policy.rego records as irreducible from the plan
alone (laundered symbol in both slots + one decoy use of the real bucket ARN
elsewhere) was rebuilt and executed: old oracle **1.0**, prototype **DENY**.
It is irreducible *from `plan.json`*; it is trivial once you can read
`main.tf`.

Further adversarial shapes, all executed:

| shape | old | prototype |
|---|---|---|
| laundered literal behind a local | DENY | DENY (`unresolvable: literal`) |
| conditional `cond ? bucket.arn : fn.arn` | **1.0 false pass** | DENY (`ambiguous`, 2 candidates) |
| `format("%s", bucket.arn)` | **1.0 false pass** | DENY (`unresolvable: opaque`) |
| `local.arns["media_bucket"]` bracket syntax (correct) | 1.0 | PASS *(after a normalization patch — see §5)* |
| locals split into a second, agent-created `locals.tf` (correct) | 1.0 | PASS |
| no locals at all, direct references (the terraconstructs shape) | 1.0 | PASS |
| 2-hop chain through a second locals block (correct) | 1.0 | PASS |

**No regression on the existing fixture set.** All 19 `solution/broken/*`
fixtures were extracted, planned, and run against the prototype. The
prototype is **silent on every fixture whose defect is outside its two
slots** (8 of 19) and denies exactly the ones inside them (11 of 19,
including all four `...-behind-a-local` fixtures). It introduced **zero**
new false denies *on this fixture set*.

> **Correction (round 13).** "Zero new false denies" was measured over
> fixtures, and the fixtures did not contain the shape that breaks it. On a
> `locals` map carrying a dotted key (`"media.bucket" = …`) alongside the
> equivalent nested path (`media = { bucket = … }`), the round-12 prototype
> did not deny — it **crashed**, and the harness's
> `opa eval … | jq -e 'length == 0'` turns a crash into `tier1_status=FAIL`.
> That is a **false fail on a correct solution, with no message at all** —
> strictly worse than a false deny, because nothing names what went wrong.
> The claim above therefore held only for artifacts on which the policy
> evaluated to completion. §5.9. Fixed; the corpus was re-swept and the
> **only** three fixtures whose behaviour changed are the three that used to
> crash.

> **Correction (post-verification).** This table originally read 9 silent /
> 10 deny. A verifier proved that one of those nine —
> `sns-topic-policy-attached-to-a-different-topic` — was **inside** slot 2,
> not outside it, and was passing *silently* because rule 2 was missing the
> arity gate rule 1 had. That is now fixed and re-swept; the counts above are
> the post-fix counts. See §5.7, which records the defect in full rather than
> retiring it quietly.

The 8 remaining silences were each re-audited attribute-by-attribute to
confirm the silence is genuine (both slots present, each resolving to exactly
one *correct* referent) and not another missing guard. Their defects live in
the policy **document** (4), the **event** wiring (2), the **absence** of a
resource (1), and resource **cardinality** (1) — all outside the two
attribute slots the prototype claims.

---

## 5. The honest failure modes that remain

These are measured, not estimated.

1. **The lexer treadmill is real, and it bites in the FALSE-FAIL
   direction.** Two spellings already needed patches during the spike:
   * `local.arns["media_bucket"]` — terraform emits
     `["local.arns", "local.arns[\"media_bucket\"]"]`, so the prefix-dedupe
     that fixes round-11 does not fire, and the symbol path lookup misses.
     Fixed by normalizing `["k"]` → `.k`.
   * `count`/index on the *referent*: `media_bucket = aws_s3_bucket.media[0].arn`
     is a **correct** solution and the prototype **DENIES** it
     (`unresolvable: opaque expression`) because `[0]` is outside the
     traversal regex. **Executed — this is a live false FAIL in the
     prototype as it stands.** Fixable, and for gaps *of this kind* — a spelling
     the resolver refuses — the fail-closed design makes each one a *false
     fail* (loud, caught by the falsifiability gate the moment a fixture
     uses it) rather than a *false pass*. But the gate only catches what a
     fixture exercises. **And this guarantee is narrower than it first
     reads:** it covers symbols the resolver is asked about, not slots that
     never reach it. A missing arity gate produces a silent *false pass* and
     the fail-closed resolver does nothing to prevent it — see §5.7, where
     exactly that happened, on a fixture already in the repo. **And a
     resolver that goes UNDEFINED rather than returning `unresolvable`
     breaks it a second way — see §5.8.** The "always a false fail, never
     a false pass" guarantee is a property of the resolver *being total*,
     which it was not; it is only true now because `verdict` carries a
     `default` clause.
2. **Modules.** A `module "x"` whose locals live under `./modules/x/` is
   outside the root `.tf` glob. `module.x.out` → UNRESOLVABLE → DENY on a
   correct solution. Would need the glob widened, and module input/output
   plumbing is a second resolver on top of this one. This is directly
   relevant to open decision #4 (`hcl-modules` as a fourth arm) — **that arm
   would need materially more than this prototype**.
3. **Same-type, wrong-instance is untouched.** Resolution answers *"what does
   this symbol point at"*, not *"is that the right one of two buckets"*. A
   topic-policy `arn` that resolves cleanly to `aws_sns_topic.decoy.arn`
   when the scenario wanted `aws_sns_topic.audit.arn` is *resolved*, and the
   prototype passes it; discriminating **which** topic stays the full
   policy's job.
   *(Correction: this item originally cited
   `sns-topic-policy-attached-to-a-different-topic` as its example. That
   citation was wrong and is withdrawn. Despite the fixture's name its `arn`
   is not a same-type reference at all — it is
   `{"constant_value":"arn:aws:sns:...:cdktn-bench-some-other-topic"}`, a
   laundered literal with **zero** references, sitting squarely inside the
   prototype's own slot 2. It was silent for the reason in §5.7, not for the
   reason claimed here. The failure mode described in this item is real; the
   evidence offered for it was not.)*
4. **Parser skew.** hcl2json 0.6.9 and terraform 1.15.8 embed *different
   builds* of `hashicorp/hcl/v2`. A file terraform accepts and hcl2json
   rejects yields no `.tf` doc → fail-closed DENY on a correct solution.
   Low probability, non-zero; mitigated by pinning both and by the
   fail-closed rule making it loud.
5. **`.tf.json`.** Terraform accepts `main.tf.json`; a `*.tf` glob misses it.
   Trivial to handle (it is already JSON) but must be handled deliberately.
6. **This does not generalize for free.** Every scenario adopting it inherits
   the lexer and its treadmill. That argues for **one shared library file**,
   which `oracles/rego/` currently has no mechanism for (confirmed: one
   self-contained `policy.rego` per scenario, no `common/`). Adopting this
   properly means creating that mechanism — a real, non-trivial harness
   change, and the largest hidden cost in this proposal.
7. **The arity guard is a per-slot obligation, and the prototype shipped one
   slot without it — an executed SILENT PASS, and a regression against
   round-12.** This is the most important entry in this list, because it is
   the failure class the whole design claims to have eliminated.

   The three-valued contract only holds if every slot **reaches**
   `slot_verdict` in the first place. Resolution is defined for *one*
   reference, so each rule must first assert `count(refs) == 1` and **deny on
   the else-branch**. Rule 1 (`aws_lambda_permission.source_arn`) did:
   `count(refs) != 1` → deny. Rule 2 (`aws_sns_topic_policy.arn`) did **not**
   — all four of its bodies were predicated on `count(refs) == 1`. An `arn`
   holding 0 or N>1 references therefore matched no body at all and emitted
   **no verdict of any kind**: not resolved, not ambiguous, not unresolvable.
   A silent pass, reward 1.0. That is precisely the "fourth bucket" §3 says
   does not exist, arrived at not by a rule that assumes it is fine but by
   the *absence* of any rule — which is indistinguishable in the output and
   worse in review, because nothing in the policy text says so.

   Two shapes were executed against it, both in slot 2:
   * **0 references** — a laundered literal ARN
     (`arn = "arn:aws:sns:...:some-other-topic"`, emitted as
     `constant_value`). This is the checked-in fixture
     `sns-topic-policy-attached-to-a-different-topic`. **Round-12 denies it**
     (`"its `arn` argument carries no resource reference at all"`); the
     prototype was **silent**. A straight regression against shipped
     behaviour, on a fixture already in the repo.
   * **N>1 references** — a conditional written *directly* in the slot,
     `arn = var.flip ? aws_sns_topic.audit.arn : aws_sns_topic.decoy.arn`.
     **Neither round-12 nor the prototype caught this**: a genuine ambiguity
     silently accepted by both. Note the asymmetry this exposes — the
     prototype only ever refused ambiguity *behind a local*; ambiguity
     written in the open went straight through slot 2.

   The mechanism was isolated by the mirror case: the identical conditional
   in **slot 1** hits rule 1's gate and denies loudly. Only slot 2 lacked it.

   **Fixed and re-proved by execution.** The twin `count(refs) != 1` deny was
   added to the `topic_policies` rule set. All four cases now deny:

   ```
   sns-topic-policy-attached-to-a-different-topic (0 refs, checked-in fixture)
     before: []   after: ["aws_sns_topic_policy.audit: arn does not hold exactly
              one reference (found set()) -- cannot decide which topic this
              policy attaches to"]
   0-ref literal rebuilt from the reference solution   before: []  after: DENY
   N>1 direct conditional in slot 2                    before: []  after: DENY
              (found {aws_sns_topic.audit.arn, aws_sns_topic.decoy.arn, var.flip})
   N>1 direct conditional in slot 1 (control)          before: DENY after: DENY
   ```

   The 19-fixture sweep was re-run: that fixture moves SILENT → DENY, nothing
   else changes, and the reference solution still passes. On the N>1-written-
   directly-in-slot shape the fixed prototype is now **strictly better than
   round-12**, which still accepts it.

   **The generalizable lesson, which outlives this prototype:** a resolver
   whose contract is *"three-valued, never a guess"* is only as good as its
   *entry* condition. Every slot needs its arity gate, and *"no rule matched"*
   must never be a reachable outcome. The two gates here are twins written
   twenty lines apart and one was still missed — so this cannot be left to
   review. If this is adopted, the arity gate belongs **inside the shared
   library** (a `slot_refs(resource, attr)` helper that is *total* — returning
   an explicit `{"kind":"ambiguous"|"unresolvable"}` for the 0 and N>1 cases
   rather than going undefined), so a call site physically cannot omit it.
   The prototype's fix is the correct *behaviour* but the wrong *structure*:
   it re-fixes the hole per rule instead of making it unreachable.

   **Contract statements this falsified, now true again but only by patch:**
   §3's "no fourth bucket / ambiguous and unresolvable both DENY", §5.1's
   "the fail-closed design means each such gap is a *false fail*, never a
   *false pass*", and recommendation point 5's "fail closed, explicitly and
   loudly". All three were false for slot 2 as originally written. §5.1's
   claim in particular should be read narrowly: it is true of the *resolver*
   (a symbol it cannot resolve is refused), and it was false of the *policy*
   (a slot that never reached the resolver was waved through). The resolver
   being fail-closed does not make the policy fail-closed.

8. **`verdict` itself was not total, and a chain deeper than 4 hops was a
   SILENT PASS. This is §5.7's failure class, a second time, in the same
   file — and the §5.7 fix did not cover it.** Read this next to §5.7: the
   pair is the real finding of this spike.

   The §5.7 fix repaired the *entry* condition (arity). It left the *verdict*
   condition — totality — broken. The resolver walked `local.` chains by
   hand-unrolling four hops (`_h1`.._h4`), because Rego forbids recursive
   rules. At 5 hops every `referent` clause failed, and then **every
   `verdict` clause failed too**, so `verdict` was UNDEFINED — the fourth
   bucket §3 claimed did not exist. `slot_verdict` was undefined, both rule
   bodies failed, and no deny was emitted.

   The clause that was *supposed* to cover this had a comment saying it
   covered "a chain that never terminates in 4 hops", but its body was
   `raw_value(s) == null` — which only covers the *undefined-symbol*
   disjunct. **The code did not do what its own comment claimed**, and the
   comment is why it survived review.

   Executed, on a 5-hop laundering chain built from the checked-in reference
   solution (`local.a→b→c→d→e = aws_lambda_function.ingest.arn`,
   `source_arn = local.a`; terraform 1.15.8 plans it; the slot's reference
   list is exactly `["local.a"]`, so the new arity gate does **not** fire):

   ```
   raw_value("local.a") -> "${local.b}"    (a non-null STRING)
   referent("local.a")  -> UNDEFINED
   verdict("local.a")   -> UNDEFINED       <-- the fourth bucket
   slot_verdict("local.a") -> UNDEFINED
   deny -> []                              <-- SILENT PASS, reward 1.0
   ```

   The boundary was exact: the identical artifact at **4** hops denies
   correctly; at **5** it is silent.

   **Worse, it defeats the additive-merge argument** (recommendation point
   6). The verifier built defect (a) laundered through a 5-hop chain *and*
   left the topic policy fully correct, so round-12's cross-referencing
   topic-policy rule is satisfied. **Round-12 was silent AND the prototype
   was silent** — reward 1.0 on an artifact whose S3 invoke permission is
   scoped to the Lambda's own ARN. Point 6 argues round-12's rules catch what
   resolution cannot; on this shape round-12 catches nothing. A reward-hackable
   false pass in a benchmark oracle, and depth was the only thing separating
   "fixed" from "not fixed".

   **Fixed at the class level, not at the boundary.** Raising the unroll to
   8 hops would only move the cliff. Two structural changes:

   * **Unbounded, cycle-safe chain walking.** `walk()` flattens every
     `locals` block to its leaves at any nesting depth; `graph.reachable`
     takes the transitive closure of the resulting reference graph. Both are
     non-recursive builtins, so Rego's no-recursion rule is satisfied without
     a depth ceiling. A cycle simply yields no non-`local.` terminal.
   * **`verdict` carries a Rego `default` clause,** so a shape nobody
     enumerated lands in `unresolvable` and DENIES instead of going
     undefined. This is the structural fix §5.7 asked for, applied to the
     dimension §5.7 missed. **This bullet originally read "total by
     construction — the *language* guarantees it is defined for every
     possible argument". Retracted: `default` guarantees definedness only
     when the rules `verdict` depends on evaluate without a runtime error.
     §5.9 executed the counterexample.**

   Executed proof (both routes, `opa`+hcl2json and real `conftest --combine`):

   ```
   5-hop chain   (verifier's /tmp/av/deep)  before: []  after: DENY (resolves to the lambda's arn)
   5-hop + correct topic policy (evasion)   before: []  after: DENY   <- round-12 still silent
   4-hop control                            before: DENY after: DENY
   1-hop defect (a)                         before: DENY after: DENY
   defect (b) correct solution              before: []   after: []    <- still 1.0
   12-hop chain                             -> resolved
   3-node cycle / self-loop                 -> unresolvable, no hang
   chain dying in a conditional / literal / container / undefined local
                                            -> unresolvable, naming the dead end
   ```

   A totality assertion now runs over 15 adversarial symbol shapes (including
   `""`, a non-`local.` traversal, and a 12-hop chain):
   **`missing: []`, `bad_kind: []`** — every probe produces a verdict, and
   every verdict is one of exactly three kinds. The 19-fixture sweep is
   unchanged. **These are the regression fixtures; they must land with the
   code.**

   > **Round-13 caveat on this assertion.** It ran all 15 shapes inside a
   > *single* query, so it can only detect a *missing* verdict — never a
   > *runtime error*, which aborts the assertion itself and makes the suite
   > emit nothing. §5.9 is the shape it could not see. The replacement runs
   > **one OPA process per shape and checks the exit code**; it is 35 shapes
   > plus a 400-case randomised hunt.

   **The lesson, sharpened by having to learn it twice:** §5.7 concluded that
   *"no rule matched" must never be a reachable outcome*, and then I fixed
   only the dimension the verifier had demonstrated. Enumerating shapes is
   what keeps failing — twice now, both times silently, both times in the
   false-PASS direction the design claims to have made impossible. The
   contract must be carried by a construct that **cannot** be undefined
   (`default`), not by an enumeration I believe is exhaustive. Note that the
   fixture sweep could not catch either bug: no fixture used a >4-hop chain,
   and none will use whatever the third shape turns out to be.

   *(Round-13 postscript: the third shape turned out not to be a missing
   verdict at all. It was a shape on which `verdict` never got the chance to
   be anything — see §5.9. The sentence above was right that the sweep would
   not catch it, and wrong about the direction.)*

9. **`_leaf` built its key by dot-joining the walk path, so two distinct
   paths could claim one key with different values — `eval_conflict_error`,
   which ABORTS the whole evaluation and scores a CORRECT solution 0.0 with
   no deny message. This is the third instance of the class §5.7 and §5.8
   declare closed, and it is the one that falsifies the totality claim the
   recommendation rests on.**

   **The mechanism.** `walk()` yields each nesting *path* — an array of
   segments. `_leaf` turned it into a symbol with
   `concat(".", array.concat(["local"], path))`. **That mapping is not
   injective.** HCL map keys are arbitrary strings, so a key may itself
   contain a dot, and then two different paths dot-join to the same string:

   ```
   path ["arns", "media.bucket"]   -> "local.arns.media.bucket"
   path ["arns", "media", "bucket"] -> "local.arns.media.bucket"   <-- same key
   ```

   A Rego object-comprehension rule (`_leaf[sym] := v`) that binds one key to
   two **different** values raises `eval_conflict_error`. That is not an
   undefined rule — it is a **runtime error**, and OPA aborts the entire
   query. No `default` clause anywhere downstream can intercept it, because
   the evaluation that would have reached the default never completes.

   **Minimal trigger** (three lines of valid HCL, `terraform` accepts it):

   ```hcl
   locals { t = { "a.b" = aws_s3_bucket.media.arn, a = { b = aws_sns_topic.audit.arn } } }
   ```

   ```
   $ opa eval -f raw -I -d policy_pre13 'data.cdktn_bench.hcl._leaf' < in.json
   1 error occurred: .../traversal.rego:78: eval_conflict_error: object keys must be unique
   exit=2
   ```

   **Control** — the identical shape with the *same* value on both paths
   returns `{...}`, exit 0. The trigger is a differing-value key collision,
   nothing else.

   **Full false-fail, executed end to end.** The verifier's artifact (a
   *fully correct* solution — both slots right — that additionally carries
   `"media.bucket"` alongside `media = { bucket = … }`; terraform 1.15.8
   plans it):

   ```
   round-12 oracle                       -> denies=0            (graded 1.0 today)
   prototype, opa+hcl2json route         -> stdout EMPTY, exit 2
                                            stderr: eval_conflict_error
   prototype, real conftest --combine    -> Error: running test: check combined:
                                            ... eval_conflict_error, exit 1
   ```

   **And the harness converts that into a score.** `static_tiers.sh:124-128`
   is `opa eval … < "$ARTIFACT" | jq -e 'length == 0'`. An aborted `opa eval`
   writes **nothing** to stdout; `jq -e` on empty stdin exits **4**; the
   `elif` fails; `tier1_status=FAIL`; **reward 0.0 on a correct solution,
   with no message naming what failed.** Executed and confirmed
   (`printf '' | jq -e 'length == 0'; echo $?` → `4`). The verifier's attack
   artifact — the same dotted-key shape *plus* the laundered wrong-type ARN
   — crashes identically, so a real defect goes **ungraded rather than
   denied**: it happens to land on 0.0, but for the wrong reason and with no
   evidence attached.

   **Why neither totality probe could see it.** The round-12 assertion asked
   for `verdict` over 15 shapes **inside one query**, and my own follow-up
   probe over 25 shapes did the same. A conflict on shape *k* aborts the
   assertion's own evaluation, so the suite emits nothing — and "nothing"
   read as "no missing verdicts". **The probe was inside the blast radius of
   the thing it was probing.** That is the methodological finding, and it
   outlives this prototype: *a totality assertion must run one process per
   shape and check the exit code*, because a runtime error is invisible from
   inside the evaluation it kills.

   **Fixed structurally, not by enumeration.** Do not dot-join a path.
   `_leaf` is now keyed by `json.marshal` of the path **array**:

   ```rego
   _key(path) := json.marshal(path)          # injective on arrays of strings

   _leaf[k] := v if {
       some path, v
       walk(locals_table, [path, v])
       count(path) > 0
       every p in path { is_string(p) }
       k := _key(array.concat(["local"], path))
   }
   ```

   `walk` yields each path exactly once and `json.marshal` is injective on
   arrays of strings, so **no two bindings of this rule can share a key**.
   Conflict-freedom is a property of the key construction, not of my having
   listed the right shapes. Graph nodes are these same marshalled keys, so
   `graph.reachable` is unaffected.

   **The symbol side needed the same treatment.** Once paths stopped being
   dotted strings, *parsing* a reference back into a path had to stop being
   `split(".")`. Terraform emits the bracket form **verbatim** — executed:

   ```
   source_arn = local.arns["media.bucket"]
     -> .configuration…references = ["local.arns[\"media.bucket\"]", "local.arns"]
   ```

   so a real tokenizer replaces `normalize()`:
   `parse_traversal(t)` matches `(?:^|\.)ident` and `["…"]` segments and
   **requires the matches to tile the input exactly** (their lengths must sum
   to `count(t)`). Anything it cannot tile — an operator, a call, whitespace,
   an escaped quote, a numeric index — yields **no parse**, and every
   consumer treats no-parse as `unresolvable`, never as "probably fine".
   `deepest()` in the calling policy now prefix-tests on segment **arrays**
   too, and its path function is total, so a reference the tokenizer cannot
   parse can no longer silently *vanish* from the reference set and leave a
   lone survivor looking like a confidently-resolved slot.

   **A conflict I introduced while fixing this, and how it was caught.** The
   new "not a parseable traversal" verdict clause overlapped the `var.*`
   clause: an unparseable `var.x[0]` matched **both**, with different values
   — a fresh `eval_conflict_error`, the very class being fixed. The
   one-process-per-shape probe flagged it immediately; inspection had not.
   The `var.*` clause now carries an explicit `parse_traversal(s)` guard.

   **Executed re-proof.**

   ```
   35 hand-built shapes, ONE OPA PROCESS EACH, exit code checked per shape:
       fixed policy      -> 35 OK,  0 FAIL
       round-12 policy   -> 32 OK,  3 FAIL  (dot_collide_diff, dot_collide_3way,
                                             dot_key_top -- all eval_conflict_error)
   400 randomised locals tables with dotted keys, one process each, same seed:
       fixed policy      -> 0 failures
       round-12 policy   -> 10 failures, all eval_conflict_error at traversal.rego:78

   38-artifact corpus (19 checked-in broken fixtures + 9 spike cases +
   10 verifier artifacts), fixed vs round-12, full deny-set diff:
       exactly 3 artifacts change behaviour -- the 3 that used to CRASH:
         correct solution + dotted key                CRASH -> []      (1.0, correct)
         attack: laundered wrong-type ARN + dotted key CRASH -> DENY   (0.0, named)
         correct solution using local.arns["media.bucket"] in the slot
                                                      CRASH -> []      (1.0, correct)
       every other artifact is byte-identical. Zero regressions.

   both original defects, re-proved after the fix:
       defect (a) false PASS  -> DENY (resolves to aws_lambda_function.ingest.arn)
       defect (b) false FAIL  -> []   (1.0)
   ```

   New regression shapes that **must land with the code**: dotted key vs
   nested path with *differing* values; with *identical* values; the 3-way
   collision (`"a.b.c"` / `"a.b".c` / `a.b.c`, which now resolve to three
   *different* buckets, correctly); a dotted key at the top level of
   `locals`; a chain hop through `local.t["a.b"]`; keys containing a space,
   a quote, a backslash, a bracket and non-ASCII; and `var.x[0]`.

   **The harness must stop conflating "denied" with "crashed".** Even with
   this fixed, today's gate maps *policy denied* and *policy did not
   evaluate* onto the same word, `FAIL`, with no message — which is how this
   defect produced a score at all. The fix is three lines and was executed:

   ```sh
   if ! out=$(opa eval -f raw -I -d "$POLICY" "$QUERY" < "$ARTIFACT" 2>"$ERR"); then
     tier1_status=ENGINE_ERROR      # run-invalidating: a defect in the ORACLE,
     cat "$ERR" | tee /logs/verifier/tier1-engine-error   # not a judgement
   elif printf '%s' "$out" | jq -e 'length == 0' >/dev/null 2>&1; then ...
   ```

   Executed on the crashing policy + the correct solution:
   today's gate → `tier1_status=FAIL` (silent 0.0); hardened gate →
   `tier1_status=ENGINE_ERROR` with the `eval_conflict_error` printed. This
   belongs in the generator regardless of whether the resolver is adopted:
   **any** future oracle bug of this class is currently graded as the
   agent's failure.

   **The generalizable lesson, third time.** §5.7: *"no rule matched" must
   never be reachable.* §5.8: *carry the contract with `default`, not with
   enumeration.* §5.9 is the limit of both: **a `default` clause is a
   guarantee about definedness, not a guarantee about evaluation.** The
   remaining way to lose is for evaluation to abort, and the only defences
   against that are (i) building keys that are injective by construction
   rather than by convention, (ii) probing totality **one process per shape**
   so a crash is observable instead of self-concealing, and (iii) a harness
   that reports "the oracle did not run" as a distinct, loud outcome.

---

## 6. Deliverable 3 — mechanics

### How conftest feeds two inputs to one policy

Three mechanisms exist; all were executed.

**(i) `parse_config_file(path)` — works, with a sharp edge.** The path is
resolved **relative to the policy file's directory**, *not* the process CWD,
and **an absolute path FAILS** (it is joined onto the policy dir). Executed:

```
parse_config_file("/tmp/spike/base/main.tf")   -> UNDEFINED   (absolute: broken)
parse_config_file("main.tf")  [cwd has it]     -> UNDEFINED   (CWD is not the base)
parse_config_file("beside.tf")[policy dir]     -> OK
parse_config_file("../base/main.tf")           -> OK          (".." works)
parse_config_file("does-not-exist.tf")         -> UNDEFINED, NOT an error  ← fails OPEN
```

In a real trial the policy is at `/app/project/tests/policy.rego` and the
artifact at `/app/project/main.tf`, so the spelling would be
`parse_config_file("../main.tf")`. It also cannot glob
(`parse_combined_config_files(["../base/*.tf"])` → UNDEFINED) and Rego has
no directory listing, so **a policy cannot discover agent-created files**.

**(ii) `parse_combined_config_files([paths])`** — same path rules; returns an
**array** of `{"path": ..., "contents": {...}}`, not a merged document.

**(iii) `conftest test --combine` — the mechanism that actually fits.** The
shell globs, conftest parses each file with the parser its extension selects,
and `input` becomes an array of `{path, contents}` sorted by path:

```
$ conftest test --combine --policy tests/ --namespace <pkg> plan.json *.tf
   input = [{"path":"main.tf",...},{"path":"plan.json",...},{"path":"provider.tf",...}]
```

Dotted namespaces work (`--namespace cdktn_bench.s3_notification_authoritative_singleton`,
executed). This is the only one of the three that survives an agent creating
new `.tf` files.

### The exact invocation — and why it should NOT be conftest

Today's generated `tests/static_tiers.sh` runs:

```sh
opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.<scenario>.deny" < plan.json
```

and the reward contract is *"tier-1 FAILs iff that raw output is not `[]`"*.
Switching the engine to conftest changes `input`'s shape for **every existing
rule** in every scenario, and swaps a `[]`-comparison for conftest's own exit
code and result format. **The recommended invocation keeps opa and adds one
pre-merge step:**

```sh
# 1. HCL -> JSON, one object keyed by filename (glob covers agent-created files)
HCL_JSON=$(python3 - <<'PY'
import json, subprocess, glob
print(json.dumps({f: json.loads(subprocess.check_output(["hcl2json", f]))
                  for f in sorted(glob.glob("*.tf"))}))
PY
)
# 2. merge under ONE new key -- `input` stays byte-identical for every existing rule
printf '%s' "$HCL_JSON" > hcl.json
jq -s '.[0] + {"_hcl": .[1]}' plan.json hcl.json > oracle-input.json
# 3. UNCHANGED engine, UNCHANGED reward contract
opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.<scenario>.deny" < oracle-input.json
```

Executed end to end; produces results identical to the conftest route on all
13 artifacts. Note `conftest parse` itself is *not* suitable for step 1: with
one file it prints the bare document, with several a filename-keyed map —
inconsistent for a generated script. `hcl2json` always prints the bare
document for exactly one file, which is why the loop above is stable.

### Offline

**Yes, fully offline.** `conftest test` with a local `--policy` directory
succeeded with `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` pointed at a dead port
(executed). Network is used only by opt-in `conftest pull` / OCI bundle
fetching, neither of which a generated script would call. `hcl2json` does no
I/O beyond the file. Both are static Go binaries, no runtime deps.

---

## 7. Deliverable 4 — cost

Measured, `linux/arm64`, uncompressed on-disk:

| binary | size | note |
|---|---|---|
| `opa 1.19.0` (`opa_linux_arm64_static`) | **57.0 MB** | already in the image; sha re-verified against the Dockerfile pin ✅ |
| `conftest 0.69.0` | **68.3 MB** | embeds **OPA 1.19.0** — same engine, same Rego semantics |
| `hcl2json 0.6.9` | **4.06 MB** | **conftest's own HCL2 parser, standalone** |

* **conftest as a *replacement* for opa: +11 MB** — but it is not a drop-in
  (different CLI contract, different `input` shape, different exit semantics),
  so the saving is illusory.
* **conftest *beside* opa: +68 MB.**
* **hcl2json beside opa: +4.1 MB.** ← recommended.

**Provenance, verified in-spike:** conftest's parser is
`github.com/tmccombs/hcl2json@v0.6.7` (extracted from the shipped binary), and
`hcl2json 0.6.9`'s output on this scenario's `main.tf` is **byte-identical**
to `conftest 0.69.0 parse` (`diff` of both through `jq -S` → no differences).
There is no capability in conftest's HCL2 parsing that hcl2json lacks.

**Runtime overhead: negligible.** Three runs each, warm:
`conftest test --combine` **0.02s**; `opa eval` (today's oracle) **0.01–0.07s**;
`hcl2json main.tf` **0.01s**. Against a `terraform init`+`plan` that dominates
the tier by two orders of magnitude, this is free.

**Pinning**, matching the `opa 1.19.0` block in
`arms/hcl-raw/environment/Dockerfile` (raw binary + `sha256sum -c`, which
hcl2json supports directly since it publishes unarchived binaries):

```
hcl2json v0.6.9
  linux_amd64  b609e37094948c0b77cd8c6c0baaf8af2bd168c685c6e3334d671cc9692c34a5
  linux_arm64  cb2ccf59a830829fe122e8dfb85d6ef2500aceda5af45a7c1052a4d2c46541f9
  https://github.com/tmccombs/hcl2json/releases/download/v0.6.9/hcl2json_linux_${TARGETARCH}
  (upstream publishes hcl2json_0.6.9_checksums.txt -- unlike opa, this pin
   CAN be cross-checked against an upstream manifest, so the caveat in the
   opa block does not apply here)

conftest v0.69.0 (if chosen instead -- tarball, so unpack then verify)
  Linux_x86_64  96fc2fbf11f0afde51256647127e6f00a64ce839a4d9a0a1aef2426c0e6f4b3f
  Linux_arm64   3b9c35223fe35f9988e153cdffb0144f911201306c746758b73be82831c543d9
```

*No Dockerfile was modified by this spike.*

---

## 8. Deliverable 5 — multi-file reality

The agent owns `main.tf`; `provider.tf` is read-only and separate; the agent
may create further `.tf` files.

* **`parse_config_file("../main.tf")` alone is NOT sufficient.** Executed:
  moving the `locals` block into an agent-created `locals.tf` makes every
  symbol UNRESOLVABLE → the correct solution is DENIED. Since a Rego policy
  can neither glob nor list a directory, the policy cannot recover.
* **`parse_combined_config_files` does not fix it either** — it takes a fixed
  path list, no globs.
* **The glob must therefore happen in the shell.** Either
  `conftest test --combine ... plan.json *.tf` or the `hcl2json` loop in §6.
  Executed with the locals hoisted into `locals.tf`: **PASS**, correctly.
* `provider.tf` is picked up harmlessly by the glob (it contributes a
  `variable` block and a `provider` block; the resolver ignores both). Its
  inclusion is in fact *desirable* — an agent could legally define a local in
  any file, and a `var.*` default lives there.
* **Gap:** `main.tf.json` (terraform-legal) is missed by a `*.tf` glob. Handle
  it explicitly rather than discovering it via a false fail.

---

## 9. Arm impact — confirmed by synthesis, not asserted

### awscdk — NO benefit needed. **CONFIRMED.**

Synthesized the exact awscdk twin of the hoisted-locals shape
(`aws-cdk-lib 2.263.0`, `cdk synth --no-lookups`):

```ts
const arns = { mediaBucket: bucket.bucketArn, auditTopic: topic.topicArn };
new lambda.CfnPermission(this, "AllowS3Invoke", { sourceArn: arns.mediaBucket, ... });
```

The TS variable is gone at synth time and the template names its referent:

```json
"AllowS3Invoke": { "Properties": {
  "SourceArn": { "Fn::GetAtt": [ "MediaBucketBCBB02BA", "Arn" ] },
  "FunctionName": { "Ref": "IngestHandler6F5F26C7" } } }
```

The value is still deploy-time unknown, but the **traversal is explicit** —
the awscdk oracle already has what the hcl_raw oracle is missing. Conftest
adds nothing.

### The CFN indirection gap — recorded AND now exercised

The analogous problem exists in CloudFormation and would bite if a solution
used it. Synthesized deliberately (`CfnMapping` + `CfnParameter`):

```json
"SourceArn": { "Fn::FindInMap": [ "ArnMap", "us", { "Ref": "WhichBucket" } ] },
"Mappings": { "ArnMap": { "us": {
    "media": { "Fn::GetAtt": [ "MediaBucketBCBB02BA", "Arn" ] },
    "other": { "Fn::GetAtt": [ "OtherBucketD0A343B2", "Arn" ] } } } }
```

Two observations that make this a *different, easier* problem than HCL's:
1. **It is strictly worse semantically** — the second-level key is a
   deploy-time `Parameter`, so even a perfect resolver can only report
   **AMBIGUOUS (N=2)**, never RESOLVED. Same for `Fn::If`.
2. **But it is strictly easier mechanically** — `Mappings`, `Parameters` and
   the intrinsics all live **inside the single template.json the oracle
   already reads**. No second input, no HCL parser, no lexer: the referents
   are already `Fn::GetAtt` structures. If this is ever closed, it is a pure
   Rego change to the awscdk policies, costing **zero** new tooling.

No current awscdk fixture uses these, so it stays a **known-but-unexercised**
gap — now with a synthesized reproduction on file.

### terraconstructs — NO benefit needed. **CONFIRMED, with one caveat.**

Inspected five real synthesized `cdk.tf.json` documents. **Every one has
`locals == false`** (top-level keys: `//`, `data`, `output`, `provider`,
`resource`, `terraform`, `variable`, `moved`), and cross-resource references
are emitted as direct, fully-qualified interpolations, e.g.
`"repository": "${github_repository.cdktn-provider-template_repo_5C27D804.name}"`.
cdktn resolves TS variables at synth exactly as CDK does, so
`.configuration...references` in the plan already carries the real traversal.

**Caveat, verified:** `TerraformLocal` exists in `cdktn` and *does* emit a
`locals:` block (`cdktn/lib/terraform-local.js`). An agent using it
reintroduces the problem for this arm. **But the fix would still not need
conftest** — `cdk.tf.json` is already JSON, so the harness can merge it into
the oracle input with `jq` alone, and the same `traversal.rego` library
resolves it unchanged.

### hcl_raw — the entire benefit. **CONFIRMED.**

---

## 10. RECOMMENDATION

**ADOPT NARROWLY — with the caveat stated first, not last.**

> **The prototype's own safety contract has now failed THREE times under
> adversarial verification** (§5.7 missing arity gate — silent PASS; §5.8
> `verdict` undefined past 4 hops — silent PASS; §5.9 `eval_conflict_error`
> aborting the evaluation — silent FAIL on a *correct* solution). None was
> caught by review or by the fixture sweep; all three were caught by someone
> actively attacking the oracle. Weigh that against this recommendation.
>
> After §5.8 I wrote that the third instance of this class "can no longer be
> a *missing verdict*". That was true and it was beside the point: **the
> third instance was not a missing verdict, it was a missing evaluation.**
> Each round I have named the mechanism that just failed and asserted the
> class was closed; each round the class had one more dimension. The pattern
> in my own claims is more informative than any single fix:
>
> | round | failure | my claim afterwards | how it was falsified |
> |---|---|---|---|
> | §5.7 | slot never reached the resolver | "every slot now gated" | a *different* dimension (totality) |
> | §5.8 | `verdict` undefined | "**the language guarantees** it is defined" | a *runtime error*, which `default` does not cover |
> | §5.9 | evaluation aborts | *(stated below, with its limit attached)* | — |
>
> **A reader who concludes that three failures is enough to reject is
> drawing a defensible conclusion from the same evidence I have** — and the
> §5.9 case is the strongest one for that reading, because the over-claim
> ("total by construction, the language guarantees it") was load-bearing for
> the recommendation and was wrong for two revisions. What I can say for
> §5.9's fix that I could not say for the previous two: it removes the
> *possibility* rather than the *instance* — the key is injective by
> construction, so this rule cannot conflict on any input at all — and it
> ships with a probe methodology (one process per shape, exit code checked)
> that would have caught all three of these bugs, plus a harness change that
> makes "the oracle did not run" a distinct, loud outcome instead of a score.

Specifically:

1. **Adopt the capability. Reject the binary.** Add `hcl2json 0.6.9`
   (4.1 MB, sha-pinned, offline, no network) to the hcl-raw arm image. **Do
   NOT add conftest** — it is the same parser at 17× the size, and adopting
   it as the *engine* would change `input`'s shape for every existing rule in
   every scenario and replace a proven reward contract. Its one genuine
   advantage (`--combine` doing the file glob) is replicable in four lines of
   shell.
2. **Keep `opa 1.19.0` as the engine and the reward contract byte-identical.**
   Merge the parsed HCL into the existing plan document under one reserved
   key (`_hcl`). Every existing rule in every scenario keeps working
   untouched; only new rules read it.
3. **Glob in the shell, never in the policy** (`*.tf`, plus `*.tf.json`
   explicitly). A Rego policy cannot discover agent-created files, and the
   locals-in-`locals.tf` case is a live false-fail otherwise (executed).
4. **Adopt narrowly: this scenario first**, and only for
   *dedicated single-ARN argument slots* — the two the defects live in. Do
   not attempt document-wide (`jsonencode`) resolution, modules, or
   `var.*` in the first cut.
5. **Fail closed, explicitly and loudly — and make it structural, not a
   convention.** AMBIGUOUS and UNRESOLVABLE both DENY with a message naming
   the symbol and quoting the expression. Add a dedicated "no `.tf` was
   supplied" rule — without one the policy fails *open*, because a missing
   file makes the builtin *undefined*, not an error. **And put the arity gate
   in the library, not in each rule.** The prototype originally shipped that
   gate on slot 1 and omitted it on slot 2, producing an executed silent pass
   and a regression against round-12 (§5.7) — two twin rules twenty lines
   apart, and review did not catch it. The library must expose a *total*
   slot-reader that returns an explicit verdict for the 0-reference and
   N>1-reference cases instead of going undefined, so that "no rule matched"
   is not a reachable outcome at any call site. Treat §5.7 as a **landing
   precondition**, not a footnote.

   **And totality is a second dimension, not the same one.** §5.8 is the
   proof: the §5.7 fix made the *entry* condition total and left the
   *verdict* condition partial, and the gap was another silent pass. The
   shared library must guarantee **both** — a total `slot_refs` (arity) *and*
   a total `verdict` (classification). Use a Rego `default` clause on every
   function whose absence would read as a pass. Walk reference chains with
   `graph.reachable`, never with hand-unrolled hops: an unrolled walk has a
   cliff, and a cliff in a fail-closed design is a silent pass, not a loud
   one.

   **And a `default` clause is NOT a totality guarantee — this is the
   correction §5.9 forces, and it applies directly to this point.** `default`
   makes a rule *defined*; it does nothing if a rule that rule *depends on*
   raises a runtime error, because evaluation aborts before any clause runs.
   Everywhere this memo previously said "total by construction — the
   language guarantees it", read "total against undefinedness, provided
   evaluation completes". Three further obligations follow, and they are
   landing preconditions:
   * **Build every rule key so that it is injective by construction** — never
     by dot-joining, concatenating, or otherwise flattening a structured
     value into a string that a data-dependent value could collide in. HCL
     map keys are arbitrary strings; assume an adversary picks them.
   * **Probe totality one process per shape, checking the exit code.** An
     assertion that evaluates every shape in one query cannot see a runtime
     error — the error kills the assertion. All three of §5.7/§5.8/§5.9
     would have been caught by the one-process-per-shape probe; none was
     caught by the in-query one.
   * **Make the gate distinguish "denied" from "did not evaluate"** (see
     point 8).

   **§5.7, §5.8 and §5.9 are all landing preconditions.**

6. **The merge must be additive: round-12's rules stay.** The recommendation
   is to *merge* `_hcl`-aware rules into the existing `policy.rego`, not to
   replace it — and §5.7 is the concrete reason that distinction decides the
   real-world blast radius. Round-12's zero-reference rules
   (`"its source_arn argument carries no resource reference at all"` and
   `"its `arn` argument carries no resource reference at all"`) **must survive
   the merge verbatim.** They are what catches a laundered literal ARN in
   either slot, they are not subsumed by resolution (a constant has no symbol
   to resolve), and the prototype's silent pass is exactly what happens when
   one of them is dropped. The new rules *narrow* verdicts on slots that
   carry references; they remove no existing deny. A merge that keeps every
   round-12 rule and adds the `_hcl` ones has a blast radius limited to
   artifacts round-12 currently mis-scores — which is the point.

   **But do not read this as a safety net.** §5.8's evasion artifact is
   silent under round-12 *and* was silent under the prototype: a laundered
   chain in slot 1 plus a fully correct topic policy satisfies every
   round-12 rule. Keeping round-12 is necessary (it catches zero-reference
   literals that resolution cannot) and **not sufficient** — it does not
   backstop a resolver bug. The additive merge limits blast radius; only
   totality prevents silent passes.
8. **Change the generated gate so "the oracle did not run" is not a score.**
   Independent of this proposal: `static_tiers.sh` currently pipes
   `opa eval` straight into `jq -e 'length == 0'`, so an aborted evaluation
   (empty stdout) becomes `tier1_status=FAIL` — the agent is charged for a
   defect in the oracle, with no message. §5.9 is that bug, executed, on a
   correct solution. Capture the exit code and emit a distinct
   `ENGINE_ERROR` / run-invalidating status with the engine's stderr logged,
   exactly as the arm already does for `TOOL_MISSING` and `SKIPPED_STUB`.
   Three lines; executed in §5.9. **This should land whether or not the
   resolver does.**

7. **Before landing, solve the shared-library problem.** `oracles/rego/` has
   no `common/` mechanism. Copy-pasting a 150-line hand-written HCL lexer
   into every scenario that needs it is the worst of the available options.
   **This is the real cost of adoption and it should gate the decision, not
   follow it.**

### What decides it

* Both proven defects are fixed, executed, in the right direction, with true
  deny messages — and the round-12 `THREE USES` shape recorded as
  *"IRREDUCIBLE from this artifact"* is **not** irreducible once `main.tf` is
  an input. It was reproduced (old **1.0**) and closed (new **DENY**).
* Zero regressions across all 19 existing `broken/` fixtures — **as
  re-measured after the §5.7 and §5.8 fixes.** The pre-fix prototype *did* carry one
  regression (a checked-in fixture round-12 denies and the prototype passed
  silently); it was found by verification, not by the sweep, because the
  sweep counted silences without asking whether each was inside a slot. The
  post-fix sweep denies 11 and is silent on 8, and each of the 8 was
  re-audited attribute-by-attribute to confirm the silence is genuine.
* The standing one-sided cross-arm strictness difference this scenario
  currently records can be **closed rather than documented**, which is worth
  more than the 4 MB by a wide margin.
* Cost is 4.1 MB and ~10 ms.
* The capability claim now holds **at any laundering depth** (executed at 1,
  4, 5, 12 and 40 hops), and `verdict` is defined for every argument on which
  evaluation completes. The regression evidence is now an executed
  **one-process-per-shape** probe over 35 adversarial shapes (0 failures;
  the round-12 policy fails 3 of them with `eval_conflict_error`) plus a
  **400-case randomised hunt** over dotted-key `locals` tables (0 failures;
  round-12 fails 10), plus a full deny-set diff over a 38-artifact corpus in
  which **exactly the three formerly-crashing artifacts change behaviour and
  nothing else moves**.
* Cost of the §5.9 fix is bounded: 1000 leaves plus a 40-hop chain resolve in
  **30 ms**, indistinguishable from the round-12 oracle's own runtime.

**Against, and I do not want this buried:** three executed failures of the
prototype's own safety contract, two silent passes and one silent fail.
Every capability number in this memo comes from a prototype that has three
times been shown to over-claim by someone attacking it, and the thing that
found them was adversarial construction — never the fixture sweep, and in
§5.9's case not even the totality assertion, which was inside the blast
radius of the bug it was meant to detect. If this lands, it should land with
the §5.8 **and** §5.9 regression fixtures (deep chain, cycle, dead-end
chain, the evasion artifact, and the dotted-key collision family), with the
one-process-per-shape probe and the randomised hunt wired into
`make falsifiability`, with the gate change in point 8, and with an explicit
expectation that the oracle gets attacked again before it is trusted. **The
base rate so far is one executed defect per round of verification; nothing
in this round justifies assuming that has stopped.**

### What would make me say reject

If the shared-library problem is judged too invasive to solve now, then the
honest alternative is **not** to hand-copy this lexer into one scenario — it
is to leave the round-12 policy in place with its residual documented, and
revisit when a second scenario needs the same capability. One scenario does
not justify a new tool in the image *and* a new duplicated-code pattern in
`oracles/`. Two do.

### Not recommended, and why

* **A shell pre-parse producing `locals.json`** (the alternative this spike
  was asked to compare against): strictly worse. It needs the same lexer, in
  a *second* language, outside the policy — so the classification logic and
  the deny messages live in different files with no shared falsifiability.
  The `_hcl` merge keeps all reasoning inside `policy.rego`, where
  `make falsifiability` already covers it.
* **Full expression evaluation.** Never. That is reimplementing Terraform.
  The three-valued contract exists precisely so the oracle can say
  *"I cannot tell"* out loud instead of guessing — which is what produced
  both defects in the first place.
