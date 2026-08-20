# local-registry.json

`registry.json`-shaped file (schema: `AwsBenchDatasetSpec` in
`aws_bench/dataset/registry.py`, exactly `[{name, version, description, scenarios[], tasks[]}]`)
describing one dataset, `cdktn-bench-anchor@0.1.0`: the anchor scenario plus its one
dummy smoke task. Kept as a **separate markdown file** rather than inline JSON comments
because `AwsBenchRegistry.from_path` parses the file as a strict `list[AwsBenchDatasetSpec]`
— every element of the top-level array must validate as a dataset spec, so there is no
comment-carrying slot inside `local-registry.json` itself (see "Format uncertainties"
below).

## CLI invocations this file is meant to be consumed with

Run from the **repository root** (this repo's checkout) — see the path-
resolution caveat below for why this matters. No AWS credentials, Docker, or network
access are exercised by any command in this document; none of them were run as part of
authoring this file.

```bash
# One-time: install the pinned aws-bench runner AND this repo's own extended CLI
# (already done for this repo; see DECISIONS.md).
#
# `cdktn-bench` is a strict SUPERSET of `aws-bench` (DECISIONS.md Amendments
# 26/27): same flags, same `env` commands, plus multi-step tasks instead of
# NotImplementedError. `scripts/run-bench.sh` execs it. The `env init/setup/
# cleanup` commands below are byte-identical under either name -- they are the
# same Typer app object -- and are left as `aws-bench` here only because that
# is what the upstream guide they cite calls them.
uv sync

# 1. env init — provisions/maps the anchor scenario onto a real AWS Organizations
#    member account under the given OU ("--env-name"). Hard-requires AWS credentials
#    for a management account (docs/aws-bench-guide.md §4) — NOT run as part of this
#    deliverable.
uv run aws-bench env init --env-name cdktn-anchor \
  --registry-path ./local-registry.json -d cdktn-bench-anchor@0.1.0 \
  --wait-for-quotas

# 2. env setup — deploys scenarios/anchor's CDK app (QARolesStack + AnchorStack) into
#    that account via scenario/Dockerfile + deploy/deploy.sh.
uv run aws-bench env setup --env-name cdktn-anchor \
  --registry-path ./local-registry.json -d cdktn-bench-anchor@0.1.0

# 3. run — one trial of tasks/anchor/smoke against the deployed anchor scenario.
#    `cdktn-bench`, not `aws-bench`: a task.toml declaring [[steps]] (today only
#    apigw-redeploy) is REFUSED outright by upstream's AwsBenchTrial.create.
uv run cdktn-bench run --env-name cdktn-anchor \
  --registry-path ./local-registry.json -d cdktn-bench-anchor@0.1.0 \
  -a claude-code -m global.anthropic.claude-sonnet-5 \
  -l 1 --yes

# 4. env cleanup — tears the scenario account back down (scenario/cleanup/cleanup.sh +
#    framework sweeper).
uv run aws-bench env cleanup --env-name cdktn-anchor \
  --registry-path ./local-registry.json -d cdktn-bench-anchor@0.1.0
```

### Equivalent local-path form (no registry file at all)

`docs/aws-bench-guide.md` §4 documents a registry-free local mode; it works identically
for this scenario/task pair and needs no `local-registry.json`:

```bash
uv run cdktn-bench run --env-name cdktn-anchor \
  --scenario-path ./scenarios --path ./tasks/anchor \
  -a claude-code -m global.anthropic.claude-sonnet-5 \
  -l 1 --yes
```

Note the `--path` caveat from the guide: it does **not** recurse, so it must point at a
directory whose *immediate* children are task dirs — `./tasks/anchor` (whose only child
is `smoke/`), not `./tasks`.

## Format uncertainties for the verifier to check

1. **Local registry paths resolve relative to the process CWD, not to
   `local-registry.json`'s own location.** Traced through
   `RegistryScenarioId.to_source_id()` / `RegistryTaskId.to_source_task_id()` (no
   `git_url` → `LocalScenarioId(path=...)` / `LocalTaskId(path=...)`,
   `aws_bench/dataset/source_ids.py`) into Harbor's `LocalTaskId` (
   `harbor/models/task/id.py`), whose `get_local_path()` is
   `self.path.expanduser().resolve()` — `Path.resolve()` on a relative path resolves
   against `Path.cwd()`, with no reference back to the registry file's directory
   anywhere in that chain. This file's `scenarios[].path` / `tasks[].path` are therefore
   written relative to the **repo root**, and the CLI invocations above are only correct
   when run from there (or with `local-registry.json`'s paths rewritten to absolute paths).
   This differs from how `--path` / `--scenario-path` behave (those are resolved directly
   from the flag value, so relative-to-CWD is the same rule but at least applies
   uniformly) — worth an explicit regression test before this file is relied on from a
   CI working directory other than the repo root.
2. **`RegistryValidator` never checks that a local `path` exists on disk at load time**
   (`_check_semver_versions` / `_check_unique_*_names_per_dataset` /
   `_warn_cross_dataset_scenario_consistency` are the only load-time checks in
   `aws_bench/dataset/registry.py`) — a typo in `path` would surface only at
   `env init` / `run` time as a `ScenarioDiscoveryError` / `TaskConfigInvalidError`, not
   at registry-load time. Not exercised here since no `aws-bench` command was run.
3. **Registry `tasks[].name` / `scenarios[].name` are not required to match the
   corresponding `task.toml [task].name` / `scenario.toml [scenario].name`** — they're
   independent identifiers (registry-level dedup and `--include/--exclude-*-names`
   filtering only). Chosen here to be human-readable (`"anchor-smoke"`) rather than
   mirroring `task.toml`'s `"cdktn-smoke/anchor-write-file"`; flagging in case the
   verifier expected byte-identical names.
4. **`tests/test.sh`'s reward is intentionally unconditional (`1.0` regardless of
   whether the agent's output matched)** — this is a literal reading of "stub verifier
   writing reward 1.0", chosen because Slice B's audit gate doesn't exist yet to
   distinguish "informationally checked and logged" from "the score depends on it". If
   the intent was instead a real (if trivial) pass/fail check, flip the unconditional
   `echo "1.0"` to branch on the existing string-match logic already in the script.
5. **No `env/verify/verify.sh` was written** for the anchor scenario (optional per
   `scenario.toml [verify]`, and `ec2-multiregion` is the only upstream scenario that has
   one). If Slice F's live validation wants a scene-state assertion beyond "the stack
   deployed", one should be added there.

## Slice F operational notes (2026-08-06, verified live)

The end-to-end smoke run succeeded: reward 1.0, 57s, tokens captured
(n_input_tokens/n_output_tokens/n_cache_tokens/cost_usd in `result.json`,
full `agent/trajectory.json` persisted). Operational lessons for the next run:

- **Task filters match directory basenames**, not registry `name` fields:
  `--include-task-name smoke` (Harbor `LocalTaskId.get_name()`), NOT
  `anchor-smoke` and NOT the task.toml `[task].name`.
- **colima**: bind-mount sources under `/var/folders` are not shared into the
  VM — run the CLI with `TMPDIR=$HOME/.awsbench-tmp` (or another home-dir
  path). The `docker compose` CLI plugin is not bundled: `brew install
  docker-compose` + symlink into `~/.docker/cli-plugins/`.
- **Memory**: the scenario deploy container OOM-killed `tsc`/`ts-node` at
  2048 MB (exit 137); `scenario.toml [environment]` now sets 4096 MB / 2 cpus.
  Root cause since removed as well as headroomed: `cdk_app/cdk.json`'s app
  command was `npx ts-node lib/app.ts` (1.7 GB tree RSS, an in-process
  type-check inside the synth process) and is now `node dist/lib/app.js` on
  JS precompiled at image build (~0.87 GB) — `docs/ts7-spike-results.md`,
  `docs/ts-runtime-spike2-results.md`. The 4096 MB floor stays (the
  terraconstructs arm still needs it).
- **SCP side effect**: `env setup` creates and attaches an
  `awsbench-region-restrict-<scenario>` SCP (deny non-us-east-1, global
  services exempted) to the scenario account and re-creates it each setup.
  On a shared/personal account this restricts unrelated regional work —
  detach/delete after runs, or use a dedicated benchmark account.
