#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/s3-bucket-hardening-decomposition.yaml.
# Tier-0/1 static verifier for the awscdk arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/s3-bucket-hardening-decomposition.yaml`).
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
echo "== tier-0: structural asserts (7 applicable) =="
tier0_pass=1
assert_check versioning-enabled '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.VersioningConfiguration.Status' eq '"Enabled"' "$ARTIFACT" || tier0_pass=0
assert_check sse-is-kms '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.BucketEncryption.ServerSideEncryptionConfiguration | .[] | .ServerSideEncryptionByDefault.SSEAlgorithm' eq '"aws:kms"' "$ARTIFACT" || tier0_pass=0
assert_check bpa-block-public-acls '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.PublicAccessBlockConfiguration.BlockPublicAcls' eq true "$ARTIFACT" || tier0_pass=0
assert_check bpa-block-public-policy '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.PublicAccessBlockConfiguration.BlockPublicPolicy' eq true "$ARTIFACT" || tier0_pass=0
assert_check bpa-ignore-public-acls '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.PublicAccessBlockConfiguration.IgnorePublicAcls' eq true "$ARTIFACT" || tier0_pass=0
assert_check bpa-restrict-public-buckets '.Resources | .[] | select(.Type=="AWS::S3::Bucket") | .Properties.PublicAccessBlockConfiguration.RestrictPublicBuckets' eq true "$ARTIFACT" || tier0_pass=0
assert_check tls-deny-condition-present '.Resources | .[] | select(.Type=="AWS::S3::BucketPolicy") | .Properties.PolicyDocument.Statement | .[] | select(.Effect=="Deny") | .Condition.Bool' contains '{"aws:SecureTransport": "false"}' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: cfn-guard =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: tls-deny-covers-objects-too-cfn, sse-kms-references-created-key-cfn
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
