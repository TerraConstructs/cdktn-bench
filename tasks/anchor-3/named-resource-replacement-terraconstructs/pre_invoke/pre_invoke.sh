#!/usr/bin/env bash
# Generated -- generator/gen.py::build_seed_pre_invoke_sh, from
# specs/named-resource-replacement.yaml's workspace_seed.deploy (specs/SCHEMA.md §2.7.1),
# terraconstructs arm. Do not hand-edit; regenerate instead
# (`make gen SPEC=specs/named-resource-replacement.yaml`).
#
# HARNESS ACTION, not agent work. Run by
# aws_bench/task/aws_trial.py::AwsBenchSingleStepTrial._prepare inside
# the AGENT container, after the container is up and BEFORE the agent's
# first token, with ~/.aws/credentials staged for
# [scenario].pre_invoke_role_name. Its job is to make
# workspace_seed.premise's "it is already deployed in this account" TRUE
# -- and then to prove it, three ways, fail-closed.
#
# WHAT IS ACTUALLY GUARANTEED ABOUT WHAT THE AGENT SEES (restated by
# finding m2, adversarial review 2026-08-25 -- the sentence that used
# to sit here claimed the agent "never sees this file, its output, or
# the fact that a harness deployed anything", which was more than the
# code enforced):
#
#   GUARANTEED GONE. ScriptRunner removes /pre_invoke and
#   /logs/pre_invoke, and NOTHING ELSE, before the agent phase
#   (aws_bench/task/script_runner.py step 7, for PRE_INVOKE
#   specifically). So this script, its stdout.log, seed-proof.json and
#   every `aws` probe it writes are gone -- all of them are written
#   under those two paths ON PURPOSE, which is the only reason the
#   claim holds.
#
#   DELIBERATELY LEFT BEHIND. Exactly one artifact: the RECEIPT at
#   /logs/seed-deploy-receipt.json, read by tests/test.sh so a trial whose
#   seed never ran fails CLOSED instead of grading an empty account
#   (finding M3). It is one JSON object under /logs, a harness
#   directory the agent has no reason to open, and it discloses only
#   what workspace_seed.premise already tells the agent in its own
#   prompt -- that this workspace is already deployed.
#
# What the agent SHOULD see -- a state-bearing workspace under
# /app/project -- is the brownfield premise being true, which is the
# point.
#
# DELIBERATELY NOT `set -e`: every failure must reach `fail`, which
# writes the machine-readable verdict BEFORE exiting non-zero.
set -uo pipefail

mkdir -p /logs/pre_invoke
PROOF=/logs/pre_invoke/seed-proof.json

# THREE VERDICTS, shaped like live_check's and idempotence's own
# three-valued contracts (SCHEMA.md §5/§5.1):
#   seed_deployed    (exit 0) deploy exited 0, state artifact present,
#                             every live assert held -> trial proceeds
#   seed_absent      (exit 2) the deploy failed, the state artifact is
#                             missing, or a live assert RESOLVED and was
#                             CONTRADICTED -> trial aborts in _prepare
#   seed_unverifiable(exit 3) the proof could not be RUN at all -> aborts
#
# Both non-`seed_deployed` verdicts abort the trial rather than score it
# 0.0, and that is the strengthening, not an accident: a 0.0 is a
# MEASUREMENT -- it says the agent failed. A seed that never deployed
# produced no measurement at all, and recording it as 0.0 would repeat
# the defect this mechanism fixes with the sign flipped
# (docs/brownfield-seed-not-deployed.md).
#
# ScriptRunner downloads /logs/pre_invoke/ (step 4) BEFORE it checks the
# exit code (step 5), so seed-proof.json and stdout.log reach
# <trial_dir>/pre_invoke/ even on a failed seed: the operator always
# gets the reason.
fail() {   # fail <outcome> <reason> <exit-code>
  jq -n --arg o "$1" --arg r "$2" '{outcome:$o, reason:$r}' > "$PROOF" 2>/dev/null \
    || printf '{"outcome":"%s","reason":"%s"}\n' "$1" "$2" > "$PROOF"
  echo "SEED PROOF FAILED [$1]: $2" >&2
  exit "$3"
}

# REGION. The staged credentials file carries credential keys only, no
# arm Dockerfile sets this and no task.toml does -- without it every
# `aws` call below dies with exit 253 (`NoRegion`) BEFORE reaching AWS,
# which is indistinguishable from a real API error. Same two lines
# tests/test.sh now carries, for the same measured reason. `:=` so a
# region the harness DOES inject always wins.
: "${AWS_DEFAULT_REGION:=us-east-1}"
export AWS_DEFAULT_REGION

# THE PROOF HARNESS IS CHECKED BEFORE THE ACCOUNT IS TOUCHED (finding
# F, adversarial review round 3, 2026-08-25). Both lines below used to
# be unguarded, and the failure was the repo's signature shape: with
# _assert_lib.sh absent (ScriptRunner uploads pre_invoke/ at RUN time,
# so a partial upload or a future rename reaches this), the source
# failed SILENTLY, every `assert_check` became `command not found` ->
# rc 127, and the per-assert dispatch below bucketed 127 as
# CONTRADICTED. The run then exited 2 saying "the account does not hold
# EXACTLY the seed this workspace describes" -- a false statement about
# a real AWS account, in the one file whose job is to be believed.
#
# Ordered jq-guard -> source -> deploy ON PURPOSE: a broken proof
# harness must never spend against the account it then cannot check.
# `fail` itself degrades to a printf fallback when jq is missing, so
# this guard can still report its own verdict.
command -v jq >/dev/null 2>&1 \
  || fail seed_unverifiable "jq is not on PATH in this container -- the entire seed proof (this script's verdict file, the compiled live asserts, and _assert_lib.sh) is written in jq, so nothing below could be resolved. This is NOT a claim about the account (DECISIONS.md's agent-container baseline contract puts jq in every arm image; if it is missing, the image is wrong)" 3

# assert_check, byte-identical to the one tests/static_tiers.sh runs --
# ONE owner (gen.py::ASSERT_LIB_SH), two destinations. The seed proof and
# tier-0 must never disagree about what `eq` means.
. /pre_invoke/_assert_lib.sh \
  || fail seed_unverifiable "could not source /pre_invoke/_assert_lib.sh -- the live-assert runner this proof depends on is missing or unreadable, so no live assert below could be resolved. ScriptRunner uploads pre_invoke/ at RUN time, so this is a harness/upload fault, NOT a claim about the account" 3
command -v assert_check >/dev/null 2>&1 \
  || fail seed_unverifiable "/pre_invoke/_assert_lib.sh sourced without error but defined no assert_check function -- the proof harness is broken (a truncated upload, or a library that no longer owns this contract). NOT a claim about the account" 3

cd /app/project || fail seed_unverifiable "no /app/project in this container" 3

# ---- 1. DEPLOY -------------------------------------------------------
# The arm's OWN output_contract.deploy_command, verbatim -- the same
# per-arm declaration steps[].pre_invoke.deploy_prior consumes. The
# generator never guesses a deploy command (SCHEMA.md §2.4/§2.6/§2.7.1).
# ANTI-VACUITY LAYER 1: a non-zero exit raises ScriptExecutionError out
# of _prepare, and Trial.run's handler then NEVER calls _run() -- no
# agent phase, no verifier, no reward key at all.
echo "== seed deploy (terraconstructs) =="
if ! ( npx cdktn deploy --auto-approve internal-services-network ); then
  fail seed_absent "seed deploy command exited non-zero -- see stdout.log" 2
fi

# ---- 2. STATE PROOF (arm-specific) -----------------------------------
# ANTI-VACUITY LAYER 2: a toolchain can report success and leave nothing
# the next phase can use. See gen.py::SEED_STATE_PROOF.
[ -s /app/project/terraform.internal-services-network.tfstate ] \
  || fail seed_absent "no terraform state at /app/project/terraform.internal-services-network.tfstate after the seed deploy. That is cdktn's default LocalBackend path (path.join(process.cwd(), \`terraform.\${stackId}.tfstate\`)); if the deploy reported success, capture 'find /app/project -iname \"*.tfstate*\"' before believing this path is still right" 2
# SEED STATE IDENTITY (finding H). Stamped into the receipt below and
# re-read by tests/test.sh's idempotence tier, which must be able to
# tell the agent's OWN converged state from the one this script just
# deployed. See gen.py::SEED_STATE_IDENTITY_JQ for why these fields.
seed_state_identity="$(jq -er '"lineage=" + (.lineage|strings) + ";serial=" + (.serial|numbers|tostring)' /app/project/terraform.internal-services-network.tfstate 2>/logs/pre_invoke/seed-identity.err)" \
  || fail seed_unverifiable "the seed deployed and its state artifact is present, but no state IDENTITY could be read out of it (/app/project/terraform.internal-services-network.tfstate): $(head -c 400 /logs/pre_invoke/seed-identity.err). tests/test.sh's idempotence tier needs that identity to tell an agent that actually deployed from one that inherited this seed's convergence, so a seed without it is not measurable" 3

# ---- 3. LIVE PROOF (arm-AGNOSTIC) ------------------------------------
# ANTI-VACUITY LAYER 3: workspace_seed.deploy.live_asserts, resolved
# against real AWS CLI responses. Arm-agnostic on purpose -- the account
# does not know which arm produced its resources, the same principle
# that makes tests/live_check.py byte-identical across all three arms.
# TWO counters, not one (finding m4). `failures` counts asserts that
# resolved and were CONTRADICTED -- assert_check rc 1, and ONLY rc 1.
# `unresolvable` counts everything else non-zero: rc 2 (the query could
# not be run) and any rc outside _assert_lib.sh's documented (0, 1, 2),
# which is a broken proof harness rather than a wrong account (finding
# F, round 3). Collapsing them told the operator the account was wrong
# when the proof simply did not resolve -- a lie about a real account,
# in the one file whose whole job is to be believed.
failures=0
unresolvable=0

# [old-group-is-live] The security group the change request renames
#   exists in the account RIGHT NOW, and it is the ONLY group by that
#   name. This is the exact negation of live_check.py's own
#   discriminating assertion ("no group named `internal-services-ssm-
#   endpoint` remains"). If this is false pre-agent, that assertion is
#   satisfied vacuously and the live oracle reports `pass` while proving
#   nothing — which is precisely the defect docs/brownfield-seed-not-
#   deployed.md was filed for.
if ! aws ec2 describe-security-groups --filters Name=group-name,Values=internal-services-ssm-endpoint --output json > /logs/pre_invoke/seed-01.json 2>/logs/pre_invoke/seed-01.err; then
  fail seed_unverifiable "aws call for [old-group-is-live] failed: $(head -c 400 /logs/pre_invoke/seed-01.err)" 3
fi
rc=0
assert_check old-group-is-live '.SecurityGroups | .[] | .GroupName' eq '"internal-services-ssm-endpoint"' /logs/pre_invoke/seed-01.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [old-group-is-live] assert_check exited $rc, which is outside _assert_lib.sh's documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [endpoint-holds-the-old-group] This account holds EXACTLY ONE
#   security-group attachment on exactly one interface VPC endpoint, and
#   it is THE old group. That attachment is the dependency that turns
#   the rename's destroy into a DependencyViolation; without it the trap
#   is inert even with the group deployed. Exactly one, not "at least
#   one": a second, identically named attachment left behind by a failed
#   reset would make the trap fire on the wrong object and score a
#   correct agent 0.0. Deliberately reads the attached groups and NOT
#   `State`: an interface endpoint can still be `pending` at the moment
#   `apply` returns, and the generator has no poll primitive today
#   (design §12 risk 3) — the attachment, unlike the state, is true the
#   instant the endpoint object exists.
if ! aws ec2 describe-vpc-endpoints --filters Name=vpc-endpoint-type,Values=Interface --output json > /logs/pre_invoke/seed-02.json 2>/logs/pre_invoke/seed-02.err; then
  fail seed_unverifiable "aws call for [endpoint-holds-the-old-group] failed: $(head -c 400 /logs/pre_invoke/seed-02.err)" 3
fi
rc=0
assert_check endpoint-holds-the-old-group '.VpcEndpoints | .[] | .Groups | .[] | .GroupName' eq '"internal-services-ssm-endpoint"' /logs/pre_invoke/seed-02.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [endpoint-holds-the-old-group] assert_check exited $rc, which is outside _assert_lib.sh's documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# UNRESOLVABLE IS CHECKED FIRST, and the order is the point: if even one
# assert could not be asked, this run has no standing to say the account
# "does not hold the seed" -- it does not know.
[ "$unresolvable" -eq 0 ] || fail seed_unverifiable \
  "$unresolvable seed live assert(s) could not be resolved at all (malformed or unexpected AWS response, or jq missing) -- see the seed-NN.json/.err probes downloaded beside this file. This is NOT a claim about the account" 3

[ "$failures" -eq 0 ] || fail seed_absent \
  "$failures seed live assert(s) resolved and were CONTRADICTED -- the account does not hold EXACTLY the seed this workspace describes. Read the assert's own resolved= line above before concluding the seed is MISSING: an exact-count op (eq) is contradicted by zero resolved nodes AND by more than one, and the second case is a STRAY leftover object from an incompletely-reset earlier trial (aws_trial.py::_reset_scenario_account logs a reset failure and never raises). Both make this trial unmeasurable, which is why both abort" 2

# ---- 4. RECEIPT ------------------------------------------------------
# THE ONE ARTIFACT THAT OUTLIVES THIS SCRIPT (finding M3, adversarial
# review 2026-08-25). Every anti-vacuity layer above lives INSIDE a file
# that a trial only runs if it is on disk: aws_trial.py:303 is a bare
# `if self.task.has_phase_script(ScriptType.PRE_INVOKE):` with no else
# and no logging, and has_phase_script is pure file existence
# (aws_bench/dataset/task_config.py:175-177). A dropped pre_invoke/
# directory -- a bad image layer, a task tree built by a stale
# generator, an upload that lost a subdirectory -- therefore skipped
# the ENTIRE mechanism in silence and handed the verifier an empty
# account, on which live_check.py's discriminating assertion passes for
# free all over again. That is the original defect, restored by a
# missing file.
#
# So the VERIFIER -- the one component that always runs -- is told to
# look for this receipt and to refuse to grade without it (see
# gen.py::build_test_sh's SPEC_SEED_DEPLOY_REQUIRED block; the env key
# is written into [verifier].env by the same generator branch that
# emits this script).
#
# It CANNOT be /logs/pre_invoke/seed-proof.json: ScriptRunner deletes
# that whole directory in step 7, before the agent phase -- read in
# aws_bench/task/script_runner.py, not assumed. /logs itself is the
# harness's own directory, created by ScriptRunner (step 2, as root)
# and untouched by step 7, and the verifier runs in this same container
# (shared verifier mode is mandatory here --
# aws_bench/dataset/task_config.py::_validate_layout rejects separate
# verifier environments outright), so a file written here is readable
# by tests/test.sh.
#
# Written BEFORE placeholder.json: if this write fails (a root-owned
# /logs under a non-root script user -- see generate_arm's Dockerfile
# USER guard) the seed must fail LOUDLY here, not succeed into a
# verifier that will refuse it later.
# `state_identity` (finding H, round 3): the identity of the state THIS
# script just deployed, which tests/test.sh's idempotence tier compares
# against the state it finds after the agent phase. Unchanged means the
# agent applied NOTHING and would otherwise have inherited the seed's
# own convergence as a `converged` verdict. See SEED_STATE_IDENTITY_JQ.
jq -n --arg identity "$seed_state_identity" \
  '{outcome:"seed_deployed", scenario:"named-resource-replacement", arm:"terraconstructs", state_identity:$identity}' \
  > /logs/seed-deploy-receipt.json \
  || fail seed_unverifiable "could not write the seed receipt to /logs/seed-deploy-receipt.json -- the verifier fails closed without it" 3

# ---- 5. DECLARE ------------------------------------------------------
# Probe leftovers first (finding m2): _assert_lib.sh writes its jq
# stderr to /tmp/assert-jq-err.txt, which step 7's cleanup does not
# reach. That library is SHARED with tier-0, so its path is NOT changed
# there; it is cleaned up here instead, where the agent is the next
# reader of this filesystem. Best-effort -- a leftover scratch file must
# never turn a deployed, proven seed into an aborted trial.
rm -f /tmp/assert-jq-err.txt || true

# placeholder.json LAST, and only on success: ScriptRunner checks the
# exit code (step 5) before it looks for the result file (step 6), so a
# failing seed surfaces as ScriptExecutionError rather than the more
# confusing ScriptResultFileNotFoundError. `{}` is its own documented
# "no values to return".
jq -n '{outcome:"seed_deployed"}' > "$PROOF"
printf '{}\n' > /logs/pre_invoke/placeholder.json
