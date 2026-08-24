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

"$DIR/static_tiers.sh"
rc=$?

if [ "${SPEC_LIVE_CHECK_ENABLED:-false}" = "true" ] \
   && [ -f "$DIR/live_check.py" ]; then
  # REGION (2026-08-25). The verifier container is handed
  # credentials but NOT a region, so every `aws` call a
  # live_check.py makes died with exit 253 (`NoRegion`: "You must
  # specify a region") BEFORE reaching AWS. live_check.py cannot
  # tell that apart from a real API error, so it reported
  # "not_verifiable" -- which gating below fails closed to reward
  # 0.0. The result is an INFRASTRUCTURE failure wearing the
  # costume of an agent failure: a correct, deployed, converged
  # solution scores 0.0 with `"failures": []`, and nothing in
  # result.json's exception_info marks the trial as invalid.
  # Observed on all three arms of named-resource-replacement's
  # first live run (jobs/rerun-named-resource-replacement/
  # 2026-08-25__00-42-05); the same latent bug sits under every
  # apigw-redeploy live_check.py, which only ever passed because
  # its proofs were driven host-side with an operator shell that
  # had a region configured.
  #
  # Set here, in the GENERATOR, and not in the nine hand-authored
  # live_check.py files: the region is a property of the
  # environment the verifier runs in, not of any one oracle, and a
  # per-file fix would have to be repeated for every scenario
  # authored from now on. `:=` so a region the harness DOES inject
  # always wins; the literal is the region this bench is pinned to
  # by its own SCP.
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

  if [ "${SPEC_LIVE_CHECK_GATING:-false}" = "true" ]; then
    live_outcome="$(jq -r '.outcome // "not_verifiable"' /logs/verifier/live_check-result.json 2>/dev/null)"
    if [ -z "$live_outcome" ]; then
      live_outcome="not_verifiable"
    fi
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
  if [ ! -s "/app/project/cdktf.out/stacks/internal-services-network/terraform.tfstate" ]; then
    idem_outcome="not_verifiable"
    idem_reason="nothing was applied (no deploy state at /app/project/cdktf.out/stacks/internal-services-network/terraform.tfstate), so there is no converged state to re-check. An offline plan with no state ALWAYS reports pending changes, so this is reported as unverifiable rather than as a real pending-changes verdict."
  fi
  if [ "$idem_outcome" = "not_verifiable" ] && [ "$idem_reason" = "tier did not run" ]; then
    ( cd /app/project && npx cdktn synth >/dev/null && cd cdktf.out/stacks/internal-services-network && { [ -s terraform.tfstate ] || { echo "IDEMPOTENCE_STATE_VANISHED: cdktf.out/stacks/internal-services-network/terraform.tfstate existed before 'npx cdktn synth' and does not after it -- synth rewrote the stack directory, so there is no converged state left to plan against"; exit 9; }; } && terraform init -input=false >/dev/null && terraform plan -input=false -refresh=false -detailed-exitcode ) > /logs/verifier/idempotence.log 2>&1
    idem_rc=$?
    if [ "$idem_rc" -eq 0 ]; then
      idem_outcome="converged"
      idem_reason="the arm's own converged-state check reported no pending change"
    elif [ "$idem_rc" -eq 9 ]; then
      idem_outcome="not_verifiable"
      idem_reason="the deploy state this tier was about to check disappeared when the command re-synthesized the stack directory, so the plan below it would have run against no state at all (an offline plan with no state ALWAYS reports pending changes) -- see idempotence.log"
    elif [ "$idem_rc" -eq 2 ]; then
      idem_outcome="pending_changes"
      idem_reason="the deployed state still differs from the configuration -- see idempotence.log"
    else
      idem_outcome="not_verifiable"
      idem_reason="idempotence command exited $idem_rc (tool missing, credentials, or a broken working tree) -- see idempotence.log"
    fi
  fi
  jq -n --arg o "$idem_outcome" --arg r "$idem_reason" --arg rc "$idem_rc" \
    '{outcome: $o, reason: $r, exit_code: $rc, arm: "terraconstructs"}' \
    > /logs/verifier/idempotence-result.json
  if [ "${SPEC_IDEMPOTENCE_GATING:-false}" = "true" ] \
     && [ "$idem_outcome" != "converged" ]; then
    echo "GATING: idempotence outcome was '$idem_outcome' ($idem_reason) -- downgrading reward to 0.0" >&2
    echo "0.0" > /logs/verifier/reward.txt
    rc=1
  fi
fi

exit $rc
