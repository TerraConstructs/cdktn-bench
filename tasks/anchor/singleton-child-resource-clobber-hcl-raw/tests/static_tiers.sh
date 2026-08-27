#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/singleton-child-resource-clobber.yaml.
# Tier-0/1 static verifier for the hcl_raw arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/singleton-child-resource-clobber.yaml`).
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

echo '== plan: terraform init && terraform validate && terraform plan -input=false -refresh=false -out=plan.tfplan && terraform show -json plan.tfplan > plan.json =='
if ! ( terraform init && terraform validate && terraform plan -input=false -refresh=false -out=plan.tfplan && terraform show -json plan.tfplan > plan.json ); then
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
echo "== tier-0: structural asserts (6 applicable) =="
tier0_pass=1
assert_check exports-objects-transition-to-glacier-instant-retrieval '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_lifecycle_configuration") | .values.rule | .[] | .transition | .[] | .storage_class' eq '"GLACIER_IR"' "$ARTIFACT" || tier0_pass=0
assert_check the-transition-happens-after-ninety-days '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_lifecycle_configuration") | .values.rule | .[] | .transition | .[] | .days' eq 90 "$ARTIFACT" || tier0_pass=0
assert_check the-other-teams-rule-still-deletes-logs-after-thirty-days '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_lifecycle_configuration") | .values.rule | .[] | .expiration | .[] | .days' eq 30 "$ARTIFACT" || tier0_pass=0
assert_check the-two-rules-cover-exactly-the-two-prefixes '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_lifecycle_configuration") | .values.rule | .[] | .filter | .[] | .prefix' set_eq '["logs/", "exports/"]' "$ARTIFACT" || tier0_pass=0
assert_check there-is-still-exactly-one-bucket-tf '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket") | .type' eq '"aws_s3_bucket"' "$ARTIFACT" || tier0_pass=0
assert_check exactly-one-storage-rule-document-for-the-bucket '.planned_values.root_module.resources | .[] | select(.type=="aws_s3_bucket_lifecycle_configuration") | .type' eq '"aws_s3_bucket_lifecycle_configuration"' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: OPA/Rego =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: no-storage-rule-is-left-un-enabled
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
  elif opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.singleton_child_resource_clobber.deny" \
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
  # singleton_child_resource_clobber.not_verifiable` is an OPTIONAL rule a scenario's
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
    NOT_VERIFIABLE_OUTPUT="$(opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.singleton_child_resource_clobber.not_verifiable" < "$ARTIFACT" 2>/dev/null)"
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
