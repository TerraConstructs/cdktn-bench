#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/iam-e2e-role.yaml.
# Tier-0/1 static verifier for the awscdk arm. Do not hand-edit;
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

echo '== build: npm run build =='
if ! ( npm run build ); then
  echo "BUILD FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo '== synth: npx cdk synth --no-lookups --quiet -o cdk.out =='
if ! ( npx cdk synth --no-lookups --quiet -o cdk.out ); then
  echo "SYNTH FAILED"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

ARTIFACT="/app/project/cdk.out/ScenarioStack.template.json"
if [ ! -s "$ARTIFACT" ]; then
  echo "MISSING ARTIFACT: $ARTIFACT"
  echo "0.0" > /logs/verifier/reward.txt
  exit 0
fi

echo
echo "== tier-0: structural asserts (6 applicable) =="
tier0_pass=1
assert_check deployer-role-exists '.Resources | .[] | select(.Type=="AWS::IAM::Role") | .Properties.RoleName' contains '"iam-e2e-role-deployer"' "$ARTIFACT" || tier0_pass=0
assert_check workload-role-exists '.Resources | .[] | select(.Type=="AWS::IAM::Role") | .Properties.RoleName' contains '"iam-e2e-role-workload"' "$ARTIFACT" || tier0_pass=0
assert_check trust-not-wildcard-principal '.Resources | .[] | select(.Type=="AWS::IAM::Role") | .Properties.AssumeRolePolicyDocument.Statement | .[] | select(.Principal=="*")' not_exists null "$ARTIFACT" || tier0_pass=0
assert_check trust-has-external-id-condition '.Resources | .[] | select(.Type=="AWS::IAM::Role") | .Properties.AssumeRolePolicyDocument.Statement | .[] | .Condition.StringEquals' exists null "$ARTIFACT" || tier0_pass=0
assert_check no-full-service-wildcard-actions '.Resources | .[] | select(.Type=="AWS::IAM::Policy") | .Properties.PolicyDocument.Statement | .[] | .Action' not_regex '"^(\\*|[a-zA-Z0-9-]+:\\*)$"' "$ARTIFACT" || tier0_pass=0
assert_check actions-are-real-iam-actions '.Resources | .[] | select(.Type=="AWS::IAM::Policy") | .Properties.PolicyDocument.Statement | .[] | .Action' in '["sts:GetCallerIdentity", "sts:AssumeRole", "ec2:Describe*", "ec2:DescribeVolumeStatus", "ec2:GetSecurityGroupsForVpc", "ec2:DescribeVolumes", "ec2:DescribeInstances", "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup", "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress", "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress", "ec2:CreateTags", "ec2:DeleteTags", "ec2:CreateVolume", "ec2:DeleteVolume", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile", "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:TagInstanceProfile", "iam:UntagInstanceProfile", "iam:ListInstanceProfilesForRole", "iam:GetRole", "iam:ListRoleTags", "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:GetParameterHistory", "ssm:DescribeParameters", "kms:DescribeKey", "kms:Decrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext", "kms:CreateGrant", "s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket", "s3:GetBucket*", "s3:PutBucket*", "s3:DeleteBucketPolicy", "s3:ListTagsForResource", "s3:GetAccelerateConfiguration", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration"]' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: cfn-guard =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: s3-resource-not-overbroad
POLICY="$DIR/policy.guard"
HAS_TIER1_ASSERTS=true
tier1_status="SKIPPED_NO_ASSERTS"
if [ "$HAS_TIER1_ASSERTS" = "true" ]; then
  if ! command -v cfn-guard >/dev/null 2>&1; then
    tier1_status="TOOL_MISSING"
    {
      echo "cfn-guard is not installed in this image, but this scenario"
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
  elif cfn-guard validate --data "$ARTIFACT" --rules "$POLICY"; then
    tier1_status="PASS"
  else
    tier1_status="FAIL"
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
