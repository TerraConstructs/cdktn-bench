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
