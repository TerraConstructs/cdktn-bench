#!/usr/bin/env bash
# run-bench.sh — wrapper around `uv run aws-bench run` that:
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
# This script makes a real (billed) Claude Code call and, via aws-bench,
# expects a real AWS account for the scenario side — it does not run
# anything on its own. See mk/rails.mk's `run-smoke` target for the intended
# invocation, and its docstring for why that target is not run as part of
# this slice's verification.
#
# Dry-run: set AWS_BENCH_DRY_RUN=1 (or pass --dry-run) to print the argv
# that would be passed to `uv run aws-bench` — with no exec, no token
# resolution side effects visible, and no AWS/Claude calls made — instead of
# running it. Used by test/test_run_bench_wrapper.py to exercise the
# argument-assembly and default logic without a live trial.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/resolve-claude-token.sh
source "$REPO_ROOT/scripts/lib/resolve-claude-token.sh"

usage() {
  cat <<'EOF'
Usage: scripts/run-bench.sh [options] [-- extra aws-bench run args]

Options (env var alternatives in parentheses; all optional):
  -m, --model MODEL         Model name. Default: claude-sonnet-5. Documented
                             alternative: claude-haiku-4-5-20251001. (MODEL)
  -k, --n-attempts N        Attempts per trial -> aws-bench run -k.
  -o, --jobs-dir DIR        Results dir -> aws-bench run -o.
                             Default: jobs/<model>.
      --path DIR             Task directory -> aws-bench run --path.
      --scenario-path DIR    Scenario directory -> aws-bench run --scenario-path.
      --registry-path FILE   Local registry file -> aws-bench run --registry-path.
  -d, --dataset NAME[@VER]  Dataset name[@version] -> aws-bench run -d.
      --env-name NAME        aws-bench env name -> aws-bench run --env-name.
  -l, --n-tasks N            Max tasks -> aws-bench run -l.
  -a, --agent NAME           Agent name -> aws-bench run -a. Default: claude-code.
      --yes                  Skip aws-bench's confirmation prompt.
      --dry-run              Print the assembled `uv run aws-bench` argv and
                              exit, instead of running it. (AWS_BENCH_DRY_RUN=1)
  -h, --help                 Show this help.

Any other argument, or anything after `--`, is forwarded verbatim to
`uv run aws-bench run`.

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
# bash 3.2 (macOS system bash) treats "${EXTRA[@]}" on a genuinely empty
# array as an unbound-variable error under `set -u`; guard with a length
# check instead of relying on the bash-4.4+ ${arr[@]:-} safe-expansion.
if [ "${#EXTRA[@]}" -gt 0 ]; then
  ARGS+=("${EXTRA[@]}")
fi

if [ "$DRY_RUN" = "1" ]; then
  # Print argv only — never the resolved token, and CLAUDE_CODE_OAUTH_TOKEN
  # is an env var, not an argv entry, so it can't leak here by construction.
  # One arg per line so tests can assert on exact tokens without a shell
  # re-parse.
  printf 'uv run aws-bench'
  printf ' %s' "${ARGS[@]}"
  printf '\n'
  printf 'CLAUDE_CODE_OAUTH_TOKEN_SET=%s\n' "$([ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && echo 1 || echo 0)"
  exit 0
fi

cd "$REPO_ROOT"
exec uv run aws-bench "${ARGS[@]}"
