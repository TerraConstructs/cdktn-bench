#!/usr/bin/env bash
# run-bench.sh — wrapper around `uv run cdktn-bench run` that:
#
# (Flipped from `aws-bench` to `cdktn-bench` on 2026-08-20, DECISIONS.md
#  Amendment 27. `cdktn-bench` is a strict SUPERSET of `aws-bench`, not a
#  replacement: it registers aws-bench's own `start` function object on its own
#  Typer app — `app.command(name="run", ...)(start)` in cdktn_bench/cli.py — so
#  every flag below reaches exactly the same parser it always did. The only
#  behavioural difference is the trial factory:
#      cdktn_bench/trial.py::CdktnTrial.create dispatches on `task.has_steps`;
#      a STEPLESS task returns the UNTOUCHED upstream AwsBenchSingleStepTrial,
#      a [[steps]] task returns CdktnMultiStepTrial.
#  So every existing single-step task runs the byte-identical code path it ran
#  before this flip, and the multi-step tasks the generator now emits stop being
#  refused with upstream's NotImplementedError("multi-step AWS tasks are not yet
#  supported"). `aws-bench` itself stays installed and working; `aws-bench env
#  init/setup/cleanup` are unaffected — cdktn-bench re-exports the same env_app.)
#
#   1. Authenticates Claude Code from an OAuth token file (default
#      ~/.anthropic — an operator-created convention for this repo, NOT an
#      independently verified `claude setup-token` output path; see
#      scripts/lib/resolve-claude-token.sh's header for why), override with
#      $AWS_BENCH_CLAUDE_TOKEN_FILE, forwarding it into the trial as
#      CLAUDE_CODE_OAUTH_TOKEN. Precedence: an already-exported
#      CLAUDE_CODE_OAUTH_TOKEN env var wins outright; otherwise the token
#      file; otherwise nothing is set and ANTHROPIC_API_KEY (if exported)
#      keeps working unchanged. If NEITHER resolves, this script prints a
#      one-line warning to stderr (it does not hard-fail — an operator
#      relying on a credential mechanism this script doesn't know about,
#      e.g. a pre-populated container image, is still possible) rather than
#      silently proceeding to spend AWS/wall-clock time on a trial that will
#      fail at agent auth. See scripts/lib/resolve-claude-token.sh and
#      gates/RECON.md item 1 for the mechanism and evidence this relies on:
#      Harbor's ClaudeCode.run() reads both env vars straight from this
#      process's os.environ at trial-run time and forwards them into the
#      agent container as literal `docker compose exec -e KEY=VALUE` flags —
#      no fork/subclass needed, a wrapper script is sufficient.
#
#   2. Configures the model via -m/--model or $MODEL, default
#      "claude-sonnet-5" (bare Anthropic-API/OAuth naming, NOT Bedrock
#      naming — this script never sets CLAUDE_CODE_USE_BEDROCK /
#      AWS_BEARER_TOKEN_BEDROCK, so ClaudeCode.run() takes the plain-API
#      model-name path unchanged: claude_code.py:1074-1091). Documented
#      alternative: claude-haiku-4-5-20251001.
#
#   3. Surfaces the flags this repo's local-registry.json / local-registry.md
#      invocations need (-k, -o, --path, --scenario-path, --registry-path,
#      -d, --env-name, -l, -a, --yes) with a `jobs/<cell>`-shaped default
#      output dir, and passes everything else through verbatim.
#
#   4. Wires the pre-registered budget cap (docs/iac-abstraction-aws-bench-plan.md
#      Phase 2 item 2 / iac-abstraction-benchmark-prereg.md §4: "MAX_ITERS = 8
#      feedback cycles or MAX_TOKENS per trajectory, whichever first"):
#        - MAX_ITERS (default 100, --max-iters; raised from the prereg's 8 on
#          2026-08-13 by DECISIONS.md Amendment 22 — `--max-turns` counts agent
#          STEPS, not the prereg's feedback CYCLES) maps to Claude Code's real
#          `--max-turns` CLI flag via `--ak max_turns=N` (verified against
#          the installed harbor package,
#          .venv/lib/python*/site-packages/harbor/agents/installed/claude_code.py
#          CLI_FLAGS: CliFlag("max_turns", cli="--max-turns", type="int",
#          env_fallback="CLAUDE_CODE_MAX_TURNS") — this IS the "MAX_ITERS
#          maps to --ak max_turns or the correct claude-code knob" item the
#          build plan flagged as needing verification). Injected early in
#          ARGS so an explicit `--ak max_turns=...` the caller passes via
#          `--`/pass-through still wins (harbor.cli.utils.parse_kwargs
#          builds its dict by iterating the `--ak` list in argv order,
#          later entries overwrite earlier ones for the same key — verified
#          against .venv's harbor/cli/utils.py — so ordering ARGS with the
#          default injected before EXTRA is what makes "explicit override
#          wins" true, not an accident).
#        - MAX_TOKENS (default unset — "pilot-set", per the build plan;
#          Phase 3's whole purpose is to set this from observed pilot
#          distributions, so this script deliberately ships no numeric
#          default) has NO native runtime enforcement knob: the installed
#          harbor ClaudeCode agent's CLI_FLAGS have no total-token-budget
#          flag (only `max_budget_usd`, a cost-not-token cap, and
#          `max_thinking_tokens`, a per-response reasoning cap — neither is
#          a whole-trajectory token budget). MAX_TOKENS is therefore a
#          **post-hoc grading threshold**, not a pre-hoc kill-switch: this
#          script records it to `${JOBS_DIR}/budget.json` alongside
#          MAX_ITERS so `gates/emit_result.py::to_result_row`'s
#          `max_tokens=`/`max_iters=` auto-censoring path (and
#          `metrics/tokens_to_green.py`'s own `--max-tokens`/`--max-iters`)
#          have a single canonical, job-scoped source for the budget that
#          applied, instead of re-deriving it from environment variables
#          that don't outlive the shell that started the job. Also forwarded
#          into the trial's own agent-visible environment as
#          `CDKTN_BENCH_MAX_TOKENS` (`--ae`) purely for in-trial-log
#          provenance/audit-trail purposes — it has no effect on Claude
#          Code's own behavior. As of 2026-08-06, `gates/emit_result.py`'s
#          CLI genuinely reads this file (`--jobs-dir <this JOBS_DIR>`,
#          `read_budget()`) and folds it into the emitted row's
#          auto-censoring — but only when a caller actually invokes
#          `emit_result.py --jobs-dir ... --model ... --harness ...
#          --oracle-version ...` per trial after this script's run
#          completes; there is still no automatic per-job orchestration
#          step in this repo that does that for a real (non-fixture) run
#          (Slice F is still pending). Until that orchestration exists,
#          budget.json is written correctly but only takes effect if the
#          caller wires it in by hand.
#      `--dry-run` prints the resolved MAX_ITERS/MAX_TOKENS values (no file
#      is written in dry-run mode — see the `budget.json` write below, which
#      is skipped entirely on the dry-run path, same as every other real-run
#      side effect this script has).
#
# This script makes a real (billed) Claude Code call and, via cdktn-bench,
# expects a real AWS account for the scenario side — it does not run
# anything on its own. See mk/rails.mk's `run-smoke` target for the intended
# invocation, and its docstring for why that target is not run as part of
# this slice's verification.
#
# Dry-run: set AWS_BENCH_DRY_RUN=1 (or pass --dry-run) to print the argv
# that would be passed to `uv run cdktn-bench` — with no exec, no token
# resolution side effects visible, and no AWS/Claude calls made — instead of
# running it. Used by test/test_run_bench_wrapper.py to exercise the
# argument-assembly and default logic without a live trial.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/resolve-claude-token.sh
source "$REPO_ROOT/scripts/lib/resolve-claude-token.sh"

usage() {
  cat <<'EOF'
Usage: scripts/run-bench.sh [options] [-- extra cdktn-bench run args]

Options (env var alternatives in parentheses; all optional):
  -m, --model MODEL         Model name. Default: claude-sonnet-5. Documented
                             alternative: claude-haiku-4-5-20251001. (MODEL)
  -k, --n-attempts N        Attempts per trial -> cdktn-bench run -k.
  -o, --jobs-dir DIR        Results dir -> cdktn-bench run -o.
                             Default: jobs/<model>.
      --path DIR             Task directory -> cdktn-bench run --path.
      --scenario-path DIR    Scenario directory -> cdktn-bench run --scenario-path.
      --registry-path FILE   Local registry file -> cdktn-bench run --registry-path.
  -d, --dataset NAME[@VER]  Dataset name[@version] -> cdktn-bench run -d.
      --env-name NAME        aws-bench env name -> cdktn-bench run --env-name.
  -l, --n-tasks N            Max tasks -> cdktn-bench run -l.
  -a, --agent NAME           Agent name -> cdktn-bench run -a. Default: claude-code.
      --yes                  Skip cdktn-bench's confirmation prompt.
      --max-iters N          Budget cap: feedback cycles before censoring.
                              Maps to `--ak max_turns=N` (Claude Code's real
                              `--max-turns` flag). Default: 100 (prereg §4's
                              8, raised by DECISIONS.md Amendment 22).
                              Pass 0 or an empty string to skip injecting it
                              entirely (falls back to Claude Code's own
                              default / an explicit --ak you pass yourself).
                              (MAX_ITERS)
      --max-tokens N          Budget cap: total trajectory tokens before
                              censoring. No native harness flag exists for
                              this (see this script's own header) — recorded
                              to `<jobs-dir>/budget.json` for offline
                              censoring by gates/emit_result.py /
                              metrics/tokens_to_green.py, and forwarded as
                              `CDKTN_BENCH_MAX_TOKENS` (--ae) for in-trial
                              provenance only. Default: unset (pilot-set per
                              the build plan — no numeric default is baked
                              in until Phase 3's pilot sets one). (MAX_TOKENS)
      --dry-run              Print the assembled `uv run cdktn-bench` argv and
                              exit, instead of running it. (AWS_BENCH_DRY_RUN=1)
  -h, --help                 Show this help.

Any other argument, or anything after `--`, is forwarded verbatim to
`uv run cdktn-bench run`.

Token resolution: CLAUDE_CODE_OAUTH_TOKEN env (if already set) takes
precedence over $AWS_BENCH_CLAUDE_TOKEN_FILE (default ~/.anthropic — an
operator-created convention, not a verified `claude setup-token` output
path); if neither resolves, ANTHROPIC_API_KEY (if exported) keeps working
unchanged. If NEITHER CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY end up
set, a warning is printed to stderr (the run still proceeds — see
scripts/lib/resolve-claude-token.sh). The token value itself is never
printed by this script, including in --dry-run output.

Requires AWS credentials (for the scenario/environment side) and a real
Claude Code credential. Makes a paid Claude Code API call.
EOF
}

MODEL="${MODEL:-claude-sonnet-5}"
AGENT="claude-code"
N_ATTEMPTS=""
JOBS_DIR=""
TASK_PATH=""
SCENARIO_PATH=""
REGISTRY_PATH=""
DATASET=""
ENV_NAME=""
N_TASKS=""
YES=0
DRY_RUN="${AWS_BENCH_DRY_RUN:-0}"
# Budget cap (prereg §4): MAX_ITERS defaults to 100 (the pre-registration's own
# 8, raised by DECISIONS.md Amendment 22 — see the note below);
# MAX_TOKENS has deliberately no numeric default (pilot-set, see this
# script's own header) — an unset/empty value means "no MAX_TOKENS recorded
# for this job", not "0".
# Default raised 8 -> 100 (2026-08-13, DECISIONS.md Amendment 22). `--max-turns`
# counts Claude Code AGENT STEPS, not the pre-reg's feedback CYCLES — one cycle
# (author -> deploy -> read error -> amend) is many steps, and a LIVE scenario's
# steps include minutes-long applies, so 8 steps under-budgets badly (the first
# live trial hit error_max_turns at 8). Start large; MAX_TOKENS remains the real
# censoring budget. MONITOR actual turn usage per scenario and TRIM toward 50 if
# 100 proves wasteful — see CLAUDE.md "Turn budget".
MAX_ITERS="${MAX_ITERS:-100}"
MAX_TOKENS="${MAX_TOKENS:-}"
EXTRA=()

while [ $# -gt 0 ]; do
  case "$1" in
    -m|--model) MODEL="$2"; shift 2 ;;
    -k|--n-attempts) N_ATTEMPTS="$2"; shift 2 ;;
    -o|--jobs-dir) JOBS_DIR="$2"; shift 2 ;;
    --path) TASK_PATH="$2"; shift 2 ;;
    --scenario-path) SCENARIO_PATH="$2"; shift 2 ;;
    --registry-path) REGISTRY_PATH="$2"; shift 2 ;;
    -d|--dataset) DATASET="$2"; shift 2 ;;
    --env-name) ENV_NAME="$2"; shift 2 ;;
    -l|--n-tasks) N_TASKS="$2"; shift 2 ;;
    -a|--agent) AGENT="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    --max-iters) MAX_ITERS="$2"; shift 2 ;;
    --max-tokens) MAX_TOKENS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; EXTRA+=("$@"); break ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

: "${JOBS_DIR:=jobs/${MODEL}}"

resolve_claude_token

# Neither credential resolved: warn (stderr, not stdout — never mixed into
# --dry-run's argv/status output) but don't hard-fail. ANTHROPIC_API_KEY is
# checked here too even though resolve_claude_token never touches it,
# because the trial is only truly credential-less if BOTH are absent — this
# is the one place that knows about both, so it's the one place that can
# make that call. Without this, a trial proceeds to resolve the AWS
# environment and build/start the agent container (real AWS work, real
# wall-clock) only to fail at `claude --print` auth with zero prior signal.
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "warn: no Claude credential resolved (checked \$CLAUDE_CODE_OAUTH_TOKEN," \
       "\$AWS_BENCH_CLAUDE_TOKEN_FILE=${AWS_BENCH_CLAUDE_TOKEN_FILE:-$HOME/.anthropic}," \
       "\$ANTHROPIC_API_KEY); the trial will fail at agent auth" >&2
fi

ARGS=(run -a "$AGENT" -m "$MODEL" -o "$JOBS_DIR")
[ -n "$N_ATTEMPTS" ] && ARGS+=(-k "$N_ATTEMPTS")
[ -n "$TASK_PATH" ] && ARGS+=(--path "$TASK_PATH")
[ -n "$SCENARIO_PATH" ] && ARGS+=(--scenario-path "$SCENARIO_PATH")
[ -n "$REGISTRY_PATH" ] && ARGS+=(--registry-path "$REGISTRY_PATH")
[ -n "$DATASET" ] && ARGS+=(-d "$DATASET")
[ -n "$ENV_NAME" ] && ARGS+=(--env-name "$ENV_NAME")
[ -n "$N_TASKS" ] && ARGS+=(-l "$N_TASKS")
[ "$YES" -eq 1 ] && ARGS+=(--yes)
# MAX_ITERS -> Claude Code's real --max-turns flag, injected BEFORE EXTRA so
# an explicit `--ak max_turns=...` the caller passes via `--`/pass-through
# still wins (see this script's header for the parse_kwargs override-order
# citation). "0" or "" skips injection entirely (falls back to Claude Code's
# own default, or an explicit --ak the caller supplies).
if [ -n "$MAX_ITERS" ] && [ "$MAX_ITERS" != "0" ]; then
  ARGS+=(--ak "max_turns=$MAX_ITERS")
fi
# MAX_TOKENS has no native harness flag (see header) -- forwarded only as an
# agent-visible env var for in-trial provenance; the actual censoring
# threshold is recorded to budget.json below, which is the value
# gates/emit_result.py / metrics/tokens_to_green.py actually read.
[ -n "$MAX_TOKENS" ] && ARGS+=(--ae "CDKTN_BENCH_MAX_TOKENS=$MAX_TOKENS")
# bash 3.2 (macOS system bash) treats "${EXTRA[@]}" on a genuinely empty
# array as an unbound-variable error under `set -u`; guard with a length
# check instead of relying on the bash-4.4+ ${arr[@]:-} safe-expansion.
if [ "${#EXTRA[@]}" -gt 0 ]; then
  ARGS+=("${EXTRA[@]}")
fi

# --- Runtime holdout-equipping guard (2026-08-06 fix: "The holdout guard
# misses the only two placements that actually equip an agent" -- part (b))
# ----------------------------------------------------------------------
# generator/gen.py::enforce_no_holdout_equipping only ever sees equipping
# material physically shipped inside a GENERATED task directory -- it has
# no visibility into --skill/--mcp-config passed straight through on the
# cdktn-bench CLI (harbor's real equipping knobs, gates/equipping.py's own
# docstring: "take a file/dir of any name"), which this script's own EXTRA
# catch-all forwards verbatim. This is the CLI-argument counterpart of that
# same rule (prereg §7.1 / DECISIONS.md Amendment 10): refuse outright if
# any --skill/--mcp-config is present in the assembled ARGS AND the task(s)
# being targeted (best-effort, from --path/-d) resolve to a HOLDOUT-split
# scenario. Runs on the --dry-run path too (before the dry-run exit below)
# so this is testable/verifiable without a real trial.
#
# KNOWN LIMITATION (not exhaustive): a bare `--registry-path`/`-d` dataset
# invocation with no `-l`/task filter that resolves to MULTIPLE tasks
# across MULTIPLE scenarios cannot be statically narrowed down to "which
# scenario(s)" from argv alone -- this guard only recognizes a spec id it
# can extract from `--path`'s basename (`<spec-id>-<arm-dirname>`, this
# repo's own generator/gen.py::task_dir() convention) or from `-d`'s
# dataset name. It is a real, additional guard, not a substitute for
# gates/equipping.py::compute_equipping_hash folding externally-supplied
# equipping into the hash (see budget.json's own `cli_equipping` field
# below, which is the other half of this fix).
CLI_EQUIP_FLAGS=()
_i=0
while [ "$_i" -lt "${#ARGS[@]}" ]; do
  case "${ARGS[$_i]}" in
    --skill|--mcp-config)
      _next=$((_i + 1))
      CLI_EQUIP_FLAGS+=("${ARGS[$_i]}=${ARGS[$_next]:-}")
      ;;
  esac
  _i=$((_i + 1))
done

if [ "${#CLI_EQUIP_FLAGS[@]}" -gt 0 ]; then
  CANDIDATE_SPEC_IDS=()
  for _base in "$(basename "${TASK_PATH:-.}")" "${DATASET%@*}"; do
    [ -z "$_base" ] || [ "$_base" = "." ] && continue
    for _suffix in -awscdk -hcl-raw -terraconstructs; do
      case "$_base" in
        *"$_suffix") CANDIDATE_SPEC_IDS+=("${_base%"$_suffix"}") ;;
      esac
    done
    CANDIDATE_SPEC_IDS+=("$_base") # in case the caller passed the bare spec id
  done

  # bash 3.2 (macOS system bash) treats "${CANDIDATE_SPEC_IDS[@]}" on a
  # genuinely empty array as an unbound-variable error under `set -u` (the
  # same trap this file already guards against for EXTRA above). When
  # neither --path nor -d/--dataset resolves to a recognizable spec id
  # (the documented KNOWN LIMITATION above), CANDIDATE_SPEC_IDS is
  # legitimately empty -- skip the loop rather than expand the array.
  if [ "${#CANDIDATE_SPEC_IDS[@]}" -gt 0 ]; then
    for _spec_id in "${CANDIDATE_SPEC_IDS[@]}"; do
      _group="$(cd "$REPO_ROOT" && uv run python -c '
import sys
sys.path.insert(0, "generator")
from split import spec_group
try:
    g = spec_group(sys.argv[1])
except FileNotFoundError:
    g = None
print(g or "")
' "$_spec_id" 2>/dev/null)"
      if [ "$_group" = "holdout" ]; then
        echo "REFUSED: --skill/--mcp-config equipping (${CLI_EQUIP_FLAGS[*]}) targets" >&2
        echo "scenario '$_spec_id', which is assigned to the HOLDOUT split" >&2
        echo "(specs/split.yaml). Per prereg §7.1 / DECISIONS.md Amendment 10, tuned" >&2
        echo "equipping must never be run against a holdout scenario via CLI" >&2
        echo "passthrough -- this is the CLI-argument counterpart of" >&2
        echo "generator/gen.py::enforce_no_holdout_equipping." >&2
        exit 1
      fi
    done
  fi
fi

if [ "$DRY_RUN" = "1" ]; then
  # Print argv only — never the resolved token, and CLAUDE_CODE_OAUTH_TOKEN
  # is an env var, not an argv entry, so it can't leak here by construction.
  # One arg per line so tests can assert on exact tokens without a shell
  # re-parse. No budget.json is written on this path -- dry-run has no file
  # side effects, full stop (see this script's header).
  printf 'uv run cdktn-bench'
  printf ' %s' "${ARGS[@]}"
  printf '\n'
  printf 'CLAUDE_CODE_OAUTH_TOKEN_SET=%s\n' "$([ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && echo 1 || echo 0)"
  printf 'MAX_ITERS=%s\n' "$MAX_ITERS"
  printf 'MAX_TOKENS=%s\n' "$MAX_TOKENS"
  exit 0
fi

cd "$REPO_ROOT"

# Record the resolved budget alongside the job's own results so
# gates/emit_result.py / metrics/tokens_to_green.py have one canonical,
# job-scoped source for what MAX_ITERS/MAX_TOKENS applied -- env vars don't
# outlive this shell, and re-deriving the budget from --ak max_turns=N deep
# inside each trial's own config.json is exactly the kind of silent-drift
# risk DECISIONS.md's equipping-hash rationale already warns about for other
# fields. `null` (not a bare empty string) for an unset MAX_TOKENS so the
# file is valid JSON either way.
mkdir -p "$JOBS_DIR"
MAX_TOKENS_JSON="null"
[ -n "$MAX_TOKENS" ] && MAX_TOKENS_JSON="$MAX_TOKENS"
# `cli_equipping` (2026-08-06 fix, "the holdout guard misses ... part (b)"):
# any --skill/--mcp-config passed via CLI passthrough (see the holdout
# guard above, which already refused a HOLDOUT-scenario invocation before
# reaching here) is invisible to gates.equipping.compute_equipping_hash
# (which only ever rglobs the task_dir it's given) -- recording it here
# means a caller emitting a result row for this job CAN fold it into that
# trial's `extra_cfg` (gates/emit_result.py's `--extra-cfg`), so a
# tuned-vs-empty comparison never silently treats two trials as
# equipping-identical when one carried extra CLI-supplied skills/MCP
# config the other didn't. Folding it in automatically would need this
# script itself to call gates/emit_result.py per trial, which it does not
# do (Slice F, still pending) -- see this file's own MAX_TOKENS section
# above for the same "recorded correctly, wired in by hand" caveat.
CLI_EQUIPPING_JSON="[]"
if [ "${#CLI_EQUIP_FLAGS[@]}" -gt 0 ]; then
  CLI_EQUIPPING_JSON="$(uv run python -c '
import json, sys
print(json.dumps(sys.argv[1:]))
' "${CLI_EQUIP_FLAGS[@]}")"
fi
printf '{\n  "max_iters": %s,\n  "max_tokens": %s,\n  "cli_equipping": %s\n}\n' \
  "${MAX_ITERS:-null}" "$MAX_TOKENS_JSON" "$CLI_EQUIPPING_JSON" > "$JOBS_DIR/budget.json"

exec uv run cdktn-bench "${ARGS[@]}"
