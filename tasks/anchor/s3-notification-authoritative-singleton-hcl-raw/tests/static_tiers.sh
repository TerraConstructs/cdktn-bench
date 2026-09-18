#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/s3-notification-authoritative-singleton.yaml.
# Tier-0/1 static verifier for the hcl_raw arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/s3-notification-authoritative-singleton.yaml`).
#
# Reward contract (reused from tasks/anchor/smoke/tests/test.sh):
# writes a bare float to /logs/verifier/reward.txt
# (harbor/verifier/verifier.py::_parse_reward_text).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_assert_lib.sh"
mkdir -p /logs/verifier
: "${AWS_DEFAULT_REGION:=us-east-1}"
export AWS_DEFAULT_REGION
rm -f /logs/verifier/aws-unavailable /logs/verifier/aws-unavailable.json
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  {
    echo "aws-unavailable: 'aws sts get-caller-identity' failed --"
    echo "no working AWS credentials in this environment. This is a"
    echo "run-invalidating test-infrastructure condition, NOT a bad"
    echo "solution -- no toolchain command was ever attempted."
  } | tee /logs/verifier/aws-unavailable
  jq -n \
    '{outcome: "run_invalid", status: "run_invalid", reason: "aws sts get-caller-identity failed -- no working AWS credentials in this environment"}' \
    > /logs/verifier/aws-unavailable.json 2>/dev/null \
    || echo '{"outcome":"run_invalid","status":"run_invalid","reason":"aws credentials unavailable"}' > /logs/verifier/aws-unavailable.json
  exit 1
fi

cd /app/project

echo '== plan: terraform init && terraform validate && terraform plan -out=plan.tfplan && terraform show -json plan.tfplan > plan.json =='
if ! ( terraform init && terraform validate && terraform plan -out=plan.tfplan && terraform show -json plan.tfplan > plan.json ); then
  echo "PLAN FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

ARTIFACT="/app/project/plan.json"
if [ ! -s "$ARTIFACT" ]; then
  echo "MISSING ARTIFACT: $ARTIFACT"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo
echo "== tier-0: structural asserts (7 applicable) =="
tier0_pass=1
assert_check s3-bucket-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket")' exists null "$ARTIFACT" || tier0_pass=0
assert_check lambda-function-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_lambda_function")' exists null "$ARTIFACT" || tier0_pass=0
assert_check sns-topic-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_sns_topic")' exists null "$ARTIFACT" || tier0_pass=0
assert_check object-created-notification-targets-a-lambda '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_notification") | .values.lambda_function | .[] | .events' in '["s3:ObjectCreated:*", "s3:ObjectCreated:Put", "s3:ObjectCreated:Post", "s3:ObjectCreated:Copy", "s3:ObjectCreated:CompleteMultipartUpload"]' "$ARTIFACT" || tier0_pass=0
assert_check object-removed-notification-targets-a-topic '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_notification") | .values.topic | .[] | .events' in '["s3:ObjectRemoved:*", "s3:ObjectRemoved:Delete", "s3:ObjectRemoved:DeleteMarkerCreated", "s3:LifecycleExpiration:*", "s3:LifecycleExpiration:Delete", "s3:LifecycleExpiration:DeleteMarkerCreated"]' "$ARTIFACT" || tier0_pass=0
assert_check exactly-one-notification-resource-per-bucket-tf '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_notification") | .type' eq '"aws_s3_bucket_notification"' "$ARTIFACT" || tier0_pass=0
assert_check lambda-permission-principal-is-s3 '.planned_values.root_module.resources | .[] | select(.type=="aws_lambda_permission") | .values.principal' eq '"s3.amazonaws.com"' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: OPA/Rego =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: lambda-permission-scoped-to-bucket-tf, sns-topic-policy-allows-s3-publish-tf, audit-topic-events-cover-a-real-delete
POLICY="$DIR/policy.rego"
# --- tier-1 input: plan JSON + the agent's own parsed .tf files ------
# (oracle.hcl_traversal, specs/SCHEMA.md §4.6). See generator/gen.py's
# build_hcl_merge_py() and the block comment above the tier-1 rego
# branch for why this exists, why the glob is here and not in the
# policy, and why every failure below is loud rather than a score.
HCL_LIB="$DIR/hcl_traversal.rego"
HCL_MERGE_PY="$DIR/hcl_merge.py"
HCL_MERGED="/logs/verifier/oracle-input.json"
HCL_MERGE_STATUS="OK"
if ! command -v hcl2json >/dev/null 2>&1; then
  HCL_MERGE_STATUS="TOOL_MISSING"
elif [ ! -f "$HCL_LIB" ]; then
  HCL_MERGE_STATUS="LIB_MISSING"
  echo "shared traversal library not found at $HCL_LIB" \
    > /logs/verifier/tier1-hcl-merge.log
elif [ ! -f "$HCL_MERGE_PY" ]; then
  # Same class as LIB_MISSING and reported through the same status: the
  # pre-parser is part of the oracle, and a task dir missing it can only
  # produce an unreadable document, never a judgement about a solution.
  HCL_MERGE_STATUS="LIB_MISSING"
  echo "HCL pre-parser not found at $HCL_MERGE_PY" \
    > /logs/verifier/tier1-hcl-merge.log
elif python3 "$HCL_MERGE_PY" "$ARTIFACT" "$HCL_MERGED" \
      > /logs/verifier/tier1-hcl-merge.log 2>&1
then
  # Every rule that ever read `input` keeps reading the same bytes;
  # the document just carries one extra top-level key now.
  ARTIFACT="$HCL_MERGED"
else
  HCL_MERGE_STATUS="PARSE_FAILED"
fi
HAS_TIER1_ASSERTS=true
tier1_status="SKIPPED_NO_ASSERTS"
if [ "$HAS_TIER1_ASSERTS" = "true" ]; then
  if ! command -v opa >/dev/null 2>&1; then
    tier1_status="TOOL_MISSING"
    {
      echo "opa is not installed in this image, but this scenario"
      echo "declares tier-1 structural_asserts -- this is a"
      echo "run-invalidating condition, not a silent pass."
    } | tee /logs/verifier/tier1-unavailable
  elif is_stub_policy "$POLICY"; then
    tier1_status="SKIPPED_STUB"
    {
      echo "  SKIPPED_STUB: $POLICY is still a generator stub (hand-authored in Slice D)."
      echo "this scenario declares tier-1 structural_asserts, but its tier-1"
      echo "policy is not yet hand-authored -- this is a run-invalidating"
      echo "condition (an un-authored scenario cannot be graded), not a silent pass."
    } | tee /logs/verifier/tier1-unauthored
  elif [ "$HCL_MERGE_STATUS" = "TOOL_MISSING" ]; then
    tier1_status="TOOL_MISSING"
    {
      echo "hcl2json is not installed in this image, but this scenario's"
      echo "tier-1 oracle resolves HCL symbols (oracle.hcl_traversal) --"
      echo "this is a run-invalidating condition, not a silent pass."
    } | tee /logs/verifier/tier1-unavailable
  elif [ "$HCL_MERGE_STATUS" != "OK" ]; then
    tier1_status="ENGINE_ERROR"
    {
      echo "the tier-1 oracle's HCL pre-parse did not complete, so the"
      echo "policy was never evaluated. This is a defect in the ORACLE's"
      echo "own toolchain (hcl2json/terraform parser skew, or a missing"
      echo "library file), NOT a judgement about this solution -- the run"
      echo "is invalid rather than failed. Details:"
      cat /logs/verifier/tier1-hcl-merge.log 2>/dev/null
    } | tee /logs/verifier/tier1-engine-error
  elif ! TIER1_OUT="$(opa eval -f raw -I -d "$POLICY" -d "$HCL_LIB" "data.cdktn_bench.s3_notification_authoritative_singleton.deny" \
        < "$ARTIFACT" 2>/logs/verifier/tier1-opa-stderr.log)"; then
    tier1_status="ENGINE_ERROR"
    {
      echo "opa eval ABORTED instead of returning a verdict, so this"
      echo "solution was never actually graded. This is a defect in the"
      echo "ORACLE (a Rego runtime error -- eval_conflict_error, a type"
      echo "error, a builtin error), NOT a judgement about the solution."
      cat /logs/verifier/tier1-opa-stderr.log 2>/dev/null
    } | tee /logs/verifier/tier1-engine-error
  elif printf '%s' "$TIER1_OUT" | jq -e 'length == 0' >/dev/null 2>&1; then
    tier1_status="PASS"
  else
    tier1_status="FAIL"
  fi
  # not_verifiable (residual finding "tier-1 action-allowlist
  # silently skipped on TF arms (plan-time-unknown path)", fixed
  # 2026-08-06): a plan-time-unknown encoded policy attribute
  # (e.g. a correct solution referencing another resource's
  # .arn) makes some tier-1 value-content facts genuinely
  # unverifiable from plan JSON alone -- specs/SCHEMA.md §4.2.1
  # mandates this be LOGGED, never silent. `data.cdktn_bench.
  # s3_notification_authoritative_singleton.not_verifiable` is an OPTIONAL rule a scenario's
  # policy.rego may define (see oracles/rego/toy-ssm-parameter/
  # policy.rego for the worked example) -- captured to a
  # variable first, not piped straight through `jq -e`, because
  # a policy.rego that never defines this rule at all makes `opa
  # eval` print NOTHING (not "[]"), which would make a bare
  # `jq -e 'length==0'` FAIL (invalid empty input) and the
  # naive `if ! ... ; then write-marker` shape write a false
  # marker on every scenario that simply hasn't adopted this
  # rule yet -- verified directly: `opa eval` on a policy.rego
  # with no not_verifiable rule at all produces empty raw
  # output, not "[]". This does NOT affect tier1_status/reward
  # either way -- it is a non-gating, informational marker only.
  if command -v opa >/dev/null 2>&1 && ! is_stub_policy "$POLICY"; then
    NOT_VERIFIABLE_OUTPUT="$(opa eval -f raw -I -d "$POLICY" -d "$HCL_LIB" "data.cdktn_bench.s3_notification_authoritative_singleton.not_verifiable" < "$ARTIFACT" 2>/dev/null)"
    if [ -n "$NOT_VERIFIABLE_OUTPUT" ] \
       && echo "$NOT_VERIFIABLE_OUTPUT" | jq -e 'length > 0' >/dev/null 2>&1; then
      {
        echo "tier-1 policy declares one or more facts NOT independently"
        echo "verifiable from plan JSON alone (specs/SCHEMA.md sect 4.2.1)."
        echo "This is informational only -- it does NOT deny the plan and"
        echo "does NOT affect tier1_status/reward. Details:"
        echo "$NOT_VERIFIABLE_OUTPUT" | jq -r '.[]'
      } | tee /logs/verifier/tier1-not-verifiable
    fi
  fi
fi

echo
echo "== summary: tier0_pass=$tier0_pass tier1_status=$tier1_status =="
if [ "$tier0_pass" = "1" ] \
   && [ "$tier1_status" != "FAIL" ] \
   && [ "$tier1_status" != "TOOL_MISSING" ] \
   && [ "$tier1_status" != "SKIPPED_STUB" ] \
   && [ "$tier1_status" != "ENGINE_ERROR" ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi
exit 0
