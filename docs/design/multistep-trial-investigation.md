# Multi-step trials in cdktn-bench — architecture investigation

> ## ⚠ HISTORICAL DESIGN RECORD — NOT THE CONTRACT
>
> **This memo has LANDED and is superseded as an authority.** It is kept as the
> investigation record — the evidence trail for *why* the architecture is what
> it is — not as the specification of what shipped.
>
> **Where the authority now lives** (these win wherever they disagree with
> anything below):
>
> | For | Read |
> |---|---|
> | multi-step trial semantics (fresh session per step, who deploys, `min_reward`, reward strategy `final`, cumulative tokens-to-green, trial-level censoring) | `DECISIONS.md` **Amendment 26** *(DRAFT until the first live multi-step run)* |
> | the scenario-form change, the no-foreshadowing decomposition, and the `environment/` leak fixed at the schema | `DECISIONS.md` **Amendment 27** |
> | the spec surface (`steps:`, `workspace_title`) and the generated task layout | `specs/SCHEMA.md` **§2.6, §8.3, §0.1** |
> | the audit this motivated | `docs/prompt-decomposition-audit.md` |
>
> **Known deltas between this memo and what shipped**, beyond ordinary detail:
>
> - §5's task-directory rules shipped **enforced**, not merely stated. The memo
>   described rule 2 ("never place later-step material in `environment/`") as
>   prose, and it was violated anyway by a generator-stamped header — the fix
>   was a new required spec field, `workspace_title`, plus a deny-list scan over
>   every emitted byte under `environment/` (Amendment 27 §5.1). The
>   generalised rule the memo does not carry: **the unit that must be read
>   hostilely is every byte the Dockerfile `COPY`s, not the files the author
>   happened to write.**
> - The memo is silent on scoring strategy; `final` (not Harbor's `mean`
>   default) is the registered choice, and it is written into `task.toml`
>   rather than left to a code default (Amendments 26 §3, 27 §5).
> - Non-final steps acquired an obligation the memo does not mention: each
>   needs its own reference `solve.sh` proving its subset oracle is
>   *satisfiable* (Amendment 27 §6).
> - Two shipped consequences the memo could not know are recorded as Amendment
>   26's draft addendum: the per-step `pre_invoke` inherits a single
>   **task-level** timeout, and a step with no trajectory makes the whole
>   trial's `n_llm_calls` null (turn-censoring blindness).
>
> Everything below is preserved as written on 2026-08-20.

**Status *(as written)*:** investigation memo, not yet a decision. Draft for operator review.
**Date:** 2026-08-20
**Scope:** how to run `workspace → prompt#1 → agent → harness apply/mutate → prompt#2 → agent → final eval`
on the aws-bench/Harbor stack, *extending* `aws_bench` rather than wrapping it.

---

## 0. Headline

**Harbor 0.9.0 already ships a complete `MultiStepTrial`.** It is not a stub: it does
per-step instruction delivery, per-step workdir seeding, per-step setup scripts, per-step
verification, per-step *token accounting*, a per-step green gate (`min_reward`), per-step
artifact/log archiving, and trial-level reward aggregation. Harbor's own
`Trial.create` already dispatches to it automatically when a task declares `[[steps]]`.

The only thing standing between cdktn-bench and multi-step trials is **five lines of
aws-bench**:

```python
# /Users/vincentsmet/cdk/aws-bench/aws_bench/task/aws_trial.py:443-448
task = await AwsBenchTask.from_config(config.task, config.extra_instruction_paths)
if task.has_steps:
    raise NotImplementedError(
        "multi-step AWS tasks are not yet supported (per-step pre/post-invoke "
        "credentialing is undefined)."
    )
```

So the work is **not** "build multi-step". It is: *re-point aws-bench's AWS behaviours
(credential staging, placeholder substitution, scenario gating, account reset) onto
Harbor's existing `MultiStepTrial`, and answer the per-step credentialing question that
aws-bench explicitly left open.* That is a genuinely small, inheritance-shaped change —
which is exactly what the operator's mandate asks for.

Path conventions used below:

- `HARBOR` = `/Users/vincentsmet/cdk/aws-bench/.venv/lib/python3.14/site-packages/harbor`
- `AWSB`   = `/Users/vincentsmet/cdk/aws-bench/aws_bench`
- `CDKTN`  = `/Users/vincentsmet/cdk/cdktn-bench`

---

## 1. Architecture map — CLI entry to trial completion

### 1.1 Call chain (single-step, today)

| # | Hop | File:line |
|---|---|---|
| 1 | console_script `aws-bench = aws_bench.cli.main:app` | `/Users/vincentsmet/cdk/aws-bench/pyproject.toml:36-37` |
| 2 | Typer root app; `run` is an alias for `job start` | `AWSB/cli/main.py:16-23`, `:110` |
| 3 | `start()` — ~500 lines of flag parsing → `AwsBenchJobConfig` | `AWSB/cli/jobs.py:562-742` |
| 4 | `AwsBenchJob.create(config)` — resolves tasks, scenarios, accounts, CFN exports | `AWSB/cli/jobs.py:760` → `AWSB/task/job.py:122-185` |
| 5 | `AwsBenchJob.__init__` swaps Harbor's queue for the aws-bench one | `AWSB/task/job.py:84-88` |
| 6 | `_init_trial_configs` → `_build_trial_config` → `AwsBenchTrialConfig` (per attempt × task × agent) | `AWSB/task/job.py:295-302`, `:232-293` |
| 7 | `job.run()` → `Job.run` → `self._trial_queue.submit_batch(...)` | `AWSB/cli/jobs.py:809`; `HARBOR/job.py:858` |
| 8 | `AwsBenchTrialQueue._run_trial` — per-scenario readers/writer gate, then global semaphore | `AWSB/task/queue.py:100-117` |
| 9 | **`_execute_trial_with_retries` → `AwsBenchTrial.create(trial_config)`** ← the dispatch point | `AWSB/task/queue.py:119-151`, **`:122`** |
| 10 | `AwsBenchTrial.create` — loads `AwsBenchTask`, **refuses `has_steps`**, returns `AwsBenchSingleStepTrial` | `AWSB/task/aws_trial.py:437-449` |
| 11 | `Trial.__init__` — paths, logger, timeouts, agent, environment, artifact handler | `HARBOR/trial/trial.py:57-93` |
| 12 | `Trial.run` — `_init_result` → emit START → `_prepare` → `_run` → `_finalize` | `HARBOR/trial/trial.py:155-176` |
| 13 | `AwsBenchSingleStepTrial.run` wraps it: log context + post-run account reset | `AWSB/task/aws_trial.py:103-116`, `:118-146` |
| 14 | `SingleStepTrial._run` — agent → upload logs → artifacts → verifier | `HARBOR/trial/single_step.py:30-43` |
| 15 | `Trial._finalize` — stop env, write `result.json`, emit END | `HARBOR/trial/trial.py:194-198` |

### 1.2 Who reads the task dir

`Task.__init__` (`HARBOR/models/task/task.py:51-78`) reads `task.toml` and `instruction.md`
**host-side, at construction**. `AwsBenchTask` (`AWSB/dataset/task_config.py:93-118`)
re-parses the same `task.toml` as its own subtype to pick up `[scenario]`, `[concurrency]`,
`[pre_invoke]`, `[post_invoke]`, then runs `_validate_layout` (`:178-202`).

Notably: `TaskPaths` already knows the multi-step layout — `steps_dir`, `step_dir`,
`step_instruction_path`, `step_tests_dir`, `step_solution_dir`
(`HARBOR/models/task/paths.py:140-189`). And `Task._validate_tests` already has a full
steps branch (`HARBOR/models/task/task.py:143-170`).

### 1.3 Who delivers the prompt, and how

The instruction is **argv text on a `docker exec`, never a file the agent reads**:

1. `Task.instruction` is read from `instruction.md` at construction
   (`HARBOR/models/task/task.py:76-78`). For a steps task it is set to `""` (`:73-74`).
2. `SingleStepTrial._run_agent` passes `self.task.instruction`
   (`HARBOR/trial/single_step.py:65`); `MultiStepTrial._run_step_agent` passes
   `self.task.step_instruction(step.name)` (`HARBOR/trial/multi_step.py:112`), which reads
   `steps/<name>/instruction.md` on demand (`HARBOR/models/task/task.py:188-192`).
3. `Trial._run_agent_phase` (`HARBOR/trial/trial.py:223-251`) calls
   `self.agent.run(instruction=..., environment=..., context=target.agent_result)`.
4. aws-bench intercepts that (`AWSB/task/aws_trial.py:323-364`) to substitute
   `{{placeholders}}` and stage `~/.aws/credentials` in-container for the agent role.
5. `ClaudeCode.run` (`HARBOR/agents/installed/claude_code.py:1015-1155`) shell-quotes the
   instruction (`:1019`) and execs:

```text
claude --verbose --output-format=stream-json --permission-mode=bypassPermissions \
       <extra flags> --print -- <escaped_instruction> 2>&1 </dev/null | tee /logs/agent/claude-code.txt
```
(`HARBOR/agents/installed/claude_code.py:1144-1155`)

**So the agent runner is a one-shot headless CLI invoked via `docker exec` — not an API
loop and not a long-lived session.** cdktn-bench runs `aws_bench.agents.claude_code.ClaudeCode`
(`AWSB/agents/claude_code.py:31`), a thin subclass that only adds plugin installation.

### 1.4 Where the transcript and token accounting live

- `CLAUDE_CONFIG_DIR` is set to `/logs/agent/sessions`
  (`HARBOR/agents/installed/claude_code.py:1113`), which is a **bind mount of the host
  `TrialPaths.agent_dir`** (`HARBOR/trial/trial.py:687-690`; the docker environment
  declares `mounted=True` at `HARBOR/environments/docker/docker.py:206`).
- After each agent phase, `Trial._sync_agent_output` → `_populate_agent_context`
  (`HARBOR/trial/trial.py:424-432`) calls `ClaudeCode.populate_context_post_run`
  (`HARBOR/agents/installed/claude_code.py:913-947`), which parses the session JSONL into
  an ATIF `Trajectory`, writes `<logs_dir>/trajectory.json`, and fills
  `AgentContext.n_input_tokens / n_cache_tokens / n_output_tokens / cost_usd`.
- In single-step that context lands on `TrialResult.agent_result`; in multi-step it lands
  on `StepResult.agent_result` (`HARBOR/models/trial/result.py:60-66`, `:79`, `:88`).
- `TrialResult.compute_token_cost_totals` (`HARBOR/models/trial/result.py:90-129`) already
  branches: top-level context if present, else sum across `step_results[].agent_result`.
- cdktn-bench's `gates/emit_result.py` **already mirrors that branch**:
  `_aggregate_step_tokens` (`CDKTN/gates/emit_result.py:420-447`) and its caller
  `_extract_score_fields` (`:450-497`), with a regression test at
  `CDKTN/gates/tests/test_emit_result.py:399`.

### 1.5 Where verification runs

`Trial._run_shared_verifier` (`HARBOR/trial/trial.py:285-304`) builds a `Verifier` via
`VerifierFactory` and runs `tests/test.sh` inside the agent container, reading
`/logs/verifier/reward.{txt,json}`. aws-bench wraps it to overlay verifier credentials
(`AWSB/task/aws_trial.py:366-388`). `AwsBenchTask._validate_layout`
(`AWSB/dataset/task_config.py:196-202`) **bans separate-environment verifiers** because
the phase scripts run in the agent container.

The verifier resolves its test sources step-aware already:
`Verifier._resolve_tests` (`HARBOR/verifier/verifier.py:100-128`) uploads the shared
`tests/` **and** `steps/<name>/tests/` when `step_name` is set.

### 1.6 Where account reset hooks in

Two layers:

1. **Per-trial `post_invoke`** — runs inside `_stop_agent_environment`
   (`AWSB/task/aws_trial.py:400-434`) via `ScriptRunner`, with staged post-invoke-role creds.
2. **Full scenario reset** — `AwsBenchSingleStepTrial.run` (`AWSB/task/aws_trial.py:103-116`)
   calls `_reset_scenario_account` (`:118-146`) after any `MUTATING` trial, which runs
   `ScenarioTrial.create(...).run(ScenarioPhase.RESET)` (`AWSB/scenario/events.py:12-25`).
   The scenario admission gate is held across this (`AWSB/task/queue.py:116`), so the next
   trial on that account waits.

### 1.7 What Harbor's `MultiStepTrial` already does

`HARBOR/trial/multi_step.py`:

| Capability | Line |
|---|---|
| `class MultiStepTrial(Trial)`; refuses a task without `[[steps]]` | `:18-29` |
| `_run` — iterate `task.config.steps`, one `StepResult` each, then aggregate reward | `:31-53` |
| `_run_step` — dirs → prepare → agent → upload logs → artifacts → verify → archive | `:59-93` |
| `_prepare_step` — reset agent logs, upload `steps/<n>/workdir/`, run `setup.sh`, healthcheck | `:95-102`, `:283-318` |
| `_run_step_agent` — `_run_agent_phase(target=step_result, instruction=task.step_instruction(...))` | `:104-119` |
| `_run_step_verifier` — per-step verifier, shared or separate env | `:121-160` |
| **Green gate** — `_should_stop_after_step` aborts remaining steps on `min_reward` miss | `:162-192` |
| Trial reward — `mean` (per-key means across steps) or `final` | `:194-228` |
| Per-step archiving — moves `agent/`, `verifier/`, `artifacts/` into `steps/<n>/` | `:334-343` |
| Per-step timeouts / users | `:345-381` |

Config surface: `StepConfig` (`HARBOR/models/task/config.py:370-396`) has `name`,
`agent`, `verifier`, `min_reward`, `healthcheck`, `artifacts`.
`TaskConfig.steps` and `multi_step_reward_strategy` at `:418-430`.
Per-step output dirs at `HARBOR/models/trial/paths.py:242-264`.

And the base dispatcher already knows:

```python
# HARBOR/trial/trial.py:105-115
@classmethod
async def create(cls, config: TrialConfig) -> "Trial":
    task = await cls._load_task(config)
    if task.has_steps:
        from harbor.trial.multi_step import MultiStepTrial
        return MultiStepTrial(config, _task=task)
    from harbor.trial.single_step import SingleStepTrial
    return SingleStepTrial(config, _task=task)
```

---

## 2. Seam options and recommendation

### Constraint that shapes everything

`aws-bench`'s git origin is `git@github.com:aws-bench/aws-bench.git` — **upstream AWS, not
our fork** — and cdktn-bench pins it by git rev:

```toml
# CDKTN/pyproject.toml
dependencies = ["aws-bench"]
[tool.uv.sources]
aws-bench = { git = "https://github.com/aws-bench/aws-bench.git", rev = "6450cb56c4552934a37feff492a6fd4eb84d1108" }
[tool.uv]
package = false
```

So "just refactor `AwsBenchSingleStepTrial` into a mixin upstream" is the *clean* fix but
is not on our critical path. Everything below assumes we change only cdktn-bench.

---

### Seam A — subclass in cdktn-bench + own console_script **(RECOMMENDED)**

**The trial class.** Combine Harbor's multi-step workload shape with aws-bench's AWS
lifecycle overrides by multiple inheritance:

```python
class CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial): ...
```

C3 linearises this to
`[Cdktn, MultiStepTrial, AwsBenchSingleStepTrial, SingleStepTrial, Trial, ABC, object]`
(hand-verified; add a unit test asserting `__mro__`). That MRO gives us, for free:

| Method | Resolves to | Why it's right |
|---|---|---|
| `_run`, `_run_step*`, `_archive_step_outputs` | `MultiStepTrial` | the multi-step workload |
| `run` | `AwsBenchSingleStepTrial:103` | log context + post-trial scenario reset |
| `_prepare` | `AwsBenchSingleStepTrial:288` | contamination check, placeholder seed, `pre_invoke` — runs **once** before all steps, which is the correct AWS semantics |
| `_run_agent_phase` | `AwsBenchSingleStepTrial:323` | placeholder substitution + staged agent creds, **per step** |
| `_run_shared_verifier` | `AwsBenchSingleStepTrial:386` | staged verifier creds, per step |
| `_stop_agent_environment` | `AwsBenchSingleStepTrial:400` | `post_invoke` teardown, once |
| `_init_logger`, `_setup_agent_environment` | `AwsBenchSingleStepTrial:85`, `:267` | aws-bench log format, container-started flag |

Zero-argument `super()` inside the inherited aws-bench methods still resolves correctly,
because it walks the *instance's* MRO.

**One obstacle, one fix.** `SingleStepTrial.__init__` refuses a steps task:

```python
# HARBOR/trial/single_step.py:25-26
if _task is not None and _task.has_steps:
    raise ValueError("SingleStepTrial requires a task without [[steps]].")
```

Fix: our `__init__` sets the pre-super state that `AwsBenchSingleStepTrial.__init__`
establishes (`AWSB/task/aws_trial.py:78-82` — `_aws_placeholders`, `_aws_post_invoke_done`,
`_agent_container_started`, `_account_manager`) plus `_are_artifacts_collected`
(`HARBOR/trial/single_step.py:28`), then calls `Trial.__init__` **explicitly**, bypassing
both guards. ~10 lines, no vendoring.

**Two deliberate overrides beyond that:**

1. `_recover_outputs` — the MRO gives us `MultiStepTrial`'s (`multi_step.py:55-57`), which
   calls `_stop_agent_environment` (→ minutes-long `post_invoke`) inside the *cancel*
   path. `AwsBenchSingleStepTrial._recover_outputs` (`aws_trial.py:390-398`) deliberately
   defers that to `_finalize` so Ctrl-C is not stranded. Re-assert aws-bench's version.
2. `_prepare_step` — add credentialed per-step harness actions (see §4).

**The dispatch.** Two thin subclasses mirroring the aws-bench originals:

```python
class CdktnTrialQueue(AwsBenchTrialQueue):     # overrides _execute_trial_with_retries
    ...                                        # mirrors AWSB/task/queue.py:119-151
class CdktnBenchJob(AwsBenchJob):              # overrides __init__ to install the queue
    ...                                        # mirrors AWSB/task/job.py:84-88
```

Roughly 30 lines, all delegating to `super()`.

**The CLI.** cdktn-bench becomes a package (`package = true`, a `cdktn_bench/` module,
`[project.scripts] cdktn-bench = "cdktn_bench.cli.main:app"`). The Typer app re-uses
aws-bench's `env_app`, `view`, preflight, ledger, and display helpers by direct import.
The only symbol that must be substituted is the module global `AwsBenchJob` that
`start` reads at `AWSB/cli/jobs.py:760`. Two sub-options:

- **A1 (1 line):** `aws_bench.cli.jobs.AwsBenchJob = CdktnBenchJob` before registering
  `start`. Python resolves module globals at call time, so this works and gives us
  **100 % flag parity for free**. It is a rebind of an import binding, not a method patch
  — but it *is* a monkeypatch, so guard it with a test asserting the symbol exists and is
  what we expect.
- **A2 (~60 lines):** cdktn's own `run` command accepting only the flags
  `scripts/run-bench.sh` actually passes (`CDKTN/scripts/run-bench.sh:230-256`:
  `-a -m -o -k --path --scenario-path --registry-path -d --env-name -l --yes --ak --ae`),
  building `AwsBenchJobConfig` and calling `CdktnBenchJob.create(config)` directly.
  No monkeypatch; costs flag parity for flags we never use.

Recommend shipping **A2** with **A1** kept in a branch as the escape hatch if we ever need
an aws-bench flag we didn't reimplement.

**Blast radius:** nothing in Harbor or aws-bench is modified. All credential staging,
placeholder resolution, scenario admission gating, export collection, contamination
checks, and account reset are *inherited*, not copied.

---

### Seam B — Harbor plugin / registry mechanism: **does not exist**

Harbor has `import_path` dynamic loading for **agents** and **verifiers**
(`HARBOR/models/trial/config.py:55`, `:79`, `:192`) and factories for both
(`HARBOR/agents/factory.py`, `HARBOR/verifier/factory.py`). It has **no** equivalent for
trials. Its `entry_points.txt` declares only console scripts
(`harbor-0.9.0.dist-info/entry_points.txt`: `harbor`, `hb`, `hr`). The one and only trial
dispatch is the hard-coded `if task.has_steps` in `Trial.create`
(`HARBOR/trial/trial.py:105-115`), and aws-bench replaces even that with its own
`AwsBenchTrial.create` (`AWSB/task/aws_trial.py:440-449`). **Rejected: there is no seam.**

---

### Seam C — vendor `aws_trial.py` + `queue.py` into cdktn-bench: **rejected**

It would copy ~450 lines of the highest-risk code in the stack (STS assume-role, in-container
credential-file heredocs, contamination flags, account reset) and fork it away from an
upstream we pin by git rev and will want to bump. Seam A *inherits* the identical code.
The only thing vendoring buys is avoiding the 10-line `__init__` bypass — a bad trade.

---

### RECOMMENDATION

**Seam A, with sub-option A2.** Evidence:

1. Harbor already has the entire multi-step engine (`HARBOR/trial/multi_step.py`, 382 lines)
   — writing our own would be pure duplication.
2. Every AWS behaviour we need is expressed as **lifecycle overrides on `Trial`**, not on
   `SingleStepTrial`: `_prepare`, `_run_agent_phase`, `_run_shared_verifier`,
   `_stop_agent_environment`, `run` (`AWSB/task/aws_trial.py:288, 323, 386, 400, 103`).
   `AwsBenchSingleStepTrial` adds nothing single-step-specific except its inherited
   `_run`. That is precisely the shape that makes MRO composition work.
3. The dispatch point is a single call site (`AWSB/task/queue.py:122`) in a class already
   designed for subclassing (`AwsBenchTrialQueue(TrialQueue)`), itself installed by a
   single assignment (`AWSB/task/job.py:84-88`).
4. cdktn-bench already tolerates the multi-step `result.json` shape in its gates
   (`CDKTN/gates/emit_result.py:420-447`) — someone anticipated this.
5. aws-bench's own refusal message names exactly one unknown ("per-step pre/post-invoke
   credentialing is undefined"), and §4 below answers it with aws-bench's own
   `ScriptRunner`.

---

## 3. Agent-session continuity

### What the harness actually does

**No session survives a harness action, by construction and by default.**

1. Each `_run_agent_phase` invokes `self.agent.run(...)` afresh
   (`HARBOR/trial/trial.py:239`), which for `ClaudeCode` is a brand-new
   `claude --print` process (`HARBOR/agents/installed/claude_code.py:1144-1155`). Harbor
   passes **no** `--resume` and **no** `--continue`.
2. Worse (or better — see below), the session store is *relocated* between steps.
   `CLAUDE_CONFIG_DIR = /logs/agent/sessions` (`claude_code.py:1113`) bind-mounts
   `TrialPaths.agent_dir` (`HARBOR/trial/trial.py:687-690`, docker `mounted=True` at
   `HARBOR/environments/docker/docker.py:206`), and
   `MultiStepTrial._archive_step_outputs` (`HARBOR/trial/multi_step.py:334-343`) **moves**
   `paths.agent_dir` contents into `steps/<name>/agent/` via
   `ArtifactHandler.move_dir_contents` (`HARBOR/trial/artifact_handler.py:26-43`).

So step 2 begins with an empty Claude config dir → a genuinely fresh session.

**What *does* survive:** the container and its filesystem. The agent environment is stopped
only after the last step (`HARBOR/trial/multi_step.py:51`, `:83-84`), so `/app` (the
workspace, the agent's step-1 IaC) persists untouched. Only `/logs/agent` is relocated.

### Can we inject a second message into a live session?

Not into a *live* one — there is no live process to inject into. But we can **resume** one.
The Claude Code CLI that Harbor shells out to supports `--continue`, `--resume <id>`,
`--session-id <uuid>`, and `--fork-session` — confirmed from the SDK that drives the same
binary:

```text
claude_agent_sdk/_internal/transport/subprocess_cli.py:289  cmd.append("--continue")
claude_agent_sdk/_internal/transport/subprocess_cli.py:292  cmd.extend(["--resume", self._options.resume])
claude_agent_sdk/_internal/transport/subprocess_cli.py:295  cmd.extend(["--session-id", self._options.session_id])
claude_agent_sdk/_internal/transport/subprocess_cli.py:344  cmd.append("--fork-session")
```

A continuity implementation would be a cdktn `ClaudeCode` subclass that (a) passes
`--session-id <deterministic uuid>` on step 1 and `--resume <same uuid>` afterwards, and
(b) overrides `_archive_step_outputs` to exclude `sessions/` from relocation.

### The token-accounting consequence — and why fresh sessions win

**Fresh session (default):** each step's `populate_context_post_run` parses only that
step's own JSONL, so `step_results[i].agent_result.n_output_tokens` is *that step's
output tokens alone*. Exact per-step attribution, zero work. Aggregation already exists
both in Harbor (`HARBOR/models/trial/result.py:90-129`) and in our gates
(`CDKTN/gates/emit_result.py:420-447`).

**Resumed session:** `--resume` writes the *full* prior history into the resumed session's
JSONL. `ClaudeCode._convert_events_to_trajectory`
(`HARBOR/agents/installed/claude_code.py:521-911`) de-duplicates by assistant message id
*within one parse* (`:633-647`) but has no notion of "messages I already counted in a
previous step" — so step 2 would re-sum step 1's assistant usage. **Per-step output-token
attribution breaks.** Recovering it needs a cdktn-side JSONL diff by message id across
steps.

### Recommendation

**Fresh session per step is the right default for cdktn-bench.**

- It is what Harbor gives for free, and it is what preserves clean per-step output-token
  attribution — the thing tokens-to-green depends on.
- It is defensible as a benchmark construct: an operator returning to a repo a week later
  to make a change request has no chat history either. State carries through the
  *workspace*, which is exactly the artefact the benchmark is grading.
- It also **strengthens the no-foreshadowing property**: there is no conversational
  channel through which step-2 intent could leak backwards or forwards.

Treat `--resume` as a possible future *arm* (measuring the value of retained context), not
as the baseline, and only after adding per-step JSONL de-duplication.

**Consequence to design around:** step-2's instruction must be self-contained. Nothing from
step 1's reasoning survives — only files. A prompt phrased as "now also add X to what you
just built" will land on an agent that has to re-read the workspace to know what "what you
just built" is. That is fine (arguably realistic), but the instruction text must not assume
recall.

---

## 4. Where harness-driven between-step actions live

Three insertion points inside `MultiStepTrial._run_step` (`HARBOR/trial/multi_step.py:59-93`):

### (a) Pre-agent, per step — the main hook

Stock Harbor gives `_prepare_step` (`:95-102`): upload `steps/<name>/workdir/` into cwd
(`:283-292`), then run `steps/<name>/workdir/setup.sh` (`:294-318`), then a per-step
healthcheck (`:320-332`).

**But `setup.sh` runs with no AWS credentials.** aws-bench stages credentials only inside
`_run_phase_script` (`AWSB/task/aws_trial.py:242-265`) and `_run_agent_phase` (`:335`).
This is precisely the gap aws-bench cites when it refuses multi-step.

**The answer is aws-bench's own `ScriptRunner`, which is fully generic over its script
type.** `AWSB/task/script_runner.py:89-134` derives *every* path from `script_type.value`:

- host script dir = `task_dir / <value>/`
- container script dir = `/<value>/`
- container output = `/logs/<value>/`
- host output = `trial_paths.trial_dir / <value>/`

So a `_prepare_step` override can run a per-step phase script by passing
`task_dir=self.task.paths.step_dir(step.name)` and
`trial_paths=TrialPaths(trial_dir=self.paths.step_dir(step.name))`, yielding
`steps/<name>/pre_invoke/pre_invoke.sh` → output under `<trial>/steps/<name>/pre_invoke/`.
aws-bench already uses exactly this `TrialPaths(trial_dir=...)` re-basing trick at
`AWSB/task/aws_trial.py:259`.

That single hook carries all three of the operator's requirements:

1. **Apply/deploy of the agent's prior-step work** — `terraform apply` / `cdk deploy` run
   by the harness with staged credentials.
2. **Out-of-band, console-style drift injection** — `aws` CLI or boto against the scenario
   account under the `pre_invoke_role_name` role
   (`AWSB/dataset/task_config.py:50-66`).
3. **Feeding step-2's prompt** — the script's result JSON already flows into
   `update_placeholder_values` (`AWSB/task/aws_trial.py:307-319`), so a drift-injection
   script can hand the step-2 instruction the ARN/id it just mutated via `{{...}}`.

### (b) Post-agent, pre-verifier, per step

No stock hook. If the apply must happen *after* the final step's agent (rather than as the
next step's pre-invoke), add a symmetric `steps/<name>/post_agent/` phase in the `_run_step`
override, between `_run_step_agent` and `_run_step_verifier`.

**Naming warning:** aws-bench's task-level `[post_invoke]` is the account-teardown script
run inside `_stop_agent_environment` (`AWSB/task/aws_trial.py:411-423`). Do **not** reuse
that name for a per-step hook.

### (c) The per-step green gate — already exists

`StepConfig.min_reward` (`HARBOR/models/task/config.py:374-382`) +
`_should_stop_after_step` (`HARBOR/trial/multi_step.py:162-192`). Setting `min_reward = 1.0`
on step 1 means step 2's prompt never fires unless step 1 verified green.

Two caveats, both scoring-related — see §5 item 7.

---

## 5. Task-dir / dataset shape

### Today

`generator/gen.py::generate_arm` (`CDKTN/generator/gen.py:1806-1881`) writes, per arm:

```text
tasks/anchor/<spec-id>-<arm>/
├── task.toml           # gen.py:1818-1820 via build_task_toml (:762-876)
├── instruction.md      # gen.py:1814-1815 via build_instruction_md (:239-262)
├── environment/        # gen.py:1811 — copytree of arms/<arm>/environment/ (:642)
├── tests/              # _assert_lib.sh :1825, static_tiers.sh :1826, test.sh :1827,
│                       # live_check.py :1834, policy.{guard,rego} :1850-1855
└── solution/solve.sh   # stub only, never overwrites (:1857-1864)
```

`task.toml` sets `[task]`, `[scenario] scenario_id="anchor"`, `[concurrency]`,
`[metadata]` (incl. `canary`, `max_iters`), `[agent] timeout_sec`, `[verifier] timeout_sec`,
`[environment]` (`gen.py:791-835`). **No steps concept anywhere.**

### Proposed multi-step shape

Harbor's native layout needs no new conventions for the core; only the credentialed
harness hook is a cdktn extension.

```text
tasks/anchor/<spec-id>-<arm>/
├── task.toml                     # + [[steps]], + multi_step_reward_strategy
├── environment/                  # unchanged: docker build context + step-1 workspace seed
├── steps/
│   ├── 01-initial/
│   │   ├── instruction.md        # step-1 prompt         HARBOR/models/task/paths.py:149-151
│   │   ├── tests/test.sh         # step-1 oracle         HARBOR/models/task/paths.py:157-163
│   │   ├── workdir/              # optional files dropped into cwd   multi_step.py:283-292
│   │   │   └── setup.sh          # optional, NO aws creds            multi_step.py:294-318
│   │   └── solution/solve.sh     # optional per-step oracle solution paths.py:175-181
│   └── 02-change-request/
│       ├── instruction.md        # step-2 prompt — never referenced from step 1
│       ├── tests/test.sh         # step-2 oracle
│       └── pre_invoke/           # ← cdktn extension: creds-staged harness action
│           └── pre_invoke.sh     #   apply step-1 work + inject drift + emit placeholders
├── tests/                        # OPTIONAL shared oracle, appended to every step
└── (no root instruction.md)      # ignored when steps exist: task.py:73-74
```

`task.toml` additions:

```toml
multi_step_reward_strategy = "final"     # see §5 item 7 — do NOT leave at the "mean" default

[[steps]]
name = "01-initial"
min_reward = 1.0                          # step 2 only fires if step 1 is green
[steps.agent]
timeout_sec = 3600.0

[[steps]]
name = "02-change-request"
[steps.agent]
timeout_sec = 3600.0
```

### The no-foreshadowing guarantee, and its one hole

**Guaranteed:** `steps/02-*/instruction.md` lives host-side only and is read on demand at
step-2 invocation (`HARBOR/models/task/task.py:188-192`), then passed as shell-quoted argv
(`claude_code.py:1019, 1151`). The task directory is never uploaded to the container — only
`environment/` (as the docker build context) and, at verification time, `tests/`. So
step-2 intent is genuinely invisible during step 1.

**The hole is `tests/`.** `Verifier._resolve_tests` (`HARBOR/verifier/verifier.py:100-128`)
uploads the **shared** `tests/` *and* the step's own tests into `/tests`, and in
shared-verifier mode `/tests` is only emptied at the start of the *next* step's
verification (`_reset_shared_step_verifier_dirs`, `HARBOR/trial/multi_step.py:274-281`) —
i.e. after that step's agent has already run. So during step 2's agent phase, `/tests`
still holds step 1's oracle.

**Generator rules that follow:**

1. Every step's oracle goes in `steps/<name>/tests/`. Keep the shared root `tests/` empty
   or strictly step-agnostic.
2. Never place step-2 material in `environment/` — that *is* the image the agent lives in.
3. Never place step-2 material in `steps/01-*/workdir/`.
4. Consider emptying `/tests` in each step's `pre_invoke` if grader-visibility during a
   later step is judged unacceptable at all.

### Generator work required (`CDKTN/generator/gen.py`)

| Function | Today | Change |
|---|---|---|
| `build_instruction_md` | `:239-262`, one prompt | per-step; `TRAILER` (`:140`) pinning `/logs/agent/agent-output.txt` becomes per-step — which works naturally, since `/logs/agent` is relocated into `steps/<n>/agent/` after each step |
| `build_task_toml` | `:762-876` | emit `[[steps]]` + `multi_step_reward_strategy`; move `max_iters` (`:822`) and `[agent] timeout_sec` (`:825`) per step |
| `build_static_tiers_sh` / `build_test_sh` | `:1072`, `:1560` | write into `steps/<name>/tests/` |
| `generate_arm` | `:1806-1881` | emit the `steps/` tree; the existing `pre_invoke` branch (`:1866-1879`, currently `NotImplementedError`) becomes the per-step harness-action writer |
| spec schema | `specs/SCHEMA.md`, `generator/spec_model.py` | add `steps:` with per-step `instruction`, `oracle`, and a `harness:` block (apply? drift mutation?) |

---

## 6. Single-step assumptions that a `MultiStepTrial` would break

Ordered by how much they will hurt.

1. **HARD BLOCK — `AwsBenchTrial.create` refuses steps outright.**
   `AWSB/task/aws_trial.py:443-448`. Its stated reason ("per-step pre/post-invoke
   credentialing is undefined") is answered by §4(a). Seam A bypasses this factory entirely.
2. **`SingleStepTrial.__init__` raises on a steps task** (`HARBOR/trial/single_step.py:25-26`)
   — bypassed by calling `Trial.__init__` directly (§2, Seam A).
3. **`trial_dir/agent/trajectory.json` disappears.** Multi-step relocates it to
   `steps/<name>/agent/trajectory.json` (`HARBOR/trial/multi_step.py:338-339`). Hardcoded
   readers of the old path:
   - `AWSB/metrics/run_data.py:633` and `:666`
   - `CDKTN/gates/emit_result.py:288` (`extract_n_llm_calls`) — this is the
     **iterations-to-green** input
   - `CDKTN/gates/emit_result.py:115-135` (`classify_infra_failure`, reads
     `agent/agent-output.txt`, `agent/claude-code.txt`)
   - `CDKTN/gates/audit.py` (Gate 2 bypass audit) reads the same trajectory
   Also relocated: `verifier/tier1-not-verifiable` (`CDKTN/gates/emit_result.py:165`) and
   `verifier/test-stdout.txt` (`:233`) → `steps/<name>/verifier/`.
   **Note:** gates' *token* aggregation already handles the step shape
   (`emit_result.py:420-447`); its *trajectory* and *log* readers do not.
4. **`TrialResult.agent_result` is never set** by `MultiStepTrial._run`
   (`HARBOR/trial/multi_step.py:31-53`). `compute_token_cost_totals` copes; direct readers
   get `None`. `CDKTN/metrics/result_schema.json:137` documents the single-step shape.
5. **`TrialResult.agent_execution` / `.verifier` `TimingInfo` stay `None`** — they are set
   on the `StepResult` instead (`HARBOR/trial/trial.py:234`, `multi_step.py:132`). So
   `AWSB/metrics/run_data.py:603-621` (`agent_execution_sec`) silently returns `None` and
   latency metrics vanish.
6. **Reward aggregation default is wrong for a green/not-green benchmark.**
   `_select_multi_step_reward` (`HARBOR/trial/multi_step.py:194-199`) defaults to `mean`
   (`HARBOR/models/task/config.py:418-429`), and `_aggregate_step_rewards`
   (`multi_step.py:201-228`) averages only over steps that *produced* a verifier result.
   Combined with the `min_reward` abort (item 7), **a trial that fails step 1 and never
   runs step 2 scores the mean of one step — potentially higher than a trial that ran and
   failed step 2.** Use `strategy = "final"`, or override `_select_multi_step_reward`.
7. **The `min_reward` gate aborts quietly.** `_should_stop_after_step`
   (`HARBOR/trial/multi_step.py:162-192`) logs at debug/warning and returns; a step's
   `exception_info` is recorded on the `StepResult`, not on `TrialResult.exception_info`.
   So gates' validity classification, which reads the top-level exception, sees a clean
   trial that only ran half its steps. We need an explicit "steps completed / steps
   declared" field in the emitted result row.
8. **Retry re-runs the whole trial, including harness mutations.**
   `AwsBenchTrialQueue._execute_trial_with_retries` (`AWSB/task/queue.py:119-151`) rmtrees
   the trial dir and rebuilds. For multi-step that is both agent invocations *and* both
   pre-invoke deploys — roughly doubling retry cost on top of the ~8.5-min scenario reset.
9. **The turn budget silently doubles.** `--max-turns` comes from `--ak max_turns=N`
   (`CDKTN/scripts/run-bench.sh:245`) and is applied per `claude` invocation
   (`HARBOR/agents/installed/claude_code.py:33-38`). An N-turn budget becomes N *per step*.
   `jobs/<name>/budget.json` (`run-bench.sh:387`) records one `max_iters` and needs a
   per-step notion, or equipping comparisons between single- and multi-step tasks are
   apples-to-oranges.
10. **Progress hooks double-fire.** `TrialEvent.AGENT_START` and `VERIFICATION_START` are
    emitted once *per step* (`HARBOR/trial/trial.py:231`, `multi_step.py:136`); Harbor's
    progress UI registers them assuming one each per trial (`HARBOR/job.py:842-843`).
11. **`_recover_outputs` MRO trap** — `MultiStepTrial`'s version (`multi_step.py:55-57`)
    stops the environment inside the cancel path, which `AwsBenchSingleStepTrial`
    deliberately defers (`AWSB/task/aws_trial.py:390-398`). Must be overridden or Ctrl-C
    gets stranded behind a multi-minute reset.
12. **The account is never reset between steps.** `AwsBenchSingleStepTrial.run`
    (`AWSB/task/aws_trial.py:113-116`) resets after the whole trial. That is *desired*
    (state must carry between steps) but means a step 1 that leaves the account wedged
    poisons step 2 with no recovery path — and both steps' AWS damage accumulates before
    the single reset.
13. **`AwsBenchTask._validate_layout` bans separate-environment verifiers**
    (`AWSB/dataset/task_config.py:196-202`). Multi-step resolves verifier mode *per step*
    (`HARBOR/trial/multi_step.py:81` → `resolve_step_verifier_mode`); we must keep the ban
    and assert it per step, otherwise a step could tear down the agent container mid-trial
    (`multi_step.py:83-84`).
14. **`Task.checksum` changes.** It is a `dirhash` of the whole task dir
    (`HARBOR/models/task/task.py:194-199`) and rides the resume identity — so no job
    resumes across the migration. Expected, but worth stating.
15. **cdktn-bench is not a package.** `CDKTN/pyproject.toml` sets `package = false` and
    declares no `[project.scripts]`. Seam A requires flipping both and adding a
    `cdktn_bench/` module (today the repo has `oracles/` as a real package, `gates/` as a
    PEP-420 namespace dir, and everything else as scripts).

---

## 7. Open questions for the operator

1. **Session policy.** Confirm fresh-session-per-step as the default (recommended, §3), or
   ask for a `--resume` arm — which requires per-step JSONL de-duplication before
   tokens-to-green stays valid.
2. **Who applies the agent's step-1 work?** The harness (a `steps/02/pre_invoke` running
   `terraform apply` / `cdk deploy`) or the agent (step-1 instruction says "…and deploy
   it")? This changes what the trap measures and whether agent-side deploy failures count
   against it. The graded scenarios in
   `CDKTN/docs/scenario-grades/2026-08-20-summary.md` read as if the harness deploys.
3. **Is step-1-green a hard gate?** `min_reward` aborts the trial. Should an aborted trial
   score 0, or the mean of what ran? (Default `mean` gives the perverse result in §6.6.)
4. **Tokens-to-green: per-step or cumulative?** Per-step is free. Cumulative-to-first-green
   across steps needs a new emitted field and a definition of which step counts as "green".
5. **Per-step turn/token budget:** same N per step, or one shared budget split across
   steps? Affects `budget.json` and the equipping hash.
6. **Do we flip cdktn-bench to a real package** (`package = true`, `cdktn_bench/`,
   console_script `cdktn-bench`)? Seam A requires it.
7. **One CLI or two?** Keep `aws-bench` for single-step tasks and add `cdktn-bench` only
   for multi-step, or route *everything* through the new CLI? (Recommend: everything, so
   gates/equipping have exactly one path to reason about.)
8. **Upstream PR?** Should we simultaneously propose extracting the AWS behaviours from
   `AwsBenchSingleStepTrial` into a mixin upstream, which would delete our `__init__`
   bypass? Clean long-term, off the critical path.
9. **Drift-injection authority.** `pre_invoke_role_name` is per-task
   (`AWSB/dataset/task_config.py:50-66`). Do we need per-*step* roles — e.g. a deliberately
   over-privileged "console operator" identity for drift injection distinct from the
   agent's role?
10. **Migration of existing single-step tasks.** Do the 3-arm generated tasks stay
    single-step (one `instruction.md`) and only new specs get `steps/`, or do we normalise
    everything to a 1-step multi-step shape for uniform result plumbing? (The latter costs
    a task-checksum churn but collapses the two result shapes in §6.3–6.5 into one.)

---

## Appendix — the ~40 lines that unlock this

Sketch only; not final code.

```python
# cdktn_bench/trial.py
from harbor.trial.trial import Trial
from harbor.trial.multi_step import MultiStepTrial
from aws_bench.task.aws_trial import AwsBenchSingleStepTrial
from aws_bench.account_management.manager import AccountManager

class CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial):
    """Harbor's multi-step workload + aws-bench's AWS lifecycle, by MRO.

    MRO: Cdktn -> MultiStepTrial -> AwsBenchSingleStepTrial -> SingleStepTrial -> Trial
    """

    def __init__(self, config, *, _task=None):
        # AwsBenchSingleStepTrial's pre-super state (aws_trial.py:78-82)
        self._aws_placeholders = {}
        self._aws_post_invoke_done = False
        self._agent_container_started = False
        self._account_manager = AccountManager()
        self._are_artifacts_collected = False        # single_step.py:28
        if _task is not None and not _task.has_steps:
            raise ValueError("CdktnMultiStepTrial requires a task with [[steps]].")
        # Skip BOTH subclass __init__ guards; go straight to the base.
        Trial.__init__(self, config, _task=_task)

    async def _recover_outputs(self) -> None:
        # aws-bench semantics (aws_trial.py:390-398): defer the env stop to _finalize.
        await self._sync_agent_output(self.result)

    async def _prepare_step(self, step, step_result) -> None:
        await self._run_step_harness_action(step, step_result)   # creds-staged ScriptRunner
        await super()._prepare_step(step, step_result)
```

```python
# cdktn_bench/queue.py / job.py
class CdktnTrialQueue(AwsBenchTrialQueue):
    async def _execute_trial_with_retries(self, trial_config):
        ...  # mirrors AWSB/task/queue.py:119-151, calling CdktnTrial.create

class CdktnBenchJob(AwsBenchJob):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self._trial_queue = CdktnTrialQueue(
            n_concurrent=self.config.n_concurrent_trials,
            retry_config=self.config.retry,
            hooks=self._trial_queue._hooks,
        )   # mirrors AWSB/task/job.py:84-88
```
