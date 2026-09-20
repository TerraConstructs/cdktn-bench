#!/usr/bin/env bash
# Generated -- generator/gen.py. Verifier entry point: exec the real
# static-tier chain, then (only if this scenario's task.toml sets
# SPEC_LIVE_CHECK_ENABLED=true, i.e. verifier.live_check.enabled is
# true for this spec) run live_check.py. If task.toml ALSO sets
# SPEC_LIVE_CHECK_GATING=true (verifier.live_check.gating), fold
# live_check.py's own JSON `.outcome` into reward.txt (AND
# semantics -- see gen.py::build_test_sh's own comment for the
# full rationale); otherwise live_check.py stays purely
# observational, exactly as before. A missing/crashing python3
# interpreter is its own distinct "run_invalid" outcome (see
# gen.py::build_test_sh's own comment), never silently folded into
# a legitimate "not_verifiable" verdict. Do not hand-edit;
# regenerate instead.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- BROWNFIELD SEED DEPLOY, FAIL-CLOSED (SCHEMA.md §2.7.1) ---------
# Every anti-vacuity layer of the seed-deploy mechanism lives inside
# pre_invoke/pre_invoke.sh, and aws_bench/task/aws_trial.py runs that
# file if and only if it is on disk -- `if
# self.task.has_phase_script(ScriptType.PRE_INVOKE):`, no else branch,
# no log line, and has_phase_script is pure file existence. A task tree
# that lost its pre_invoke/ directory (stale generator, bad image
# layer, truncated upload) therefore runs the whole trial against an
# EMPTY account in total silence, on which this scenario's live oracle
# passes for free (docs/brownfield-seed-not-deployed.md).
#
# The verifier is the one component that always runs, so it is the one
# that refuses. SPEC_SEED_DEPLOY_REQUIRED comes from this task's own
# [verifier].env (build_task_toml), written by the SAME generator
# branch that emits pre_invoke/pre_invoke.sh; the receipt is written by
# that script on its success path only, at a path ScriptRunner's step-7
# cleanup does not reach (gen.py::SEED_DEPLOY_RECEIPT_PATH explains why
# it cannot be /logs/pre_invoke/seed-proof.json).
#
# NOT a reward of 0.0, and the difference is the whole point: 0.0 is a
# MEASUREMENT -- it says the agent failed. This says no measurement
# exists. So it runs BEFORE static_tiers.sh, exits without ever writing
# /logs/verifier/reward.txt, and lets harbor's own
# RewardFileNotFoundError (harbor/verifier/verifier.py::verify) abort
# the trial with no reward key at all -- the same shape _prepare's
# ScriptExecutionError gives a seed that failed while it COULD still
# run. A machine-readable marker is left beside it for the operator.
#
# Emitted unconditionally and gated at RUNTIME on the env var, matching
# every other branch in this file, so a task that later GAINS a seed
# cannot end up with a tests/ directory that has no gate in it.
if [ "${SPEC_SEED_DEPLOY_REQUIRED:-false}" = "true" ]; then
  seed_receipt_outcome=""
  if [ -s "/logs/seed-deploy-receipt.json" ]; then
    seed_receipt_outcome="$(jq -r '.outcome // ""' "/logs/seed-deploy-receipt.json" 2>/dev/null)"
  fi
  if [ "$seed_receipt_outcome" != "seed_deployed" ]; then
    echo "SEED DEPLOY REQUIRED BUT NOT PROVEN: this task.toml sets" >&2
    echo "SPEC_SEED_DEPLOY_REQUIRED=true, so pre_invoke/pre_invoke.sh must have" >&2
    echo "deployed and proven this scenario's brownfield seed before the agent" >&2
    echo "started -- but /logs/seed-deploy-receipt.json says" >&2
    echo "'${seed_receipt_outcome:-<absent>}'. The account this verifier is about to" >&2
    echo "read was NEVER SEEDED, so a 'pass' from it would prove nothing" >&2
    echo "(docs/brownfield-seed-not-deployed.md). REFUSING TO GRADE: no reward file" >&2
    echo "is written, so this trial reports as INVALID rather than as a score." >&2
    jq -n --arg o "${seed_receipt_outcome:-}" \
      '{outcome: "run_invalid", status: "run_invalid", reason: ("SPEC_SEED_DEPLOY_REQUIRED=true but the seed receipt at /logs/seed-deploy-receipt.json is absent or not seed_deployed (found: " + (if $o == "" then "<absent>" else $o end) + ") -- pre_invoke/pre_invoke.sh did not run to completion in this container"), receipt_path: "/logs/seed-deploy-receipt.json"}' \
      > /logs/verifier/seed-deploy-missing.json 2>/dev/null \
      || echo '{"outcome":"run_invalid","status":"run_invalid","reason":"seed receipt absent"}' > /logs/verifier/seed-deploy-missing.json
    exit 1
  fi
fi

"$DIR/static_tiers.sh"
rc=$?

# AWS UNAVAILABLE => THE ROW IS VOID, NOT A ZERO. static_tiers.sh
# preflights `aws sts get-caller-identity` on the Terraform-shaped arms
# and drops this marker when there is no working credential chain
# (gen.py::build_static_tiers_sh). A nonzero rc from static_tiers.sh
# does NOT stop this script, and every block below it writes
# /logs/verifier/reward.txt on a gating failure -- so without this
# short-circuit a broken credential chain would score 0.0, i.e. an
# infrastructure failure wearing the costume of a wrong answer. Exit
# here instead, before any reward file exists, so harbor's own
# RewardFileNotFoundError aborts the trial as INVALID -- the same
# contract as the SPEC_SEED_DEPLOY_REQUIRED guard above.
if [ -f /logs/verifier/aws-unavailable ]; then
  echo "AWS UNAVAILABLE: static_tiers.sh could not reach AWS -- see" >&2
  echo "/logs/verifier/aws-unavailable. REFUSING TO GRADE: no reward file" >&2
  echo "is written, so this trial reports as INVALID rather than as a score." >&2
  rm -f /logs/verifier/reward.txt
  exit 1
fi

if [ "${SPEC_LIVE_CHECK_ENABLED:-false}" = "true" ] \
   && [ -f "$DIR/live_check.py" ]; then
  # REGION. The verifier container is handed credentials but NOT a
  # region, so without these two lines every `aws` call a
  # live_check.py makes dies with exit 253 (`NoRegion`) BEFORE
  # reaching AWS. live_check.py cannot tell that apart from a real
  # API error, reports "not_verifiable", and the gating below fails
  # closed to 0.0 -- an infrastructure failure wearing the costume
  # of an agent failure: a correct, deployed, converged solution
  # scores 0.0 with `"failures": []` and nothing marks the trial
  # invalid.
  #
  # Set in the GENERATOR, not in the hand-authored live_check.py
  # files: the region is a property of the environment the verifier
  # runs in, not of any one oracle. `:=` so a region the harness
  # DOES inject always wins; the literal is the region this bench is
  # pinned to by its own SCP.
  : "${AWS_DEFAULT_REGION:=us-east-1}"
  export AWS_DEFAULT_REGION
  if command -v python3 >/dev/null 2>&1; then
    python3 "$DIR/live_check.py" \
      > /logs/verifier/live_check-result.json \
      2> /logs/verifier/live_check-stderr.log
    py_rc=$?
  else
    py_rc=127
    echo "python3: command not found" > /logs/verifier/live_check-stderr.log
    : > /logs/verifier/live_check-result.json
  fi

  if [ "$py_rc" -ne 0 ]; then
    echo "live_check.py did not complete (python3 exit $py_rc) -- see live_check-stderr.log; NOT a legitimate live-check verdict" >&2
    jq -n --arg rc "$py_rc" \
      '{outcome: "run_invalid", status: "run_invalid", reason: ("interpreter/script failed, exit " + $rc + " -- see live_check-stderr.log")}' \
      > /logs/verifier/live_check-result.json
  fi

  # A live_check.py still carrying the generator stub's payload
  # (`"status": "not_implemented"`) proves the hand-authored oracle
  # this spec declares never reached the container. It prints no
  # `outcome`, so the gating block below would read "not_verifiable"
  # and score EVERY solution 0.0, correct ones included. Same rule as
  # static_tiers.sh's is_stub_policy: a missing oracle VOIDS the row,
  # it never grades it. No reward file is written, so harbor's own
  # RewardFileNotFoundError reports the trial INVALID.
  if [ "$(jq -r '.status // ""' /logs/verifier/live_check-result.json 2>/dev/null)" = "not_implemented" ]; then
    echo "GENERATOR STUB: tests/live_check.py is the inert generator stub, not this spec's" >&2
    echo "hand-authored live oracle. REFUSING TO GRADE: no reward file is written, so this" >&2
    echo "trial reports as INVALID rather than as a score." >&2
    rm -f /logs/verifier/reward.txt
    exit 1
  fi

  if [ "${SPEC_LIVE_CHECK_GATING:-false}" = "true" ]; then
    live_outcome="$(jq -r '.outcome // "not_verifiable"' /logs/verifier/live_check-result.json 2>/dev/null)"
    if [ -z "$live_outcome" ]; then
      live_outcome="not_verifiable"
    fi
    live_kind="$(jq -r '.not_verifiable_kind // ""' /logs/verifier/live_check-result.json 2>/dev/null)"

    # AWS never answered => the row is void, not a zero. Same rule as
    # the aws-unavailable marker above: "transient-exhausted" (every
    # attempt at a call timed out or was throttled) and "api-error"
    # (the call could not be made -- no credentials, no CLI, an API
    # refusal) are test-infrastructure failures, indistinguishable from
    # a wrong solution once written as 0.0. Writing no reward file makes
    # harbor's RewardFileNotFoundError report the trial invalid, keeping
    # a regional throttle out of tokens-to-green. Every other
    # not_verifiable kind is a statement about the account and still
    # gates to 0.0 below.
    case "$live_outcome:$live_kind" in
      not_verifiable:transient-exhausted|not_verifiable:api-error)
        echo "LIVE CHECK UNANSWERED ($live_kind): AWS never answered -- see" >&2
        echo "/logs/verifier/live_check-result.json. REFUSING TO GRADE: no reward" >&2
        echo "file is written, so this trial reports as INVALID rather than as a score." >&2
        rm -f /logs/verifier/reward.txt
        exit 1
        ;;
    esac

    if [ "$live_outcome" != "pass" ]; then
      echo "GATING: live_check.py outcome was '$live_outcome' (not 'pass') -- downgrading reward to 0.0" >&2
      echo "0.0" > /logs/verifier/reward.txt
      rc=1
    fi
  fi
fi

# --- idempotence tier (specs/SCHEMA.md §5.1) ------------------------
# "Is the agent's own toolchain still reporting a pending change
# against what it just deployed?" LIVE-ONLY by construction: with
# nothing deployed there is nothing to be idempotent about AND the
# command's exit code carries no signal -- an offline
# `terraform plan -detailed-exitcode` is always 2, and an offline
# `cdk diff` cannot resolve an AWS environment at all (it exits 1, the
# same code it uses for "changes found"). Both cases are caught below
# and reported not_verifiable WITH a reason, never fake-passed.
# Emitted only because this spec sets verifier.idempotence.enabled.
if [ "${SPEC_IDEMPOTENCE_ENABLED:-false}" = "true" ]; then
  idem_outcome="not_verifiable"
  idem_reason="tier did not run"
  idem_rc=""
  # This arm keeps no local deploy state to probe: cdk diff reads
  # the DEPLOYED stack, so the never-deployed / no-credentials
  # guarantee is delivered AFTER the run by the completion-marker
  # guard below (IDEMPOTENCE_COMPLETION_MARKER in generator/gen.py).
  # SEED MOVEMENT GUARD (specs/SCHEMA.md §2.7.1). The state
  # probe above cannot fire on a spec whose seed the HARNESS deployed
  # before the agent's first token, so a do-nothing agent would inherit
  # the seed's own convergence as a `converged` verdict. The seed's
  # identity has to have MOVED.
  seed_identity="$(jq -r '.state_identity // ""' /logs/seed-deploy-receipt.json 2>/dev/null)"
  now_identity="$(aws cloudformation describe-stacks --stack-name ScenarioStack --output json 2>/dev/null | jq -er '.Stacks[0] | "stack_id=" + (.StackId|strings) + ";last_update=" + ((.LastUpdatedTime // .CreationTime)|strings)' 2>/dev/null)"
  if [ -z "$seed_identity" ]; then
    idem_outcome="not_verifiable"
    idem_reason="the seed receipt at /logs/seed-deploy-receipt.json carries no state_identity, so this tier cannot tell whether the agent deployed anything or simply inherited the harness-deployed seed's converged state (specs/SCHEMA.md §2.7.1, finding H)."
  elif [ -z "$now_identity" ]; then
    echo "[idempotence] SEED MOVEMENT GUARD ABSTAINED: describe-stacks on ScenarioStack returned no readable stack identity, so this tier could not check whether the agent's own deployment moved the harness-seeded state. The verdict below rests on the completion-marker guard alone (specs/SCHEMA.md §2.7.1, finding H)." >&2
  elif [ "$seed_identity" = "$now_identity" ]; then
    idem_outcome="not_verifiable"
    idem_reason="the deployed state identity is still EXACTLY the one the harness seeded before the agent's first token ($seed_identity unchanged). That may mean the agent applied nothing, or that its apply failed without moving the state -- this tier cannot tell them apart, and in neither case is there an agent-produced deployment to be idempotent about. A converged verdict here would credit the agent with the SEED's convergence (specs/SCHEMA.md §2.7.1, finding H)."
  fi
  if [ "$idem_outcome" = "not_verifiable" ] && [ "$idem_reason" = "tier did not run" ]; then
    ( cd /app/project && npx cdk diff --fail --no-lookups ScenarioStack ) > /logs/verifier/idempotence.log 2>&1
    idem_rc=$?
    if [ "$idem_rc" -eq 0 ]; then
      idem_outcome="converged"
      idem_reason="the arm's own converged-state check reported no pending change"
    elif [ "$idem_rc" -eq 1 ] \
               && grep -qF 'Number of stacks with differences:' /logs/verifier/idempotence.log; then
      idem_outcome="pending_changes"
      idem_reason="the deployed state still differs from the configuration -- see idempotence.log"
    else
      idem_outcome="not_verifiable"
      idem_reason="the idempotence command exited $idem_rc without printing its own completion marker, so it never compared against the deployed stack (unresolvable AWS environment, credentials, network, or a broken working tree) -- see idempotence.log. Offline this is ALWAYS the outcome, so it is reported as unverifiable rather than as a real pending-changes verdict."
    fi
  fi
  jq -n --arg o "$idem_outcome" --arg r "$idem_reason" --arg rc "$idem_rc" \
    '{outcome: $o, reason: $r, exit_code: $rc, arm: "awscdk"}' \
    > /logs/verifier/idempotence-result.json
  if [ "${SPEC_IDEMPOTENCE_GATING:-false}" = "true" ] \
     && [ "$idem_outcome" != "converged" ]; then
    echo "GATING: idempotence outcome was '$idem_outcome' ($idem_reason) -- downgrading reward to 0.0" >&2
    echo "0.0" > /logs/verifier/reward.txt
    rc=1
  fi
fi

exit $rc
