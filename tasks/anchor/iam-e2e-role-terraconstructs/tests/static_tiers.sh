#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/iam-e2e-role.yaml.
# Tier-0/1 static verifier for the terraconstructs arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/iam-e2e-role.yaml`).
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

echo '== synth: npx cdktn synth =='
if ! ( npx cdktn synth ); then
  echo "SYNTH FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo '== tf-plan: cd cdktf.out/stacks/iam-e2e-role && rm -rf .terraform .terraform.lock.hcl || exit 1
node /app/project/mock-sts.js 17771 \
  > /tmp/cdktn-bench-mock-sts-iam-e2e-role.log 2>&1 &
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
    echo "/tmp/cdktn-bench-mock-sts-iam-e2e-role.log). This is a"
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
if ! ( cd cdktf.out/stacks/iam-e2e-role && rm -rf .terraform .terraform.lock.hcl || exit 1
node /app/project/mock-sts.js 17771 \
  > /tmp/cdktn-bench-mock-sts-iam-e2e-role.log 2>&1 &
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
    echo "/tmp/cdktn-bench-mock-sts-iam-e2e-role.log). This is a"
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

ARTIFACT="/app/project/cdktf.out/stacks/iam-e2e-role/plan.json"
if [ ! -s "$ARTIFACT" ]; then
  echo "MISSING ARTIFACT: $ARTIFACT"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo
echo "== tier-0: structural asserts (6 applicable) =="
tier0_pass=1
assert_check deployer-role-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role") | .values.name' contains '"iam-e2e-role-deployer"' "$ARTIFACT" || tier0_pass=0
assert_check workload-role-exists '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role") | .values.name' contains '"iam-e2e-role-workload"' "$ARTIFACT" || tier0_pass=0
assert_check trust-not-wildcard-principal '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role") | .values.assume_role_policy | fromjson | .Statement | .[] | select(.Principal=="*")' not_exists null "$ARTIFACT" || tier0_pass=0
assert_check trust-has-external-id-condition '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role") | .values.assume_role_policy | fromjson | .Statement | .[] | .Condition.StringEquals' exists null "$ARTIFACT" || tier0_pass=0
assert_check no-full-service-wildcard-actions '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role_policy") | .values.policy | fromjson | .Statement | .[] | .Action' not_regex '"^(\\*|[a-zA-Z0-9-]+:\\*)$"' "$ARTIFACT" || tier0_pass=0
assert_check actions-are-real-iam-actions '.planned_values.root_module.resources | .[] | select(.type=="aws_iam_role_policy") | .values.policy | fromjson | .Statement | .[] | .Action' in '["sts:GetCallerIdentity", "sts:AssumeRole", "ec2:Describe*", "ec2:DescribeVolumeStatus", "ec2:GetSecurityGroupsForVpc", "ec2:DescribeVolumes", "ec2:DescribeInstances", "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup", "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress", "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress", "ec2:CreateTags", "ec2:DeleteTags", "ec2:CreateVolume", "ec2:DeleteVolume", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile", "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:TagInstanceProfile", "iam:UntagInstanceProfile", "iam:ListInstanceProfilesForRole", "iam:GetRole", "iam:ListRoleTags", "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:DescribeParameters", "kms:DescribeKey", "kms:Decrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext", "kms:CreateGrant", "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket", "s3:GetBucket*", "s3:PutBucket*", "s3:DeleteBucketPolicy", "s3:ListTagsForResource", "s3:GetAccelerateConfiguration", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration"]' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: OPA/Rego =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: s3-resource-not-overbroad
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
  elif opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.iam_e2e_role.deny" \
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
  # iam_e2e_role.not_verifiable` is an OPTIONAL rule a scenario's
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
    NOT_VERIFIABLE_OUTPUT="$(opa eval -f raw -I -d "$POLICY" "data.cdktn_bench.iam_e2e_role.not_verifiable" < "$ARTIFACT" 2>/dev/null)"
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
