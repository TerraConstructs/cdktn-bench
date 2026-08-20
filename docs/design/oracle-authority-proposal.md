# Proposal: where oracle authority should live — behavioural probes vs. structural asserts

**Status:** proposal for operator decision. Nothing implemented. Would require a
pre-registered amendment before any scenario adopts it, because it changes what
a reward *means*.
**Date:** 2026-08-20
**Origin:** the `apigw-openapi` prompt critique. Its instruction contained
"each route is its own API Gateway resource and method, individually reachable
and individually wired -- not an API whose routes exist only inside an imported
OpenAPI document body" — a sentence that existed only because the asserts
counted per-route resources. Removing it (correctly, see
`docs/adding-scenarios.md` §1 item 3a) exposes the deeper question: *if the
prompt may not force a shape, what is the oracle judging?*

---

## 1. The validity threat, stated plainly

A structural assert says **"the synthesized template contains X."** If two
different implementations both satisfy the ticket and only one contains X, then
`tokens-to-green` is measuring *"tokens until the agent guesses our expected
shape"*, not *"tokens until working infrastructure."*

That is not a cosmetic issue. It is the single most available line of attack on
the benchmark's headline claim, and it gets worse as prompts get leaner —
because a lean prompt deliberately stops telling the agent which shape we
expect. **The prompt-writing rules and the current oracle design are in
tension, and this proposal is about resolving it in the oracle.**

## 2. Where we are today (measured, 2026-08-20)

| | count |
|---|---|
| scenarios with a live tier | 2 of 6 (`apigw-redeploy`, `named-resource-replacement`) |
| tier-0 asserts (static: synth/plan text) | 26 |
| tier-1 asserts (static: graph/intent) | 14 |
| planted mistakes caught at tier 0 / 1 / live | 6 / 5 / 1 |

**~92% of the benchmark's catching power reads templates rather than reality.**

The mechanism for the alternative already exists and is proven in production:
`apigw-redeploy`'s `live_check.py` `urlopen`s the deployed API and asserts real
HTTP responses. `named-resource-replacement` uses the grey-box variant (EC2
`describe-*` calls). So the question is not *can we*; it is *how much weight
moves*.

## 3. How much would today's traps tolerate a behavioural oracle?

Nearly all of them. Walking the shipped and blueprinted traps and asking *"does
this manifest at runtime?"*:

| trap | manifests? | how a probe sees it |
|---|---|---|
| exclusive IAM policy attachment | **yes** | the *other* role loses its policy — `describe` shows it |
| missing `create_before_destroy` | **yes** | the agent's own second apply fails |
| ASG tag propagation | **yes** | `describe-instances` / volume tags |
| stale API Gateway deployment | **yes** | the deployed stage serves the old route set |
| drift | **yes, by definition** | out-of-band change vs. next plan |
| teardown / force-delete | **yes, by definition** | destroy succeeds or does not |
| policy JSON normalization | **yes** | second plan is non-empty |
| bucket-hardening decomposition | **no** | a correct bucket looks identical either way |

The one "no" is the interesting case, and it argues *for* the change rather
than against it: that scenario's signal was never correctness — it is
**authoring cost**, which already lives in the token count. **A behavioural
oracle does not lose the decomposition signal, because the oracle was never
carrying it.** It only has to certify "it works."

### 3.1 The one thing a behavioural oracle cannot do alone

It cannot distinguish *"the IaC produced this"* from *"the agent clicked it
together with the CLI."* Structural asserts prevent that implicitly today.

The companion already exists: **the idempotence tier** built for Amendment 28.
A second `plan -detailed-exitcode` returning 0 proves the deployed reality is
what the committed code describes. **Behavioural probe + idempotence = "it
works, *and* the code is what made it work."** Both halves already ship.

## 4. The real tensions — operational, not epistemic

1. **Falsifiability cost inverts.** This is the sharpest cost and the least
   obvious. Today, proving an oracle discriminates runs **offline in seconds**:
   broken fixture in, reward < 1.0 out, no AWS. A live oracle can only be proven
   by **deploying the broken fixture**. Batch A alone is ~12 scenarios × ~3
   broken solutions × 3 arms ≈ **100+ real deploys just to prove the oracles
   work**, before a single measurement trial runs.
2. **Serialization is the schedule-killer.** Live trials hold the per-scenario
   account writer-lock. Today's 18 live-capable trials ≈ 6h serialized; the
   26-scenario queue at 3 arms ≈ 78 trials ≈ 25h+. A same-day results cadence
   stops being possible.
3. **Flake contaminates the metric worse than it slows it.** An AWS throttle or
   an eventual-consistency miss yields a non-green trial that is *not the
   agent's failure* — an **invalid row** in tokens-to-green, not merely a slow
   one. `classify_infra_failure` exists; its load grows with live surface.
4. **Credential-free CI dies.** Static scenarios are the only ones a community
   contributor can verify without an AWS account — the foundation of the
   contribution path (task #12). Full black-box makes the bench unrunnable by
   anyone without the org's account.

## 5. Recommendation: invert the authority, don't replace the tiers

Not either/or. Four moves:

1. **Where a scenario is live anyway, the behavioural probe becomes the
   correctness authority**, and structural asserts are demoted to *pre-flight
   screens* — fast, cheap, early failure feedback. A screen may be loose and
   shape-tolerant **precisely because it is no longer the judge**. This
   dissolves the "oracle surface doubles per accepted shape" problem: shapes
   only have to be tolerated by the screen, and the screen does not decide the
   reward.
2. **Express the probe as a spec-level behavioural contract** — the ticket's
   acceptance criteria as probes (HTTP calls, `describe` assertions), authored
   **once and arm-agnostic**. This is *better parity* than three per-arm
   structural assert sets: the same probe judges all three arms, which is the
   cleanest expression of the parity discipline the benchmark has.
3. **Split falsifiability by tier.** Static screens keep proving offline on
   every CI run. Live probes prove discrimination **once per scenario** (one
   good deploy, one bad deploy, recorded as dated evidence) rather than
   per-fixture-per-arm on every run. This is what makes tension (1) affordable.
4. **Static-only scenarios keep structural asserts**, but the shape-tolerance
   analysis from `docs/adding-scenarios.md` §1 item 3a is their price of
   admission — every accepted shape needs its own reference solution and its
   own broken fixtures.

## 6. What should decide this

The empirical question is **how often static-green diverges from live-green.**
If a trial that passes every structural assert reliably also passes a
behavioural probe, the current design is fine and this proposal is
over-engineering. If they diverge — in *either* direction (shape-compliant but
broken, or working but shape-nonconforming) — the divergence rate is the
argument.

The 2026-08-20 battery (6 scenarios × 3 arms) is the first dataset large enough
to look at. **Decide after those results, not before.**

## 7. Open questions for the operator

1. Does the behavioural contract belong in the spec (arm-agnostic YAML compiled
   to a probe script) or as a hand-authored per-scenario `live_check.py` in the
   style used today?
2. Is "once per scenario, recorded as dated evidence" acceptable falsifiability
   for a live probe, given the pre-registration discipline treats falsifiability
   as a standing gate rather than a one-time proof?
3. Do static-only scenarios stay first-class, or become a deliberately
   second-class tier ("screened, not verified") whose rows carry a caveat?
4. Does the credential-free contributor path (task #12) constrain this — i.e.
   must every scenario keep a meaningful offline gate so contributions remain
   verifiable without an AWS account?
