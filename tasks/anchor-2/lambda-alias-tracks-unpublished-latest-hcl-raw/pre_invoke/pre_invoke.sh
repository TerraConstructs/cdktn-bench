#!/usr/bin/env bash
# Generated -- generator/gen.py::build_seed_pre_invoke_sh, from
# specs/lambda-alias-tracks-unpublished-latest.yaml's workspace_seed.deploy (specs/SCHEMA.md §2.7.1),
# hcl_raw arm. Do not hand-edit; regenerate instead
# (`make gen SPEC=specs/lambda-alias-tracks-unpublished-latest.yaml`).
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
echo "== seed deploy (hcl_raw) =="
if ! ( terraform init -input=false && terraform apply -input=false -auto-approve ); then
  fail seed_absent "seed deploy command exited non-zero -- see stdout.log" 2
fi

# ---- 2. STATE PROOF (arm-specific) -----------------------------------
# ANTI-VACUITY LAYER 2: a toolchain can report success and leave nothing
# the next phase can use. See gen.py::SEED_STATE_PROOF.
[ -s /app/project/terraform.tfstate ] \
  || fail seed_absent "no terraform state at /app/project/terraform.tfstate after the seed apply -- the agent's own terraform would treat this workspace as greenfield, which is the exact brownfield premise this deploy exists to make true" 2
# SEED STATE IDENTITY (finding H). Stamped into the receipt below and
# re-read by tests/test.sh's idempotence tier, which must be able to
# tell the agent's OWN converged state from the one this script just
# deployed. See gen.py::SEED_STATE_IDENTITY_JQ for why these fields.
seed_state_identity="$(jq -er '"lineage=" + (.lineage|strings) + ";serial=" + (.serial|numbers|tostring)' /app/project/terraform.tfstate 2>/logs/pre_invoke/seed-identity.err)" \
  || fail seed_unverifiable "the seed deployed and its state artifact is present, but no state IDENTITY could be read out of it (/app/project/terraform.tfstate): $(head -c 400 /logs/pre_invoke/seed-identity.err). tests/test.sh's idempotence tier needs that identity to tell an agent that actually deployed from one that inherited this seed's convergence, so a seed without it is not measurable" 3

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

# [the-live-alias-resolves-to-version-one] The function this workspace
#   describes has EXACTLY ONE alias in the account, and it names version
#   `1`. Deliberately name-INDEPENDENT -- `$.Aliases[*]`, not a
#   `[?(@.Name==...)]` filter -- because the alias's physical name is
#   composed by the L2 on terraconstructs and typed literally on the
#   other two arms, and a live assert that had to know which arm
#   produced the account would be the one thing §2.7.1 says a live
#   assert must never be. Reading every alias and requiring exactly one
#   is also strictly STRONGER than filtering by name: a stray second
#   alias left behind by an incomplete reset fails here instead of being
#   filtered out of view. This is the exact precondition that makes the
#   trap ARMED: version 1 is the snapshot the seed published, and the
#   alias will keep naming it unless the agent changes what the alias is
#   wired to. If this is false pre-agent there is nothing to be behind,
#   and `tests/live_check.py`'s verdict means nothing whichever way it
#   comes out.
if ! aws lambda list-aliases --function-name cdktn-bench-quote-service --output json > /logs/pre_invoke/seed-01.json 2>/logs/pre_invoke/seed-01.err; then
  fail seed_unverifiable "aws call for [the-live-alias-resolves-to-version-one] failed: $(head -c 400 /logs/pre_invoke/seed-01.err)" 3
fi
rc=0
assert_check the-live-alias-resolves-to-version-one '.Aliases | .[] | .FunctionVersion' eq '"1"' /logs/pre_invoke/seed-01.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [the-live-alias-resolves-to-version-one] assert_check exited $rc, which is outside _assert_lib.sh's documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [version-one-still-carries-the-configuration-being-changed] Version 1
#   -- the version the assert above proves the alias names -- carries
#   the configuration the change request supersedes. It also proves the
#   snapshot semantics this whole scenario depends on are real in this
#   account: version 1 froze the environment the seed deployed with, and
#   reading it back returns that frozen value rather than the function's
#   current one. WHAT THIS ASSERT DOES AND DOES NOT DO, stated precisely
#   because the honest version is weaker than the tempting one.
#   `tests/live_check.py` passes a trial iff the alias resolves to
#   `QUOTE_CURRENCY=USD`. The exact negation of that clause -- "pre-
#   agent the alias resolves to EUR" -- is the CONJUNCTION of this
#   assert and `the-live-alias-resolves-to-version-one`, not this assert
#   alone. On its own this one does NOT flip after a correct solution,
#   and that is not a defect but arithmetic: a published version is
#   immutable, so version 1 still says EUR in the post-solution account
#   too. Executed against hand-built AWS responses at authoring time
#   (2026-08-26) through the real `_assert_lib.sh::assert_check` and the
#   real compiled jq filter: armed account rc=0, post-solution account
#   rc=0, EMPTY account rc=1. It is therefore genuinely falsifiable --
#   an account without the seed contradicts it -- while the assert above
#   is the one that separates armed from disarmed.
if ! aws lambda list-versions-by-function --function-name cdktn-bench-quote-service --output json > /logs/pre_invoke/seed-02.json 2>/logs/pre_invoke/seed-02.err; then
  fail seed_unverifiable "aws call for [version-one-still-carries-the-configuration-being-changed] failed: $(head -c 400 /logs/pre_invoke/seed-02.err)" 3
fi
rc=0
assert_check version-one-still-carries-the-configuration-being-changed '.Versions | .[] | select(.Version=="1") | .Environment.Variables.QUOTE_CURRENCY' eq '"EUR"' /logs/pre_invoke/seed-02.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [version-one-still-carries-the-configuration-being-changed] assert_check exited $rc, which is outside _assert_lib.sh's documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [exactly-one-numbered-version-has-been-published] The function holds
#   `$LATEST` and version `1` and NOTHING ELSE. Two different
#   contaminations are refused by this one claim, and both are the kind
#   that corrupt a measurement silently rather than loudly: (a) a
#   leftover function from an incompletely-reset earlier trial
#   (aws_trial.py::_reset_scenario_account only flags contamination when
#   the reset itself reports failure) would carry versions 2, 3, ... and
#   the agent's change would land on top of somebody else's history; (b)
#   a seed deploy that somehow ran twice would publish a version 2 that
#   the alias does not name, making the post-agent account
#   indistinguishable from a half-solved one. `set_eq` rather than `eq`
#   because this IS a genuinely multi-valued claim, and its documented
#   `unique` hazard cannot bite here: version identifiers are unique per
#   function by construction, and this query is scoped to one function
#   name, so no two resolved nodes can carry the same value. Executed
#   against hand-built AWS responses at authoring time (2026-08-26)
#   through the real `_assert_lib.sh::assert_check` and the real
#   compiled jq filter: armed account rc=0, post-solution account (a
#   version 2 exists) rc=1, contaminated account (versions 1 and 2, both
#   still EUR) rc=1, EMPTY account rc=1.
if ! aws lambda list-versions-by-function --function-name cdktn-bench-quote-service --output json > /logs/pre_invoke/seed-03.json 2>/logs/pre_invoke/seed-03.err; then
  fail seed_unverifiable "aws call for [exactly-one-numbered-version-has-been-published] failed: $(head -c 400 /logs/pre_invoke/seed-03.err)" 3
fi
rc=0
assert_check exactly-one-numbered-version-has-been-published '.Versions | .[] | .Version' set_eq '["$LATEST", "1"]' /logs/pre_invoke/seed-03.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [exactly-one-numbered-version-has-been-published] assert_check exited $rc, which is outside _assert_lib.sh's documented {0,1,2} -- counted as UNRESOLVABLE" >&2
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
  '{outcome:"seed_deployed", scenario:"lambda-alias-tracks-unpublished-latest", arm:"hcl_raw", state_identity:$identity}' \
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
