# Research spike: model-as-oracle

Read: `CLAUDE.md`, `docs/gates.md`, `specs/SCHEMA.md` §4/§0.2/§1, `DECISIONS.md`
Amendments 32/42-47, `oracles/rego/README.md`, `generator/verify_py.py`,
`gates/equipping.py`, `metrics/result_schema.json`, Harbor (`.venv/lib/
python3.13/site-packages/harbor/`), `arms/hcl-modules/environment/docker-
compose.yaml`, `docs/asset-mirror.md`, `docs/design/tf-modules-arm.md` §1,
`docs/design/hcl-modules-spec-matrix.md` §2. Web research 2026-09-24. No AWS
calls; no repo writes besides this file.

## 1. What exists

**TypeSafe AI / "Jev"** is real: a startup that left stealth 2026-09-15 with a
$40M seed (DCVC) at a $200M valuation, founded by Diogo Almeida (ex-OpenAI,
RLHF co-inventor) — confirmed independently by Forbes, SiliconANGLE, Wilson
Sonsini's own release, and Tom's Hardware. Their model **Jev** is what they
call a **"System One" model**: not autoregressive — one forward pass over a
structured question against state, returning a typed answer (Choice / Score
/ "Noul"/binary) plus a calibrated probability, via a proprietary "RLCD"
method. Claims ~193-200x faster and ~400-445x cheaper than an LLM on these
tasks; priced $42/B input tokens. **"System One" is TypeSafe's own coined
term**, not a prior academic category — the underlying System-1/System-2
routing pattern (a small fast model verifies/classifies, escalates to a big
generative model) predates them, but the product name is theirs. **Jev is
closed**: no weights, no GitHub, API/console only (docs.typesafe.ai) — not
self-hostable, and relevant here only as a remote provider (§2).

**"Kev"** — the owner's "Jev" misspelling was actually a second, real,
*open* project: Jared Palmer's `jaredpalmer/kev` on GitHub/HuggingFace, an
explicit open "Jev-alike," built in six days (2026-09-18 to -21). It is a
family, not one model: a LoRA adapter (a few million trainable params) plus
a small pointer/classification head bolted onto a **frozen** Qwen base —
current generation `kev-0.8b`/`kev-4b`/`kev-9b` on Qwen3.5-0.8B/4B/9B-Base
(Apache-2.0 adapter, Qwen base license), superseding short-lived Qwen3 and
an original Qwen2.5-0.5B prototype. Architecturally it reads the input
**once** (prefill-only, no autoregressive decoding) and emits a calibrated
probability over yes/no/multiple-choice/rating — the same three primitives
Jev claims. Self-reported metrics (90.4% acc / 0.156 Brier on one narrow
in-domain set) carry HuggingFace's own `verified: false` flag and n in the
hundreds. Training data is generic NLP classification (banking77, BoolQ, AG
News, MultiNLI, SST-5...) — **zero IaC, code, or policy-verification data**.
No GGUF quantisation exists for any Kev checkpoint (safetensors/adapter
files only), so it needs `transformers`+`peft`, not llama.cpp/Ollama.

**"Laya"** (`github.com/NandhaKishorM/laya`, weights at `huggingface.co/
convaiinnovations/laya`, Apache-2.0) is a third, independent open answer to
Jev: a **non-autoregressive encoder classifier** (ModernBERT-large, 421M
params, 512-token context; a multilingual mmBERT-base sibling at 322M/1024
tokens), same "RLCD-against-proper-scoring-rules" idea, claiming ~33ms
decisions. Safetensors only, no GGUF. Same fixed-choice-head family as Kev,
same gap (no IaC/code training data), and 3,150 HF likes against 0 recorded
downloads on a 6-day-old repo with a GitHub star count that looks
anomalously high against that — worth independently re-verifying.

**Bottom line on all three:** real, but 6-9 days old at research time, none
trained or evaluated on infrastructure-as-code artifacts, and neither open
one (Kev, Laya) speaks the free-text "read this artifact against this
intent, emit `{verdict, reason}`" interface this bench's oracle role needs —
both are fixed-choice/scalar classifiers wearing a "judge" label. Using
either as-is would mean building a bespoke choice/score adapter around their
vendor SDK, not prompting them like an instruct model, then fine-tuning past
their out-of-domain training data — outside this spike's budget.

**Nearest real open-weight alternatives** for a fast local verification
role (HuggingFace, confirmed live):

| model | params | licence | context | GGUF | ~Q4_K_M |
|---|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | 7B | Apache-2.0 | 128K | yes, official | ~4.7GB |
| Qwen2.5-1.5B-Instruct | 1.5B | Apache-2.0 | 32K | yes | ~1.0GB |
| Qwen2.5-3B-Instruct | 3B | Qwen "other" (not Apache) | 32K | yes | ~2.0GB |
| Llama-3.2-3B-Instruct | 3B | Llama community licence | 128K | yes | ~2.0GB |
| Phi-4-mini-instruct | 3.8B | MIT | 128K | yes | ~2.3GB |
| Skywork-Reward-V2-Qwen3-{0.6,1.7,4}B | 0.6-4B | Apache-2.0 | 32K+ | partial | ~0.4-2.5GB |

Qwen2.5-Coder-7B-Instruct is the best fit for "code/structured-text
verification" (Apache-2.0, code-tuned, mature GGUF/llama.cpp support) and is
the model selected for §4. Skywork-Reward-V2 fits a pure judge/reward-model
*architecture* (scalar output, RewardBench/JudgeBench-benchmarked) better if
a scalar rather than a three-valued verdict is wanted. None of these are
special "JSON-constrained" fine-tunes — grammar-constrained decoding
(llama.cpp GBNF, Outlines, vLLM structured output) is an inference-engine
property layered on any instruct model, which is how §4 would have enforced
`{verdict, reason}`.

## 2. Local inference options vs. what Harbor needs

Harbor's verifier already anticipates an LLM-based verifier: `Verifier.
verify()` merges `task.config.verifier.env` into the command env and warns
"the verifier.env contains an API key (often the case for LLM-based
verifiers)" (`.venv/…/harbor/verifier/verifier.py:150-166`). A verifier can
run **shared** (default: same container/network as the agent, torn down
only after verification) or **separate** (own `EnvironmentConfig`, and
critically — the agent's environment is stopped *before* the separate
verifier environment starts: `harbor/trial/single_step.py:35-42`). That
ordering is the one mechanism that can make a judge sidecar genuinely
agent-unreachable. cdktn-bench does not use `separate` today —
`arms/hcl-modules/environment/docker-compose.yaml:8` documents that its
`tf-registry` sidecar is reachable "by name on the project's default
network" by **both** the agent and the verifier, one shared environment.
`allow_internet` also defaults to Harbor's `true` (`specs/SCHEMA.md:269-276`)
and no spec in the corpus sets it `false` — today's tasks already carry open
egress the agent could use to reach a remote judge just as the verifier
could.

| option | what a task must declare | verifier-reachable | agent-reachable (leak?) | equipping hash |
|---|---|---|---|---|
| (a) host llama.cpp/Ollama via `host.lima.internal` | nothing in `task.toml`; verifier shells out to a URL, same pattern as `docs/asset-mirror.md`'s `ARG ASSET_MIRROR=http://host.lima.internal:8899` (`docs/asset-mirror.md:14,62`) | yes, if verifier has network | **yes, by default** (`allow_internet: true`) — a leak unless the spec sets `allow_internet: false`, which then also blocks the verifier in `shared` mode since it's the same container | not covered by scheme 2 at all — a host process is invisible to `compose_sha256`/`harbor_equipping`; two runs against different host model builds hash identically (silent non-reproducibility) |
| (b) compose sidecar, `[verifier] environment_mode = "separate"` | a `verifier.environment.docker-compose.yaml` (or `[verifier.environment]`) declaring the model server as its own service, kept **out of** the agent's `environment/docker-compose.yaml` | yes, by construction | **no**, if and only if separate mode is used and the model service is declared only in the verifier's own environment — the agent's environment is stopped first (`single_step.py:35-42`) | covered: `gates/equipping.py`'s `COMPOSE_REL_PATH` (`gates/equipping.py:65`) only hashes `environment/docker-compose.yaml` (the agent's); a verifier-only compose file is a **new** channel scheme 2 does not read today and would need its own manifest key, on the same "always present, null when undeclared" discipline Amendment 47 used (`DECISIONS.md:8861`) |
| (b') compose sidecar, `shared` mode (the `hcl_modules` pattern as-is) | `environment/docker-compose.yaml` service, Amendment 46/47 shape | yes | **yes** — same network, same lifetime as the agent (`docker-compose.yaml:8`) | covered by `compose_sha256` already |
| (c) LiteLLM facade in front of a remote or local model | `task.toml [verifier].env` (API key/base URL) exactly as Harbor's own comment anticipates (`verifier.py:150-166`); or a remote Jev/System-One API behind it | yes | **yes** by default (`allow_internet: true`); still a leak unless network-partitioned, and now also a real network dependency (egress, provider uptime, rate limits) the offline gates (`gates/aws_stub.py`, `docs/asset-mirror.md`) exist specifically to avoid for AWS | `env` values are not content-hashed by scheme 2 (only file bytes and Harbor's declared config are); a rotated API key or swapped backend model would not move the hash — a real gap if this path is used for grading |

**Verdict on (a)/(b)/(b')/(c):** only **(b) with `[verifier]
environment_mode = "separate"`** gives network partition from the agent for
free from Harbor's own lifecycle — the agent environment is already gone
before the sidecar exists. It needs a new equipping-hash channel (a
`verifier_compose_sha256`, parallel to `compose_sha256`) plus an amendment,
and turning `allow_internet` off on the **agent's** environment specifically
(already supported per-spec, `specs/SCHEMA.md §0.2`) while the verifier's own
separate environment stays able to reach its sidecar.

**colima has no GPU passthrough** (macOS Virtualization.Framework exposes no
Metal device into the Linux VM), so inference *inside* a compose sidecar
(b/b′) is CPU-only regardless of the host's Apple Silicon GPU. Only (a),
on the bare host via `host.lima.internal`, gets Metal acceleration.

## 3. Oracle fitness, against this bench's own rules

| property | jq/Rego (tiers 0/1) | an LLM judge |
|---|---|---|
| determinism | bit-for-bit: pure functions over JSON, `jq`/`opa` pinned by sha256 in every arm image (`DECISIONS.md` Amendment 43, "jq pinned," and Amendment 45) | **not guaranteed even at temperature 0**: llama.cpp/Ollama batching, thread count, and quantisation kernel choice can change token-level results across hardware, and most model-serving stacks do not guarantee bit-identical output run-to-run on the *same* box, let alone across a different GPU/CPU. Same weights sha does not imply same output sha. |
| falsifiability | proven per Amendment's own falsifiability gate: reference scores 1.0, every planted broken fixture 0.0 **for the right reason at the predicted tier** (`gates/oracle_falsifiability.py`, `docs/gates.md` "oracle-falsifiability"; live on the 13 fixtures §4 collected) | measurable in principle, same shape, but the proof does **not survive a model or prompt change** — a Rego rule is falsified once, forever, until someone edits the `.rego`; a model's pass/fail boundary can shift on the next quantisation, next Ollama release, or next unrelated prompt edit upstream of it, so the gate would need to be re-run per model version, not per policy version |
| three-valued outcome | structural, exit-code-typed: `held`/`contradicted`/`unresolvable` (`generator/tier0_py.py:69-71`, `oracles/rego/README.md` "REFUSAL, not a value") | achievable as a JSON-schema/grammar constraint (§1, not exercised live — §4), but a model can also emit **a syntactically valid `unresolvable` for a fact it could plainly resolve**, or a confident wrong verdict with no error at all — the failure mode the deterministic tiers structurally cannot produce (an `unresolvable` there means jq/opa genuinely could not evaluate, never "chose not to") |
| prompt-injection surface | none — the plan/template JSON is data to a jq filter or Rego query, never instructions to an interpreter | real: the artifact under judgment is agent-written HCL/CFN JSON, and a judge model reads it as **context**, so a comment or string value in the artifact can attempt to steer the verdict the way it could steer an LLM agent — this is the same trap-vocabulary sweep `CLAUDE.md`/Amendment 27 already run on the *agent's* prompt surface, now needed on the *judge's* input too |
| arm neutrality | structural — Amendment 45 exists precisely because cfn-guard's asymmetric expressiveness broke it (`DECISIONS.md:8438-8501`, the iam-managed-policy-exclusive-vs-attachment reversal); Rego now reads both `planned_values`/`configuration` and the CFN template at the same strictness | unverified by default: nothing about a chat model guarantees it reads Terraform plan JSON and CloudFormation template JSON with equal strictness — this would need its own oracle-equivalence CI, mirroring Slice E's Rego-bundle check, before a model verdict could be trusted arm-to-arm |
| latency/cost per verdict | milliseconds; `jq`/`opa` subprocess calls with no network I/O (`generator/verify_py.py` `shell()`/`jq_test()`, pure `subprocess.run`) | not measured live here (§4) — but any LLM decode, even fully local on Metal, is seconds not milliseconds for a multi-hundred-token structured artifact, before any network hop for a remote option |
| pinning | image digest + `jq`/`opa` sha256 pins are already inside `compute_equipping_hash` via the resolved image digest (`gates/equipping.py`) | a model weights sha would need to be a **new** equipping-hash field, the same way `compose_sha256`/`harbor_equipping` were added under Amendment 47 (`DECISIONS.md:8861`, `gates/equipping.py:47`) — nothing in scheme 2 covers "which GGUF file, which quantisation" today |
| "wrong output, no error" | structurally excluded — `Void`/exit-2 paths exist for every unresolvable case (`generator/verify_py.py` docstring, "THREE OUTCOMES, NOT INTERCHANGEABLE") | the single biggest fitness gap: a confidently wrong JSON-valid verdict is indistinguishable, at the schema level, from a correct one, and nothing in this bench's integrity stack (`gates/audit.py`, `gates/emit_result.py`) currently detects it |

**Ranked uses, most to least defensible:**

1. **Authoring aid, no runtime role.** A model proposes candidate
   `structural_asserts`/Rego rules from `oracle.intent`; the existing
   falsifiability gate (`gates/oracle_falsifiability.py`) still proves them
   against the reference and every broken fixture before they ship. Zero
   exposure to determinism/injection/pinning problems — the model never runs
   at grading time.
2. **Red-team: proposing broken-fixture shapes.** Same non-runtime shield —
   every suggestion still has to earn its `predicted_tier_caught` and score
   0.0 for the stated reason before it ships. Useful for scaling
   `docs/design/hcl-modules-spec-matrix.md`-style catch surveys.
3. **Adjudicator of `tier1_not_verifiable` outcomes**, *off the reward path*
   — an advisory annotation beside `metrics/result_schema.json`'s existing
   `tier1_not_verifiable`/`tier1_not_verifiable_detail` fields, never
   replacing them: a bounded, already-three-valued surface where a model
   could flag "looks intentional" vs. "looks like a dodge" without being the
   grader of record.
4. **A tier deciding properties static tiers structurally cannot express**
   (semantic intent, module-default cases per `hcl-modules-spec-matrix.md`
   §2, plan-time-unknown values) — highest-value *if it worked*, and what
   this spike recommends **against** as a gating tier today: it inherits
   every fitness gap above exactly where static tiers admit defeat, i.e.
   where there is no cheap independent check to catch the judge being wrong.

Uses 1-3 add value without changing what "graded" means. Use 4 is the
tempting one and the one this bench's own falsifiability discipline should
block until a model-equivalence CI (a "Slice E for judges") exists.

## 4. Mini experiment — attempted, model-grading half skipped

**Artifact collection ran, and is the real, measured half.**
`gates/artifact_collector.py::collect()` (the same path `make falsifiability`
uses, under `gates/aws_stub.py`, no real AWS calls) produced `hcl_raw`
`plan.json` for the reference solution and every declared broken fixture of
three small specs — `ecs-swappiness` (2 broken), `caller-identity-arn-as-
principal` (4 broken), `apigwv2-route-settings-zero-vs-unset` (4 broken); 13
artifacts, real `terraform init/plan/show` against the vendored provider,
each graded through the corpus's own generated `tests/tiers.py`:

| spec | fixture | reward | seconds |
|---|---|---:|---:|
| ecs-swappiness | reference | 1.0 | 97.2 |
| ecs-swappiness | broken/swappiness-nested-attribute | 0.0 | 85.2 |
| ecs-swappiness | broken/swappiness-requires-maxswap | 0.0 | 82.0 |
| caller-identity-arn-as-principal | reference | 1.0 | 70.2 |
| caller-identity-arn-as-principal | broken/account-root-principal-over-grant | 0.0 | 63.6 |
| caller-identity-arn-as-principal | broken/principal-hardcoded-to-a-foreign-arn | 0.0 | 85.1 |
| caller-identity-arn-as-principal | broken/principal-is-a-role-looked-up-by-name | 0.0 | 72.4 |
| caller-identity-arn-as-principal | broken/sts-session-arn-as-principal | 0.0 | 70.8 |
| apigwv2-route-settings-zero-vs-unset | reference | 1.0 | 65.7 |
| apigwv2-route-settings-zero-vs-unset | broken/burst-limit-left-unset | 0.0 | 51.8 |
| apigwv2-route-settings-zero-vs-unset | broken/integration-targets-a-function-outside-this-plan | 0.0 | 75.1 |
| apigwv2-route-settings-zero-vs-unset | broken/settings-on-the-wrong-stage | 0.0 | 50.4 |
| apigwv2-route-settings-zero-vs-unset | broken/throttle-set-to-zero | 0.0 | 64.8 |

Exactly the deterministic-oracle claim §3 leans on, live: reference held at
1.0, every one of 10 broken fixtures at 0.0, real Terraform plans, freshly
generated this session. `seconds` is the whole `solve.sh` (`terraform init
&& plan && show`), not grading time — the tier-0/1 grade inside it is the
millisecond `jq`/`opa` step §3 already cites.

**The model-grading half could not run — worth recording, not hiding.** This
sandbox's network is throttled to roughly 100 B/s-10 KB/s, measured directly
against three unrelated hosts (`ghcr.io`, `huggingface.co`,
`raw.githubusercontent.com`). At that rate the ~4.7GB Qwen2.5-Coder-7B-
Instruct GGUF selected in §1 would take days, so `ollama pull` and a direct
GGUF download were abandoned mid-transfer; no pre-existing generative GGUF
was found on the host to substitute. Per this spike's own instruction — "if
no model fits the budget, say so and skip" — the live `{verdict, reason}`
grading, its stability repeats, and its latency measurement are **skipped,
not estimated or fabricated**: an environment constraint of this session,
not a finding about any candidate model's fitness.

## Recommendation

Do **not** give a model a gating role in tiers 0/1 today. The bench's own
falsifiability discipline (reference=1.0, every fixture=0.0 **for the
predicted reason at the predicted tier**, reproducible across runs and arms,
`oracles/rego/README.md`'s three-valued contract) is a bar current
model-judges cannot durably clear on determinism, arm-neutrality, or the "no
silent wrong answer" test — before latency and cost are even weighed.

Where a model earns its place, in the ranked order from §3: (1) authoring
aid proposing asserts/Rego the existing gate still falsifies
deterministically, (2) red-team fixture proposals under the same gate, (3)
an advisory adjudicator beside `tier1_not_verifiable`, never replacing it.
(4) — a genuine judging tier for module-default/semantic cases — is the
right long-term target but needs new machinery first, not just a model.

**What an amendment introducing any runtime model role would have to
state**, on the pattern of Amendments 32/42-47:

1. **Isolation**: `[verifier] environment_mode = "separate"` with the model
   sidecar declared only in the verifier's own environment
   (`single_step.py:35-42`'s ordering is the proof obligation), agent's
   environment carrying `allow_internet: false` (`specs/SCHEMA.md §0.2`) —
   otherwise the judge is an oracle the agent can query, a leak not a verifier.
2. **A new equipping-hash channel** for weights sha256 and the verifier-side
   compose/env config, added the way Amendment 47 added `compose_sha256`/
   `harbor_equipping` (`gates/equipping.py:47`, `DECISIONS.md:8861`) — never
   silently folded into `extra_cfg`.
3. **A falsifiability gate scoped to the model**, re-run on every weights or
   prompt change: reference `held`, every broken fixture `contradicted` for
   the stated reason, 3+ repeats, zero verdict flips.
4. **A trap-vocabulary sweep of the judge's own input**, parallel to the
   agent-prompt sweep Amendment 27 already runs.
5. **An oracle-equivalence check across arms**, mirroring Slice E's
   Rego-bundle-vs-`intent.md` check, before claiming equal strictness.
6. **Never sole grader of `reward.txt`.** Advisory/pre-grading only until
   1-5 are met and promoted the way Amendment 46 required live trials first.
