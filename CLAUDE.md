# cdktn-bench — working notes for agents

Repo-specific guidance. See `README.md` for what the benchmark is, `DECISIONS.md`
for the append-only amendment log (the pre-registration discipline), and
`docs/adding-scenarios.md` for how to add a scenario.

## Turn budget (monitor & trim)

`scripts/run-bench.sh` sets `MAX_ITERS` → Claude Code's `--max-turns`. **Default is
`100`** (raised from 8 on 2026-08-13, Amendment 22).

- `--max-turns` counts **agent steps**, not the pre-registration's feedback
  **cycles**. One cycle (author → deploy → read error → amend) is many steps;
  a live scenario's steps include minutes-long `terraform apply` / `cdk deploy`.
  8 was far too tight — the first live trial hit `error_max_turns` at 8.
- `MAX_TOKENS` (pilot-set, currently unset) is the **real censoring budget**.
  `--max-turns` is a runaway backstop, not the headline cap.
- **Monitor:** after runs, check `agent_result` / trajectory `num_turns` per
  scenario. If a scenario reliably finishes well under 100, **trim toward 50**
  (start large, tighten with evidence — don't guess low). Static scenarios need
  far fewer turns than live ones; consider a per-scenario override before a
  blanket cut.
- Override per run: `MAX_ITERS=<n> ./scripts/run-bench.sh …` or `--max-iters <n>`.

## Multi-step scenarios (quick reference)

- The runner is **`cdktn-bench`**, not `aws-bench` (`scripts/run-bench.sh`
  execs it; Amendment 27). Superset CLI — same flags — whose only difference is
  that a `task.toml` declaring `[[steps]]` builds a `CdktnMultiStepTrial`
  instead of hitting upstream's `NotImplementedError`. Stepless tasks take the
  untouched single-step path.
- A scenario decomposes into steps via a spec-level `steps:` list
  (`specs/SCHEMA.md` §2.6). **The rule: a step-1 prompt must contain no hint of
  step 2's intent** — no "then modify", no route/arg the later step introduces,
  not even in a per-arm `language_line`. See
  `docs/prompt-decomposition-audit.md`; the deny-list is enforced by
  `generator/tests/test_multistep_emission.py`.
- **The rule has two surfaces, not one.** `environment/` is `COPY`'d into the
  agent image, so the skeleton files are prompt surface too. A multi-step spec
  must declare `workspace_title` (`specs/SCHEMA.md` §0.1) — a step-1-safe
  header — because the scenario `title` describes the whole arc and used to be
  stamped into the agent's own `main.tf` line 1 (Amendment 27 §5.1).
- Every step's oracle lives in `steps/<name>/tests/`. The **shared root
  `tests/` must stay oracle-free** (Harbor uploads it at every step's
  verification, so step-specific material there is readable in a later step's
  agent phase). A multi-step task has **no root `instruction.md`**.
- `apigw-redeploy` is multi-step. Its single-step results (2026-08-13,
  `docs/live-results.md`) are a **different scenario form** and must never be
  pooled with multi-step-form results (Amendment 27 §2).

## Brownfield / poisoned workspaces (quick reference)

- A spec with a `workspace_seed` block (`specs/SCHEMA.md` §2.7, DECISIONS.md
  Amendment 28) is **brownfield**: its `entry_file` ships hand-authored,
  plan-green, already-deployed config instead of §2.4's empty skeleton, and the
  prompt is a change request against it. `named-resource-replacement` is the
  only one.
- **A brownfield spec must declare `workspace_title` too** (`SCHEMA.md` §0.1) —
  the *same* requirement as multi-step, for the same reason. A brownfield
  `title` names the change and usually the trapped property with it; stamped
  into `bin/app.ts`/`main.ts` it leaked on two arms and not on the third, whose
  entry file IS the seed. Header must say only what the workspace already *is*
  ("Internal services network"). Scanned as emitted bytes by
  `test_workspace_seed.py::TestBrownfieldPromptSurface`.
- **Read every byte the Dockerfile COPYs, not just the files you wrote.** The
  leak above survived a hostile self-check scoped to "the seed and the
  instruction" (Amendment 28 §3 rule 7).
- **The seed is prompt surface** — same rule, same reason as the skeleton header
  (Amendment 27 §5.1). No `TODO`/`NOTE:`/`careful`, no generator banner, and
  above all no comment naming the mechanism that fixes the trap. Tripwired by
  `spec_model._seed_comment_violations`; the real rule is review-time.
- The seed is **writable** (`0o644`) — it is the file the agent is asked to
  change. `seeded_files` (§2.5) are the opposite: `0o444` reference inputs.
- `make seed-parity SPEC=…` runs the real toolchain against the generated,
  **un-overlaid** workspace on every arm and resolves `seed_asserts` against
  what it produces. Equivalence = declared behavioural facts + seed-plans-green,
  explicitly **not** resource-count parity. Wired per spec into `make ci`.
- **Brownfield tokens-to-green is a separate stratum** — never pooled with
  greenfield rows (Amendment 28 §6, extending Amendments 23/26/27).
- `NODE_OPTIONS` is set in some shells and breaks `npm ci` inside the gates —
  run the toolchain gates as `env -u NODE_OPTIONS uv run python …` if `npm ci`
  dies with `Cannot find module '…/restore-node-options.cjs'`.

## Live runs (quick reference)

- Credentials: `aws-vault exec --no-session tcons-mgmt -- …` (management account;
  the runner assumes `OrganizationAccountAccessRole` into the dedicated account
  `886312446417`). Keychain may prompt — an operator must unlock it.
- The `aws` CLI is run via **mise**, never brew: `mise x aws@latest -- aws …`.
- colima needs `TMPDIR=$HOME/.awsbench-tmp` (bind mounts under `/var/folders`
  aren't shared into the VM); the `docker compose` plugin must be installed.
- Task filters match the **task directory basename** (`--include-task-name
  apigw-redeploy-hcl-raw`), not the registry `name` or `task.toml` name.
- Mutating tasks trigger the framework reset (~8.5 min) automatically — do **not**
  hand-write teardown (Amendments 17/18); `scenarios/anchor/reset/reset.sh` was
  removed as redundant.
- After changing anything under `scenarios/anchor/**`, re-run `env setup` or
  resets fail with a scenario-source-hash mismatch.
- Mutating scenarios run the agent as **`QALocalInvocationApplicationAdmin`**
  (`AdministratorAccess`) — aws-bench's own mutation-task model (Amendment 24).
  Both arms deploy with equal (admin) authority: hcl-raw via terraform, awscdk
  via the standard `cdk deploy` bootstrap path (admin can assume `cdk-hnb659fds-*`).
  Safety is the disposable account + region/role-protection SCPs + reset, not
  narrow IAM. The old bespoke `QADeployApplicationRole` is retired; do **not**
  reintroduce a per-scenario scoped deploy role (it causes fake agent failures
  and breaks arm parity — see Amendment 24).

## Never

- Write AWS credentials to a file, or run boto/botocore at DEBUG (leaks session
  tokens to logs). Pipe assume-role output directly into the process env.
- Touch account `694710432912` (production website) or mutate `489592802338`.
- Hand-edit generated `tasks/**` — regenerate with `make gen` / `make gen-all`.
  The only hand-authored files under a task dir are `solution/**/solve.sh` and
  (when the spec declares `hand_authored`) `tests/live_check.py` — including
  their per-step `steps/<name>/…` equivalents. The generator is
  destructive-safe for exactly those and will hard-error rather than delete
  hand-authored content it finds somewhere it must not be.
  **One documented exception:** for a `workspace_seed` spec,
  `solution/broken/seed-unchanged/solve.sh` is **generator-owned** and is
  overwritten on every run (SCHEMA.md §2.7 / Amendment 28 §5). Its content is
  entirely mechanical — it writes nothing — and the one negative whose purpose
  is to be un-weakenable must not be hand-editable into a passing no-op.
