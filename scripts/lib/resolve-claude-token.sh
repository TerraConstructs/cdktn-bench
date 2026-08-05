#!/usr/bin/env bash
# resolve-claude-token.sh — resolves CLAUDE_CODE_OAUTH_TOKEN for a trial run.
#
# Meant to be `source`d (not executed) by scripts/run-bench.sh, and directly
# by tests, so it can export into the caller's shell.
#
# Precedence (highest wins), per REQUIREMENTS in the task brief this
# implements and gates/RECON.md item 1:
#   1. CLAUDE_CODE_OAUTH_TOKEN already set in the environment — left
#      untouched. This lets a caller's own env override always win.
#   2. $AWS_BENCH_CLAUDE_TOKEN_FILE (default: ~/.anthropic) — read (if it
#      exists, is a regular file, and is non-empty after trimming
#      whitespace) and exported as CLAUDE_CODE_OAUTH_TOKEN.
#   3. Neither present/usable: CLAUDE_CODE_OAUTH_TOKEN is left unset. This is
#      not a failure by itself — ANTHROPIC_API_KEY (if the caller has it
#      exported) keeps working unchanged, because Harbor's ClaudeCode.run()
#      reads both env vars independently from os.environ at trial-run time
#      and lets the `claude` binary arbitrate; Harbor does not require
#      CLAUDE_CODE_OAUTH_TOKEN to be set (harbor/agents/installed/claude_code.py:
#      1023-1034,1070-1072). scripts/run-bench.sh is the caller responsible
#      for warning when this function leaves BOTH credentials unresolved —
#      this function itself stays silent-on-success/silent-on-absence by
#      design (see "Never echoes" below) and never raises.
#
# On the default path, `~/.anthropic`: this is NOT independently verified
# against a real `claude setup-token` run — nothing in this repo, in Harbor,
# or in aws-bench documents where that command actually writes its output
# (grepping Harbor's claude_code.py only shows it *reading*
# CLAUDE_CODE_OAUTH_TOKEN from the process environment, never a file path).
# Treat `~/.anthropic` as an **operator-created convention** this repo picked
# for $AWS_BENCH_CLAUDE_TOKEN_FILE's default, not a confirmed fact about the
# `claude` CLI's own behavior. If `claude setup-token` writes somewhere else
# on your machine (e.g. ~/.claude, the macOS Keychain, ~/.config/anthropic),
# either point $AWS_BENCH_CLAUDE_TOKEN_FILE at the real file yourself, or
# export CLAUDE_CODE_OAUTH_TOKEN directly — both are first-class, equally
# supported paths (see precedence above).
#
# Never echoes, logs, or otherwise prints the token value anywhere — callers
# that want to confirm resolution should check whether
# CLAUDE_CODE_OAUTH_TOKEN is non-empty, not print it.
#
# Usage:
#   source scripts/lib/resolve-claude-token.sh
#   resolve_claude_token
#   # $CLAUDE_CODE_OAUTH_TOKEN is now set if it could be resolved.

resolve_claude_token() {
  local token_file="${AWS_BENCH_CLAUDE_TOKEN_FILE:-$HOME/.anthropic}"

  # Highest precedence: an already-exported CLAUDE_CODE_OAUTH_TOKEN wins
  # outright and we must not touch it (empty-string override counts as
  # "not set" — an operator exporting CLAUDE_CODE_OAUTH_TOKEN="" clearly
  # wants the file/API-key path, not a literal empty token forwarded to the
  # trial).
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    return 0
  fi

  if [ -f "$token_file" ]; then
    # Suspend xtrace (if a caller has `set -x` on) for the duration of the
    # secret read/export, so bash's own command tracing never echoes the
    # token value to stderr; restore the caller's xtrace state before
    # returning, on every path (including the empty-file fall-through
    # below).
    local restore_xtrace=0
    case "$-" in *x*) restore_xtrace=1; set +x ;; esac

    local raw token resolved=0
    raw="$(cat "$token_file" 2>/dev/null || true)"
    # Trim leading/trailing whitespace (a trailing newline from an editor
    # is the common case; command substitution above already stripped
    # trailing newlines, this additionally handles stray spaces/tabs).
    token="${raw#"${raw%%[![:space:]]*}"}"
    token="${token%"${token##*[![:space:]]}"}"
    if [ -n "$token" ]; then
      export CLAUDE_CODE_OAUTH_TOKEN="$token"
      resolved=1
    fi
    # Drop the secret from these locals before xtrace (if any) comes back
    # on — everything below only branches on the non-secret $resolved flag,
    # never re-tests $token/$raw, so no later trace line can echo it.
    unset raw token

    [ "$restore_xtrace" -eq 1 ] && set -x

    if [ "$resolved" -eq 1 ]; then
      return 0
    fi
  fi

  # No env override, no (usable) token file: leave CLAUDE_CODE_OAUTH_TOKEN
  # unset. ANTHROPIC_API_KEY, if the caller has it exported, is untouched
  # and keeps working via Harbor's independent env-var read.
  return 0
}
