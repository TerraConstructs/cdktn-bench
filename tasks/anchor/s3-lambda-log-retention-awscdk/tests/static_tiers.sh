#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/s3-lambda-log-retention.yaml.
# Tier-0/1 static verifier for the awscdk arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/s3-lambda-log-retention.yaml`).
#
# Reward contract (reused from tasks/anchor/smoke/tests/test.sh):
# writes a bare float to /logs/verifier/reward.txt
# (harbor/verifier/verifier.py::_parse_reward_text).
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
assert_check s3-bucket-exists '.Resources | .[] | select(.Type=="AWS::S3::Bucket")' exists null "$ARTIFACT" || tier0_pass=0
assert_check lambda-function-exists '.Resources | .[] | select(.Type=="AWS::Lambda::Function")' exists null "$ARTIFACT" || tier0_pass=0
assert_check log-group-exists '.Resources | .[] | select(.Type=="AWS::Logs::LogGroup")' exists null "$ARTIFACT" || tier0_pass=0
assert_check log-group-retention-near-ten '.Resources | .[] | select(.Type=="AWS::Logs::LogGroup") | .Properties.RetentionInDays' in '[7, 14]' "$ARTIFACT" || tier0_pass=0
assert_check s3-notification-put-event-configured '.Resources | .[] | select(.Type=="Custom::S3BucketNotifications") | .Properties.NotificationConfiguration.LambdaFunctionConfigurations | .[] | .Events' contains '"s3:ObjectCreated:Put"' "$ARTIFACT" || tier0_pass=0
assert_check lambda-permission-principal-is-s3 '.Resources | .[] | select(.Type=="AWS::Lambda::Permission") | .Properties.Principal' eq '"s3.amazonaws.com"' "$ARTIFACT" || tier0_pass=0

echo
echo "== tier-1: cfn-guard =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: lambda-permission-scoped-to-bucket-cfn
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
