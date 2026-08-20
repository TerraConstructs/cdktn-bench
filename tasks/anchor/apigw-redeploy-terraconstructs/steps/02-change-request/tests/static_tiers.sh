#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/apigw-redeploy.yaml.
# Tier-0/1 static verifier for the terraconstructs arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/apigw-redeploy.yaml`).
# STEP '02-change-request' oracle (SCHEMA.md §2.6): the FULL tier suite
# -- this is the final step, so its grading is identical to what the
# single-step form of this scenario graded.
# It lives in steps/02-change-request/tests/, never in the shared
# tests/: Harbor uploads the shared tests dir during EVERY step's
# verification and only empties /tests at the start of the NEXT step's
# verification, so step-specific oracle text placed there is readable
# inside a later step's agent phase (DECISIONS.md Amendment 26 §7 rule
# 1).
#
# Reward contract (reused from tasks/anchor/smoke/tests/test.sh):
# writes a bare float to /logs/verifier/reward.txt
# (harbor/verifier/verifier.py::_parse_reward_text). No live AWS
# calls -- verifier.live_check.enabled is always false in v1.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_assert_lib.sh"
mkdir -p /logs/verifier

cd /app/project

echo '== build: npx tsc -p tsconfig.json =='
if ! ( npx tsc -p tsconfig.json ); then
  echo "BUILD FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo '== synth: npx cdktn synth =='
if ! ( npx cdktn synth ); then
  echo "SYNTH FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo '== tf-plan: cd cdktf.out/stacks/apigw-redeploy && rm -rf .terraform .terraform.lock.hcl || exit 1
node /app/project/mock-sts.js 17771 \
  > /tmp/cdktn-bench-mock-sts-apigw-redeploy.log 2>&1 &
MOCK_STS_PID=$!
MOCK_STS_READY=0
for _attempt in $(seq 1 50); do
  if (exec 3<>"/dev/tcp/127.0.0.1/17771") 2>/dev/null; then
    exec 3<&- 3>&- 2>/dev/null
    MOCK_STS_READY=1
    break
  fi
  sleep 0.1
done
if [ "$MOCK_STS_READY" != "1" ]; then
  {
    echo "mock-sts.js (pid $MOCK_STS_PID) never opened"
    echo "127.0.0.1:17771 within 5s (EADDRINUSE from a"
    echo "leftover process, or a slow bind under load -- see"
    echo "/tmp/cdktn-bench-mock-sts-apigw-redeploy.log). This is a"
    echo "run-invalidating test-infrastructure condition, NOT a bad"
    echo "solution -- terraform plan was never attempted."
  } | tee /logs/verifier/tf-plan-mock-sts-unavailable
  kill "$MOCK_STS_PID" >/dev/null 2>&1 || true
  wait "$MOCK_STS_PID" 2>/dev/null
  cd /app/project || true
  exit 1
fi
terraform init -input=false \
  && terraform plan -input=false -refresh=false -out=plan.tfplan \
  && terraform show -json plan.tfplan > plan.json
TF_RC=$?
kill "$MOCK_STS_PID" >/dev/null 2>&1 || true
wait "$MOCK_STS_PID" 2>/dev/null
cd /app/project || true
exit "$TF_RC"
 =='
if ! ( cd cdktf.out/stacks/apigw-redeploy && rm -rf .terraform .terraform.lock.hcl || exit 1
node /app/project/mock-sts.js 17771 \
  > /tmp/cdktn-bench-mock-sts-apigw-redeploy.log 2>&1 &
MOCK_STS_PID=$!
MOCK_STS_READY=0
for _attempt in $(seq 1 50); do
  if (exec 3<>"/dev/tcp/127.0.0.1/17771") 2>/dev/null; then
    exec 3<&- 3>&- 2>/dev/null
    MOCK_STS_READY=1
    break
  fi
  sleep 0.1
done
if [ "$MOCK_STS_READY" != "1" ]; then
  {
    echo "mock-sts.js (pid $MOCK_STS_PID) never opened"
    echo "127.0.0.1:17771 within 5s (EADDRINUSE from a"
    echo "leftover process, or a slow bind under load -- see"
    echo "/tmp/cdktn-bench-mock-sts-apigw-redeploy.log). This is a"
    echo "run-invalidating test-infrastructure condition, NOT a bad"
    echo "solution -- terraform plan was never attempted."
  } | tee /logs/verifier/tf-plan-mock-sts-unavailable
  kill "$MOCK_STS_PID" >/dev/null 2>&1 || true
  wait "$MOCK_STS_PID" 2>/dev/null
  cd /app/project || true
  exit 1
fi
terraform init -input=false \
  && terraform plan -input=false -refresh=false -out=plan.tfplan \
  && terraform show -json plan.tfplan > plan.json
TF_RC=$?
kill "$MOCK_STS_PID" >/dev/null 2>&1 || true
wait "$MOCK_STS_PID" 2>/dev/null
cd /app/project || true
exit "$TF_RC"
 ); then
  echo "TF-PLAN FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

ARTIFACT="/app/project/cdktf.out/stacks/apigw-redeploy/plan.json"
if [ ! -s "$ARTIFACT" ]; then
  echo "MISSING ARTIFACT: $ARTIFACT"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo
echo "== tier-0: structural asserts (6 applicable) =="
tier0_pass=1
assert_check rest-api-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_api_gateway_rest_api")' exists null "$ARTIFACT" || tier0_pass=0
assert_check deployment-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_api_gateway_deployment")' exists null "$ARTIFACT" || tier0_pass=0
assert_check lambda-function-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_lambda_function")' exists null "$ARTIFACT" || tier0_pass=0
assert_check proxy-integration-wired '.planned_values.root_module.resources | .[] | select(.type=="aws_api_gateway_integration") | .values.type' contains '"AWS_PROXY"' "$ARTIFACT" || tier0_pass=0
assert_check mock-integration-wired '.planned_values.root_module.resources | .[] | select(.type=="aws_api_gateway_integration") | .values.type' contains '"MOCK"' "$ARTIFACT" || tier0_pass=0
assert_check deployment-triggers-present '.planned_values.root_module.resources | .[] | select(.type=="aws_api_gateway_deployment") | .values.triggers.redeployment' exists null "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: OPA/Rego =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: deployment-depends-on-all-methods
POLICY="$DIR/policy.rego"
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
  elif opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.apigw_redeploy.deny" \
        < "$ARTIFACT" | jq -e 'length == 0' >/dev/null 2>&1; then
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
  # apigw_redeploy.not_verifiable` is an OPTIONAL rule a scenario's
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
    NOT_VERIFIABLE_OUTPUT="$(opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.apigw_redeploy.not_verifiable" < "$ARTIFACT" 2>/dev/null)"
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
   && [ "$tier1_status" != "SKIPPED_STUB" ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi
exit 0
