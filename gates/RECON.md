# RECON — Claude Code agent wiring in Harbor / aws-bench

Scope: recon only, no implementation. All paths below are relative to the repo
venv `.venv/lib/python3.14/site-packages/` unless stated otherwise. aws-bench
is pinned at git rev `6450cb56c4552934a37feff492a6fd4eb84d1108`
(`pyproject.toml:15-16`).

**Naming note (2026-08-20, DECISIONS.md Amendment 27).** `scripts/run-bench.sh`
now execs `uv run cdktn-bench run …` rather than `uv run aws-bench run …`.
Every mechanism this document analyses is unchanged by that: `cdktn-bench`
registers aws-bench's own `start` function object on its own Typer app, so it
IS the same control-plane process reading the same `os.environ`, with the same
flags, and `ClaudeCode.run()` is reached by the identical path. Read every
`uv run aws-bench run …` below as "the control-plane process", which today is
spelled `cdktn-bench`.

## 1. How the agent container gets env vars

`ClaudeCode.run()` (`harbor/agents/installed/claude_code.py:1016-1155`) builds a
plain Python `dict` called `env` by reading **the control-plane process's own
`os.environ`** (the process running `uv run aws-bench run ...`), not anything
already inside the container:

- `claude_code.py:1023-1034` — unconditionally reads
  `ANTHROPIC_API_KEY` (falling back to `ANTHROPIC_AUTH_TOKEN`),
  `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_OAUTH_TOKEN`,
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, plus two static flags
  (`FORCE_AUTO_BACKGROUND_TASKS`, `ENABLE_BACKGROUND_TASKS`).
- `claude_code.py:1070-1072` — empty-string entries are dropped ("Remove empty
  auth credentials to allow Claude CLI to prioritize the available method.
  When both are empty, Claude CLI will fail with a clear authentication
  error."). **Both `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` are
  forwarded simultaneously if both are set in the host env** — Harbor does not
  itself pick a winner; that's left to the `claude` binary.
- `claude_code.py:1006-1013, 1037-1057` — Bedrock vars (`AWS_ACCESS_KEY_ID`,
  `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION`, etc.) are only added when
  `CLAUDE_CODE_USE_BEDROCK=1` or `AWS_BEARER_TOKEN_BEDROCK` is set in the host
  env — irrelevant to our Anthropic-API-only requirement.
- `claude_code.py:1111` — `env.update(self._resolved_env_vars)` merges any
  declarative `ENV_VARS` (currently only `MAX_THINKING_TOKENS`,
  `claude_code.py:91-98`).
- `claude_code.py:1139-1155` — this same `env` dict is passed to
  `exec_as_agent(...)` twice: once for the `mkdir`/skills/memory/MCP setup
  command, once for the actual
  `claude --verbose --output-format=stream-json --permission-mode=bypassPermissions ... --print -- <instruction>`
  invocation, teed to `/logs/agent/claude-code.txt`.

`exec_as_agent` → `BaseInstalledAgent._exec`
(`harbor/agents/installed/base.py:275-330`) additionally merges
`self._extra_env` **on top of** the passed-in `env` dict
(`base.py:288-291`), i.e. `extra_env` wins over anything `ClaudeCode.run()`
computed from `os.environ`. `self._extra_env` is populated from the
constructor's `extra_env` kwarg (`base.py:144-159`), which
`AgentFactory.create_agent_from_config` sets to
`resolve_env_vars(config.env)` (`harbor/agents/factory.py:158,166-172`), and
`config.env` is populated from repeatable `--ae`/`--agent-env KEY=VALUE` CLI
flags (`aws_bench/cli/jobs.py:216-225`, wired into `AgentConfig(...)` at
`jobs.py:638,648,660-661,671-672`).

Finally, `BaseEnvironment.exec(..., env=...)` reaches the Docker backend at
`harbor/environments/docker/docker.py:619-648`, which literally appends
`["-e", f"{key}={value}"]` per env-dict entry to a
`docker compose exec ... main <command>` invocation (`docker.py:636-638`) —
confirming these are real container env vars, not just visible to the host
process.

**Conclusion for requirement (1):** no fork or subclass is needed to inject a
file-backed OAuth token. Because `ClaudeCode.run()` reads
`CLAUDE_CODE_OAUTH_TOKEN` straight out of the *host* `os.environ`
(`claude_code.py:1028`) at the moment each trial runs, and `os.environ` is
process-wide and inherited by every async task `uv run aws-bench run` spawns,
a thin wrapper (shell function or `mk/rails.mk` target) that does, before
invoking `aws-bench run`:

```sh
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -f "$HOME/.anthropic" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.anthropic")"
fi
```

satisfies the requirement exactly as stated: an already-set
`CLAUDE_CODE_OAUTH_TOKEN` env var wins (untouched by the `if`), the file is
only read as a fallback, and `ANTHROPIC_API_KEY` keeps working unmodified
since `claude_code.py:1024-1026` forwards it independently and both
credentials can coexist in the container env with the `claude` CLI arbitrating
(per the comment at `claude_code.py:1070-1072`). The alternative seam,
`--ae CLAUDE_CODE_OAUTH_TOKEN=<value>` on the CLI, works too (same
precedence effect via `_extra_env` override in `base.py:288-291`) but is
worse for secret hygiene — the token would appear in argv/shell history —
so it should not be preferred over the wrapper.

## 2. `-m`/`--model` flow, and Anthropic vs Bedrock naming

`-m`/`--model` is a repeatable Typer option, `model_names: list[str]`
(`aws_bench/cli/jobs.py:196-205`, "Model name for the agent. Can be repeated
for multi-model runs."). When `--agent`/`--agent-import-path` is also given,
`jobs.py:640-652` builds one `AgentConfig(model_name=model_name, ...)` per
entry in `model_names` (fanning a run out into one job per model).

`AgentConfig.model_name` flows into `AgentFactory.create_agent_from_config`
(`harbor/agents/factory.py:140-180`), which passes
`model_name=config.model_name` into either `create_agent_from_name`
(`factory.py:70-97`, used for `-a`/`--agent claude-code`) or
`create_agent_from_import_path` (`factory.py:99-137`, used for
`--agent-import-path`). Both ultimately do
`agent_class(logs_dir=logs_dir, model_name=model_name, **kwargs)`
(`factory.py:97,137`), landing on `BaseAgent.__init__`
(`harbor/agents/base.py:20-46`), which just stores `self.model_name`.

`ClaudeCode.run()` consumes `self.model_name` at `claude_code.py:1074-1091`:

- If Bedrock mode is on (`_is_bedrock_mode()`, `claude_code.py:1006-1013`):
  pass the model string through as-is (Bedrock ARN / model ID), stripping only
  a Harbor-style `provider/` prefix if present (`claude_code.py:1077-1083`).
- Else if a custom `ANTHROPIC_BASE_URL` is set: keep the full model string
  (`claude_code.py:1084-1086`).
- **Else (the default, official Anthropic API path)**:
  `env["ANTHROPIC_MODEL"] = self.model_name.split("/")[-1]`
  (`claude_code.py:1087-1089`) — i.e. `-m claude-sonnet-5` passes through
  unchanged, and `-m anthropic/claude-sonnet-5` has the provider prefix
  stripped to `claude-sonnet-5`. Nothing in this path converts to or expects
  a `us.anthropic.*`/`global.anthropic.*` Bedrock-style ID, confirming
  **bare Anthropic-API model names work** as long as `CLAUDE_CODE_USE_BEDROCK`
  and `AWS_BEARER_TOKEN_BEDROCK` are both unset in the host env. Default
  Sonnet (`claude-sonnet-5`) and the tested alternative Haiku
  (`claude-haiku-4-5-20251001`) both need zero code changes — pure `-m`
  values.
- The resulting `ANTHROPIC_MODEL` env var is one of the `-e` flags forwarded
  into the container per §1, and is presumably read by the `claude` CLI
  binary itself. **Caveat: the `claude` CLI's own env-var handling lives
  inside the npm-installed `@anthropic-ai/claude-code` package** (installed
  at container-build time via `claude_code.py:127-159`'s `install()`), which
  is not vendored into this venv/repo, so I could not read its source to
  verify `ANTHROPIC_MODEL` consumption directly — this is asserted from
  Harbor's own contract/comments, not independently confirmed here.
- No `CLI_FLAGS` entry exists for `model` (`claude_code.py:33-90` lists
  `max_turns`, `reasoning_effort`, `thinking`, `thinking_display`,
  `max_thinking_tokens`, `max_budget_usd`, `fallback_model`,
  `append_system_prompt`, `allowed_tools`, `disallowed_tools` — no `model`).
  Model selection is env-var-only (`ANTHROPIC_MODEL`), not a `claude` CLI
  flag.

## 3. Where trajectory.json / result.json land, and which fields the audit gate needs

Per-trial host directory layout is `TrialPaths`
(`harbor/models/trial/paths.py:79-127`): `trial_dir/agent/` is bind-mounted
into the container at `/logs/agent` (docstring `paths.py:18-23,110-116`;
property `agent_dir` at `paths.py:161-168`).

- **Trajectory**: `ClaudeCode.populate_context_post_run()`
  (`claude_code.py:913-947`) converts the Claude Code session JSONL
  (`_get_session_dir`/`_convert_events_to_trajectory`,
  `claude_code.py:161-911`) into an ATIF `Trajectory` and writes it to
  `self.logs_dir / "trajectory.json"` (`claude_code.py:930-936`), i.e. host
  path **`<job_dir>/<trial_name>/agent/trajectory.json`**. The raw
  `stream-json` transcript is also teed to
  `<job_dir>/<trial_name>/agent/claude-code.txt` (`claude_code.py:1151-1153`),
  and re-read there to extract the authoritative `total_cost_usd`
  (`_parse_total_cost_from_stream_json`, `claude_code.py:490-519`).
- **Tool invocations** (what an audit gate walks): each `Step` in
  `trajectory.json["steps"]` optionally carries `tool_calls: [ToolCall]`
  (`harbor/models/trajectories/tool_call.py:8-31`): `tool_call_id`,
  `function_name`, `arguments: dict`, optional `extra`. Built in
  `_convert_event_to_step`'s `tool_call` branch (`claude_code.py:246-314`).
  Tool output is attached as `Step.observation.results[].content` plus
  metadata under `extra["metadata"]`/`extra["tool_use_result"]`/
  `extra["raw_tool_result"]` (`claude_code.py:417-488`, `269-289`). So an
  audit gate should read `trajectory.json → .steps[] → .tool_calls[] →
  {tool_call_id, function_name, arguments}` and cross-reference
  `.observation.results[].content` for what the tool returned.
- **Tokens**: per-step `Step.metrics` (`Metrics`, built in `_build_metrics`,
  `claude_code.py:383-415`: `prompt_tokens`, `completion_tokens`,
  `cached_tokens`, plus raw usage fields in `extra`), and trajectory-level
  `Trajectory.final_metrics` (`FinalMetrics`, `claude_code.py:889-896`):
  `total_prompt_tokens`, `total_completion_tokens`, `total_cached_tokens`,
  `total_cost_usd`, `total_steps`. These are also copied onto the trial's
  `AgentContext` (`claude_code.py:942-947`: `context.cost_usd`,
  `context.n_input_tokens`, `context.n_cache_tokens`,
  `context.n_output_tokens`).
- **result.json**: the harbor-level per-trial result is written by
  `SingleStepTrial`/`Trial` base machinery: `harbor/trial/trial.py:197`
  `self.paths.result_path.write_text(self.result.model_dump_json(indent=4))`,
  where `result_path` (`harbor/models/trial/paths.py:221-225`) resolves to
  **`<job_dir>/<trial_name>/result.json`** (singular — note the `TrialPaths`
  docstring at `paths.py:89,101` says `results.json` (plural); that's a stale
  comment, the actual property/code uses the singular filename, which is
  what's authoritative). Its schema is `TrialResult`
  (`harbor/models/trial/result.py:70-88`): `agent_info` (`AgentInfo` incl.
  `ModelInfo{name, provider}`, `result.py:52-59`), `agent_result`
  (`AgentContext`), `verifier_result`, timing blocks, and
  `compute_token_cost_totals()` (`result.py:90-`) for aggregating tokens/cost.
- **Distinct, unrelated `result.json`**: aws-bench's own AWS-scenario layer
  (deploy/verify/reset/cleanup phases, not the coding-agent trial) has its
  own `ScenarioTrialPaths.result_path = trial_dir / "result.json"`
  (`aws_bench/scenario/trial_paths.py:9-43`) for a `ScenarioTrialResult` —
  a different concept sharing only the filename. `AwsBenchSingleStepTrial`
  (`aws_bench/task/aws_trial.py:63-141`) is a `harbor.trial.single_step.
  SingleStepTrial` subclass that layers AWS credential injection on top and,
  after a mutating run, separately drives a `ScenarioTrial(RESET)` under
  `<trial_dir>/scenario-reset/` (`aws_trial.py:118-141`). **Our audit gate
  should read the harbor-level `<job_dir>/<trial_name>/result.json` +
  `<job_dir>/<trial_name>/agent/trajectory.json`**, not the AWS-scenario
  `ScenarioTrialResult`.

## 4. Cleanest non-fork extension seam

- `--agent-import-path` **is supported**, exactly like `--verifier-import-path`
  (`aws_bench/cli/jobs.py:187-195` vs `jobs.py:452-460,703-704`), and there is
  precedent for it in the upstream repo itself: the `MiniSweBedrock` docstring
  literally shows
  `aws-bench run --agent-import-path "aws_bench.agents.mini_swe_bedrock:MiniSweBedrock"`
  (`aws_bench/agents/mini_swe_agent.py:7-8`).
  `AgentFactory.create_agent_from_import_path`
  (`harbor/agents/factory.py:99-137`) does a plain `importlib.import_module`
  + `getattr`, so any subclass living in our own repo and importable under
  `uv run` (repo root or a `src/` dir on `sys.path`) works with zero patching
  of aws-bench/harbor.
- **However, recon findings §1–§2 show neither stated requirement actually
  needs a subclass**:
  - Requirement (1) (OAuth-token-from-file, env-var-override precedence,
    `ANTHROPIC_API_KEY` still works) is already exactly what
    `ClaudeCode.run()` does by reading `os.environ` at trial-run time
    (`claude_code.py:1024-1034,1070-1072`) — solved by a **wrapper script**
    that resolves `CLAUDE_CODE_OAUTH_TOKEN` (env override wins, else read
    `~/.anthropic`) and `export`s it before `uv run aws-bench run ...`. No
    agent code changes.
  - Requirement (2) (configurable model, default Sonnet, Haiku alternative,
    Anthropic-API naming) is a pure `-m`/`--model` CLI value
    (`jobs.py:196-205` → `claude_code.py:1074-1091`) — again no code changes,
    just choosing the right string (`claude-sonnet-5` /
    `claude-haiku-4-5-20251001`) and *not* setting any Bedrock env vars.
  - A plain wrapper (`mk/rails.mk` target invoking
    `uv run aws-bench run -a claude-code -m <model> ...` after resolving the
    token) is strictly simpler and lower-risk than introducing an
    `--agent-import-path` subclass: fewer moving parts, no need to mirror
    `ClaudeCode`'s `CLI_FLAGS`/`ENV_VARS`/ATIF-conversion machinery, and no
    risk of drifting from upstream's `ClaudeCode.run()` behavior on the next
    aws-bench pin bump.
- **Keep `--agent-import-path` in reserve**, not for auth/model plumbing, but
  for anything that genuinely requires new *behavior* inside `run()`/
  `populate_context_post_run()` — e.g. a custom tool-allowlist policy beyond
  `--allowedTools`/`--disallowedTools` (`claude_code.py:80-89`), injecting
  extra Anthropic-specific headers, or post-processing the trajectory for a
  cdktn-bench-specific audit signal not already in ATIF. If/when that need
  arises, subclass `harbor.agents.installed.claude_code.ClaudeCode` in our
  own repo (module importable under `uv run`) and pass
  `--agent-import-path "our_module:OurClaudeCode"` — no fork of the
  `aws-bench`/`harbor` pins required either way.

## Files read (for traceability)

- `.venv/lib/python3.14/site-packages/harbor/agents/installed/claude_code.py`
- `.venv/lib/python3.14/site-packages/harbor/agents/installed/base.py`
- `.venv/lib/python3.14/site-packages/harbor/agents/base.py`
- `.venv/lib/python3.14/site-packages/harbor/agents/factory.py`
- `.venv/lib/python3.14/site-packages/harbor/models/trial/paths.py`
- `.venv/lib/python3.14/site-packages/harbor/models/trial/result.py`
- `.venv/lib/python3.14/site-packages/harbor/models/agent/context.py`
- `.venv/lib/python3.14/site-packages/harbor/models/trajectories/trajectory.py`
- `.venv/lib/python3.14/site-packages/harbor/models/trajectories/tool_call.py`
- `.venv/lib/python3.14/site-packages/harbor/trial/trial.py`
- `.venv/lib/python3.14/site-packages/harbor/environments/docker/docker.py`
- `.venv/lib/python3.14/site-packages/aws_bench/cli/jobs.py`
- `.venv/lib/python3.14/site-packages/aws_bench/cli/shared_options.py`
- `.venv/lib/python3.14/site-packages/aws_bench/scenario/trial_paths.py`
- `.venv/lib/python3.14/site-packages/aws_bench/task/aws_trial.py`
- `.venv/lib/python3.14/site-packages/aws_bench/agents/mini_swe_agent.py`
- `pyproject.toml` (repo root)
