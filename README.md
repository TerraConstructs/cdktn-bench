# cdktn-bench

**Do typed, intent-level IaC constructs beat raw HCL for AI-assisted infrastructure authoring?**

cdktn-bench is a benchmark that measures whether an LLM coding agent (Claude Code, held
constant) authors AWS infrastructure more reliably and more token-efficiently when the
substrate is a strongly-typed L2 construct library versus hand-written Terraform HCL.
The headline metric is **tokens-to-green** (agent *output* tokens, censored, paired with
success-rate-within-budget — `DECISIONS.md` Amendment 23); the oracle is a tiered,
deployment-free stack (compile/synth → structural asserts → plan + policy intent), so
most scenarios cost API tokens and ≈ $0 of AWS spend. On a multi-step scenario the metric
is the **cumulative** sum of per-step output tokens up to the step at which the final
oracle first passes (Amendment 26 §4). Rows from different **scenario forms** —
single-step vs multi-step, greenfield vs brownfield — are never pooled; each is its own
pre-registered stratum with its own census (Amendments 26 §4, 27 §2, 28 §6).

## Authoring arms

| Arm | Substrate | Feedback loop |
|---|---|---|
| `awscdk` | AWS CDK (TypeScript), [`aws-cdk-lib`](https://github.com/aws/aws-cdk) L2 constructs | `tsc` + `cdk synth` |
| `hcl-raw` | Hand-written Terraform HCL, no modules | `terraform validate` + `plan` |
| `terraconstructs` | [terraconstructs](https://github.com/terraconstructs/base) — AWSCDK-style L2s synthesizing Terraform via `cdktn` | `tsc` + `cdktn synth` + `plan` |

`awscdk` and `hcl-raw` are the primary contrast; `terraconstructs` is a
limited-coverage third arm running only scenarios its L2 coverage supports (see
`DECISIONS.md` Amendment 2 — including the dropped `terraform-aws-modules` arm; no
Pulumi, no chant).

Both TypeScript arms run **one uniform toolchain shape: a real emitting `tsc` compile,
then plain `node` on the emitted JS**, with the compile *chained into the synth command*
so an agent can never synthesize stale JS behind a type-broken edit (`DECISIONS.md`
Amendment 25). Keeping the type check inside the agent's iteration loop is not incidental
— it is the steering this benchmark exists to measure, which is why every transpile-only
runner was measured and rejected.

Each scenario embeds **planted catches** (invalid enum values, deeply-nested attribute
placement, cross-resource dependency edges, and anti-L2 catches the type system *cannot*
see) and records, per arm, **at which oracle tier each catch is caught** — relocating
failure to a cheaper tier is the mechanism under test.

## How it works

- Built on **[aws-bench](https://github.com/aws-bench/aws-bench)** (Amazon's
  Harbor-based agent-evaluation runner) with a dataset following the
  **[aws-bench-datasets](https://github.com/aws-bench/aws-bench-datasets)** task format.
- One YAML **intent spec** per scenario (`specs/`) is expanded by a generator into
  per-arm task directories with structurally-enforced prompt parity (identical
  natural-language instruction; only the target-language line differs).
- Every scenario ships a natural-language intent implemented **twice at equal
  strictness** — Rego/OPA over `terraform show -json` for the TF arms, and over the
  synthesized CloudFormation for the CDK arm either cfn-guard (the default) or, when
  the intent needs a cross-resource join cfn-guard cannot express, the same Rego/OPA
  engine (`oracle.awscdk_tier1_engine`, `specs/SCHEMA.md` §4.5) — cross-checked against
  reference solutions and negative fixtures (`make grading-proof`: correct ⇒ 1.0, planted-bug ⇒
  0.0, on every arm).
- **Integrity gates** make results hard to game: a toolchain preflight per arm image, a
  trajectory audit proving the agent actually ran the substrate's toolchain, validity
  classes that refuse to score infrastructure failures or tool-bypass runs, and an
  equipping hash (instruction + skills/MCP config + image digest) stamped into every
  result row.
- **Multi-step scenarios** (`specs/SCHEMA.md` §2.6; `DECISIONS.md` Amendments 26/27): a
  scenario may decompose into N prompts delivered to N **fresh agent sessions**, so a
  day-2 change is measured *without foreknowledge of it at day 1* — the condition a real
  day-2 change actually has. State carries through the workspace, not through
  conversation; each step is verified by its own oracle behind a hard `min_reward` gate;
  and the no-foreshadowing rule is enforced against **both** prompt surfaces — the step-1
  instruction and everything under `environment/`, which the arm Dockerfile copies into
  the agent image. Trials run through `cdktn-bench`, this repo's superset of the upstream
  runner (same flags; a stepless task takes the untouched single-step path).
- **Brownfield scenarios** (`specs/SCHEMA.md` §2.7; Amendment 28, draft): a scenario may
  ship a working, plan-green, already-deployed configuration as its starting workspace
  instead of an empty skeleton, and ask for one ordinary change to it — measuring
  tokens-to-green on *a change to code the agent did not write*, which is where the
  interesting traps actually fire. The three arms' starting configurations are proved
  equivalent by declared behavioural facts, never by resource census (`make seed-parity`),
  every such scenario must prove that doing nothing scores less than full marks, and an
  optional live **idempotence** tier asks whether the agent's own toolchain reports a
  converged state after the change (gating, fail-closed, and skipped-with-a-reason rather
  than fake-passed when it cannot run).
- A **Tier 0.5** oracle evaluates embedded JSONata `{% ... %}` expressions in Step
  Functions ASL against real sample inputs — the catch class that sails through every
  compiler and synth step on every arm alike.
- Adding a new scenario or task variant? See
  [`docs/adding-scenarios.md`](docs/adding-scenarios.md) — spec authoring, agent-role
  selection, read-only vs. mutating, oracle authoring, and the reference-solution/
  grading-proof/holdout-split requirements, in one practical walkthrough.

## Inspiration & prior work

- The locked experimental design lives in
  [`docs/prereg-iac-abstraction-benchmark.md`](docs/prereg-iac-abstraction-benchmark.md)
  — hypotheses, arms, oracle tiers, metrics, censoring rules, and the amendment-log
  discipline this repo's `DECISIONS.md` continues.
- **IaC-Eval** (Kon et al., NeurIPS 2024) — the two-phase no-deploy oracle (compile +
  Rego intent on the resource graph) this benchmark's Tier 1 reuses; **IaCGen** for
  iterations-to-green; **Multi-IaC-Eval** for CFN-vs-TF backend parity evidence;
  **TerraFormer** for the HCL data-scarcity results.
- **[aws-bench](https://github.com/aws-bench/aws-bench)** /
  **[aws-bench-datasets](https://github.com/aws-bench/aws-bench-datasets)** — the runner
  and task format this repo builds on.
- **[lex00/aws-bench](https://github.com/lex00/aws-bench)** — a fork whose three-gate
  integrity pattern (preflight / audit / refuse-invalid-results) directly inspired this
  repo's `gates/`; its recorded lesson — trials scored for a toolchain the agent never
  invoked — is the reason the audit gate exists.
- **[AWS CDK](https://github.com/aws/aws-cdk)** and
  **[terraconstructs/base](https://github.com/terraconstructs/base)** — the L2 construct
  libraries whose typed-enum, nested-shape, and deterministic-redeployment semantics
  provide the planted catches (see
  [`docs/apigw-redeploy-mechanics.md`](docs/apigw-redeploy-mechanics.md)).

## Repo layout

| Path | Purpose |
| --- | --- |
| `specs/` | Intent specs (one YAML per scenario) + `SCHEMA.md`, source of truth for the generator |
| `generator/` | Intent-spec → task-dirs expander, parity + reference-path checks |
| `arms/{awscdk,hcl-raw,terraconstructs}/` | Per-arm agent container images (pinned toolchains, offline preflights) |
| `scenarios/anchor/` | Near-empty scenario satisfying aws-bench's real-AWS-account precondition |
| `tasks/` | Generated `<scenario>-<arm>` task directories (never hand-edited; `make gen`) |
| `oracles/{rego,rego-cfn,cfn-guard}/` | Static oracle policies (plan-shaped Rego, CFN-shaped Rego, cfn-guard) + structural / Tier-0.5 libraries |
| `cdktn_bench/` | The `cdktn-bench` runner — a superset of upstream aws-bench by inheritance, adding multi-step trials; nothing upstream is vendored or modified |
| `gates/` | preflight / trajectory-audit / result-validity / equipping-hash / falsifiability gates |
| `metrics/` | Result schema, validation, tokens-to-green + tier-attribution aggregation |
| `ci/` | Oracle-equivalence CI + drift checks |
| `docs/` | Pre-registration, mechanics notes, [`adding-scenarios.md`](docs/adding-scenarios.md) (how to add a scenario/task) |
| `DECISIONS.md` | Append-only amendment log (pre-registration discipline) |

## Setup

```bash
make setup       # uv sync (installs the pinned aws-bench runner + this repo's
                 #          own `cdktn-bench` CLI, a superset that adds multi-step
                 #          trials — DECISIONS.md Amendments 26/27)
make build-arms  # docker build each arm's environment/Dockerfile
make preflight   # confirm each arm's toolchain works offline in its container
make check       # schema checks, gate tests, drift checks
```

See `DECISIONS.md` for the aws-bench pin, packaging notes, and the full amendment log.

## Status

Work in progress. Phase 0 (runner substrate + integrity rails) and Phase 1 (generator +
seed scenarios, each proven end-to-end gradeable) are built, along with CI consolidation
and the train/holdout split. The first live single-step trials have run green on all
three arms (`docs/live-results.md`, pilot data, n=1 per arm — directional only).

The multi-step and brownfield forms are **pre-registered but still DRAFT**: both are
built, generated and offline-proven, and each is promoted out of draft by its first live
run, which is the first thing that can falsify it (Amendments 26/27 and 28). No
multi-step or brownfield result may be published while they are. No benchmark results are
published yet — when they are, every trajectory, prompt, oracle spec, and equipping hash
ships with them.

## Provenance

Authored with Claude Code (Sonnet implementation workflows, Opus verification
workflows), directed and reviewed by [@so0k](https://github.com/so0k). Disclosure: the
terraconstructs library compared in one arm is maintained by the same author — noted
here and in `arms/terraconstructs/README.md`, and controlled for in the design
(symmetric equipping, oracle equivalence, integrity gates).
