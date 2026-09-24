#!/usr/bin/env bash
# Generated -- generator/gen.py::build_seed_pre_invoke_sh, from
# specs/s3-acl-vs-object-ownership-log-delivery.yaml's workspace_seed.deploy (specs/SCHEMA.md §2.7.1),
# hcl_modules arm. Do not hand-edit; regenerate instead
# (`make gen SPEC=specs/s3-acl-vs-object-ownership-log-delivery.yaml`).
#
# HARNESS ACTION, not agent work. Run by
# aws_bench/task/aws_trial.py::AwsBenchSingleStepTrial._prepare inside
# the AGENT container, after the container is up and BEFORE the agent's
# first token, with ~/.aws/credentials staged for
# [scenario].pre_invoke_role_name. Its job is to make
# workspace_seed.premise's "it is already deployed in this account" TRUE
# -- and then to prove it, three ways, fail-closed.
#
# WHAT IS ACTUALLY GUARANTEED ABOUT WHAT THE AGENT SEES. The
# guarantee is exactly what ScriptRunner removes, and nothing wider:
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
#   seed never ran fails CLOSED instead of grading an empty account.
#   It is one JSON object under /logs, a harness
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

# THE PROOF HARNESS IS CHECKED BEFORE THE ACCOUNT IS TOUCHED.
# Unguarded, a missing or unrunnable runner (ScriptRunner uploads
# pre_invoke/ at RUN time, so a partial upload or a rename reaches
# this) makes every assert exit outside the three-valued contract, and
# the dispatch below buckets anything it does not recognise as
# CONTRADICTED: the script would exit 2 saying "the account does not
# hold EXACTLY the seed this workspace describes", a false statement
# about a real AWS account in the one file whose job is to be believed.
#
# Ordered jq-guard -> python3-guard -> ops.py selftest -> deploy: a
# broken proof harness must never spend against the account it then
# cannot check. `fail` degrades to a printf fallback when jq is
# missing, so the first guard can still report its own verdict.
#
# THE SELFTEST IS THE LOAD-BEARING ONE: a truncated ops.py is a file
# that ignores its own argv and exits 0, which the dispatch reads as
# "held" -- a seed announced as proven that was never checked. So its
# STDOUT is compared, as a whole string, against the one line only a
# driver that really resolved one assert per outcome through jq can
# print. Exiting 0 proves nothing here; answering does.
command -v jq >/dev/null 2>&1 \
  || fail seed_unverifiable "jq is not on PATH in this container -- this script's verdict file, the seed receipt and every compiled live assert are resolved through jq, so nothing below could be resolved. This is NOT a claim about the account (DECISIONS.md's agent-container baseline contract puts jq in every arm image; if it is missing, the image is wrong)" 3
command -v python3 >/dev/null 2>&1 \
  || fail seed_unverifiable "python3 is not on PATH in this container -- /pre_invoke/ops.py is the live-assert runner this proof depends on, so no live assert below could be resolved. This is NOT a claim about the account (DECISIONS.md's agent-container baseline contract puts python3 in every arm image; if it is missing, the image is wrong)" 3

# ops.py, byte-identical to the one tests/static_tiers.sh's tier-0
# driver imports -- ONE owner (gen.py::OPS_PY), two destinations. The
# seed proof and tier-0 must never disagree about what `eq` means.
[ -f /pre_invoke/ops.py ] \
  || fail seed_unverifiable "/pre_invoke/ops.py is not there -- the live-assert runner this proof depends on is missing, so no live assert below could be resolved. ScriptRunner uploads pre_invoke/ at RUN time, so this is a harness/upload fault, NOT a claim about the account" 3
[ "$(python3 /pre_invoke/ops.py --selftest 2>/dev/null)" = "OPS_SELFTEST_OK" ] \
  || fail seed_unverifiable "/pre_invoke/ops.py did not answer its own --selftest with OPS_SELFTEST_OK, so it cannot be trusted to resolve a live assert (a truncated upload, a python3 that cannot run it, or a jq it cannot drive). NOT a claim about the account" 3

cd /app/project || fail seed_unverifiable "no /app/project in this container" 3

# ---- 1. DEPLOY -------------------------------------------------------
# The arm's OWN output_contract.deploy_command, verbatim -- the same
# per-arm declaration steps[].pre_invoke.deploy_prior consumes. The
# generator never guesses a deploy command (SCHEMA.md §2.4/§2.6/§2.7.1).
# ANTI-VACUITY LAYER 1: a non-zero exit raises ScriptExecutionError out
# of _prepare, and Trial.run's handler then NEVER calls _run() -- no
# agent phase, no verifier, no reward key at all.
echo "== seed deploy (hcl_modules) =="
if ! ( terraform init -input=false && terraform apply -input=false -auto-approve ); then
  fail seed_absent "seed deploy command exited non-zero -- see stdout.log" 2
fi

# ---- 2. STATE PROOF (arm-specific) -----------------------------------
# ANTI-VACUITY LAYER 2: a toolchain can report success and leave nothing
# the next phase can use. See gen.py::SEED_STATE_PROOF.
[ -s /app/project/terraform.tfstate ] \
  || fail seed_absent "no terraform state at /app/project/terraform.tfstate after the seed apply -- the agent's own terraform would treat this workspace as greenfield, which is the exact brownfield premise this deploy exists to make true" 2
# SEED STATE IDENTITY. Stamped into the receipt below and
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
# TWO counters, never one. `failures` counts asserts that resolved and
# were CONTRADICTED -- ops.py rc 1, and ONLY rc 1. `unresolvable`
# counts everything else non-zero: rc 2 (the query could not be run)
# and any rc outside ops.py's documented {0,1,2}, which is a broken
# proof harness rather than a wrong account. Collapsing them would tell
# the operator the account is wrong when the proof simply did not
# resolve -- a lie about a real account, in the one file whose whole
# job is to be believed.
failures=0
unresolvable=0

# [destination-bucket-acl-grants-the-log-delivery-group] THE POISON IS
#   LIVE. The destination bucket's real, deployed ACL grants the S3 log
#   delivery group. This is the exact negation of what
#   `tests/live_check.py` requires after the agent is done (ACLs
#   disabled and the grant carried by a bucket policy instead), so if
#   THIS is false pre-agent the live oracle is reporting on a system
#   that was never in the state the scenario is about. `set_eq` and not
#   `eq` here, deliberately and against the general preference SCHEMA.md
#   §2.7.1 states: the canned `log-delivery-write` ACL is TWO grants
#   (WRITE and READ_ACP) to the SAME grantee URI, so the path resolves
#   to two identical nodes and `eq`'s "exactly one node" rule would fail
#   against a correct seed. The duplicate-collapse hazard `eq` exists to
#   prevent does not apply, because this query names ONE bucket by its
#   globally unique name rather than scanning an account -- there is no
#   second object for `unique` to swallow. The owner's own FULL_CONTROL
#   grant has no `Grantee.URI` at all, so it resolves to `null` and is
#   dropped by `assert_check`'s `map(select(. != null))`; on a bucket
#   with ACLs already disabled the ONLY grant is that owner grant, so
#   the path resolves to zero nodes and `set_eq` against a non-empty
#   expected fails -- which is the discrimination this assert is for.
if ! aws s3api get-bucket-acl --bucket cdktn-bench-application-storage-access-logs --output json > /logs/pre_invoke/seed-01.json 2>/logs/pre_invoke/seed-01.err; then
  fail seed_unverifiable "aws call for [destination-bucket-acl-grants-the-log-delivery-group] failed: $(head -c 400 /logs/pre_invoke/seed-01.err)" 3
fi
rc=0
python3 /pre_invoke/ops.py --one destination-bucket-acl-grants-the-log-delivery-group '.Grants | .[] | .Grantee.URI' set_eq '["http://acs.amazonaws.com/groups/s3/LogDelivery"]' /logs/pre_invoke/seed-01.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [destination-bucket-acl-grants-the-log-delivery-group] ops.py exited $rc, which is outside its documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [destination-bucket-object-ownership-still-allows-acls] The deployed
#   Object Ownership setting is `ObjectWriter`, i.e. ACLs are enabled
#   and the grant above is actually in force rather than being an inert
#   leftover. Without this, an account whose bucket had ACLs disabled by
#   some earlier process would satisfy the assert above only if the
#   grant somehow survived -- and would make the agent's entire job
#   already done. `eq` pins the node COUNT to exactly one, so a response
#   carrying two ownership rules is a failure rather than a coin toss.
if ! aws s3api get-bucket-ownership-controls --bucket cdktn-bench-application-storage-access-logs --output json > /logs/pre_invoke/seed-02.json 2>/logs/pre_invoke/seed-02.err; then
  fail seed_unverifiable "aws call for [destination-bucket-object-ownership-still-allows-acls] failed: $(head -c 400 /logs/pre_invoke/seed-02.err)" 3
fi
rc=0
python3 /pre_invoke/ops.py --one destination-bucket-object-ownership-still-allows-acls '.OwnershipControls.Rules | .[] | .ObjectOwnership' eq '"ObjectWriter"' /logs/pre_invoke/seed-02.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [destination-bucket-object-ownership-still-allows-acls] ops.py exited $rc, which is outside its documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [application-bucket-really-ships-its-access-logs-here] The source half
#   of the system exists in the account: the application bucket's
#   deployed logging configuration names THIS destination bucket.
#   Without it, `live_check.py`'s "logging still targets the destination
#   bucket" clause could be satisfied vacuously by an account where
#   logging was never configured and the agent never touched it.
#   `--query` is used because `GetBucketLogging`'s response is a bare
#   OBJECT (`{"LoggingEnabled": {"TargetBucket": ..., "TargetPrefix":
#   ...}}`) with no array anywhere in it, and §2.7.1's anti-vacuity PATH
#   rule requires the jsonpath to ITERATE a collection --
#   `$.LoggingEnabled .TargetBucket` compiles to a filter with no `.[]`
#   stage and is a hard error at spec load. Wrapping the projection in a
#   one-element JMESPath list produces `["<bucket>"]`, which `$[*]`
#   iterates, and which resolves to `[null]` -> zero nodes (dropped by
#   `map(select(. != null))`) when logging is NOT configured. `--query`
#   is not on §2.7.1's harness-owned reject list (`--profile`,
#   `--region`, `--endpoint-url`, `--output`) and does not change the
#   output FORMAT, which the compiled jq filter depends on.
if ! aws s3api get-bucket-logging --bucket cdktn-bench-application-storage-app-data --query '[LoggingEnabled.TargetBucket]' --output json > /logs/pre_invoke/seed-03.json 2>/logs/pre_invoke/seed-03.err; then
  fail seed_unverifiable "aws call for [application-bucket-really-ships-its-access-logs-here] failed: $(head -c 400 /logs/pre_invoke/seed-03.err)" 3
fi
rc=0
python3 /pre_invoke/ops.py --one application-bucket-really-ships-its-access-logs-here '.[]' eq '"cdktn-bench-application-storage-access-logs"' /logs/pre_invoke/seed-03.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [application-bucket-really-ships-its-access-logs-here] ops.py exited $rc, which is outside its documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# [access-logs-land-under-the-app-data-prefix] The prefix half of the
#   same deployed fact, split into its own assert rather than folded
#   into a `set_eq` with the bucket name: `eq` pins exactly one node per
#   fact, and a `set_eq` over two projected values would pass if the two
#   were swapped. The bucket-policy grant a correct solution writes must
#   cover exactly this prefix, so a seed whose deployed prefix is not
#   `app-data/` would make the live oracle grade against the wrong key
#   space.
if ! aws s3api get-bucket-logging --bucket cdktn-bench-application-storage-app-data --query '[LoggingEnabled.TargetPrefix]' --output json > /logs/pre_invoke/seed-04.json 2>/logs/pre_invoke/seed-04.err; then
  fail seed_unverifiable "aws call for [access-logs-land-under-the-app-data-prefix] failed: $(head -c 400 /logs/pre_invoke/seed-04.err)" 3
fi
rc=0
python3 /pre_invoke/ops.py --one access-logs-land-under-the-app-data-prefix '.[]' eq '"app-data/"' /logs/pre_invoke/seed-04.json || rc=$?
if [ "$rc" -eq 0 ]; then
  :
elif [ "$rc" -eq 1 ]; then
  failures=$((failures + 1))
else
  unresolvable=$((unresolvable + 1))
  echo "  [access-logs-land-under-the-app-data-prefix] ops.py exited $rc, which is outside its documented {0,1,2} -- counted as UNRESOLVABLE" >&2
fi

# UNRESOLVABLE IS CHECKED FIRST, and the order is the point: if even one
# assert could not be asked, this run has no standing to say the account
# "does not hold the seed" -- it does not know.
[ "$unresolvable" -eq 0 ] || fail seed_unverifiable \
  "$unresolvable seed live assert(s) could not be resolved at all (malformed or unexpected AWS response, or jq missing) -- see the seed-NN.json/.err probes downloaded beside this file. This is NOT a claim about the account" 3

[ "$failures" -eq 0 ] || fail seed_absent \
  "$failures seed live assert(s) resolved and were CONTRADICTED -- the account does not hold EXACTLY the seed this workspace describes. Read the assert's own resolved= line above before concluding the seed is MISSING: an exact-count op (eq) is contradicted by zero resolved nodes AND by more than one, and the second case is a STRAY leftover object from an incompletely-reset earlier trial (aws_trial.py::_reset_scenario_account logs a reset failure and never raises). Both make this trial unmeasurable, which is why both abort" 2

# ---- 4. RECEIPT ------------------------------------------------------
# THE ONE ARTIFACT THAT OUTLIVES THIS SCRIPT. Every anti-vacuity layer
# above lives INSIDE a file that a trial only runs if it is on disk:
# aws_trial.py:303 is a bare
# `if self.task.has_phase_script(ScriptType.PRE_INVOKE):` with no else
# and no logging, and has_phase_script is pure file existence
# (aws_bench/dataset/task_config.py:175-177). A dropped pre_invoke/
# directory -- a bad image layer, a task tree built by a stale
# generator, an upload that lost a subdirectory -- therefore skips the
# ENTIRE mechanism in silence and hands the verifier an empty account,
# on which live_check.py's discriminating assertion passes for free.
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
# `state_identity`: the identity of the state THIS
# script just deployed, which tests/test.sh's idempotence tier compares
# against the state it finds after the agent phase. Unchanged means the
# agent applied NOTHING and would otherwise have inherited the seed's
# own convergence as a `converged` verdict. See SEED_STATE_IDENTITY_JQ.
jq -n --arg identity "$seed_state_identity" \
  '{outcome:"seed_deployed", scenario:"s3-acl-vs-object-ownership-log-delivery", arm:"hcl_modules", state_identity:$identity}' \
  > /logs/seed-deploy-receipt.json \
  || fail seed_unverifiable "could not write the seed receipt to /logs/seed-deploy-receipt.json -- the verifier fails closed without it" 3

# ---- 5. DECLARE ------------------------------------------------------
# placeholder.json LAST, and only on success: ScriptRunner checks the
# exit code (step 5) before it looks for the result file (step 6), so a
# failing seed surfaces as ScriptExecutionError rather than the more
# confusing ScriptResultFileNotFoundError. `{}` is its own documented
# "no values to return".
jq -n '{outcome:"seed_deployed"}' > "$PROOF"
printf '{}\n' > /logs/pre_invoke/placeholder.json
