#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/asg-launch-template-tag-propagation.yaml.
# Tier-0/1 static verifier for the awscdk arm. Do not hand-edit;
# regenerate instead (`make gen SPEC=specs/asg-launch-template-tag-propagation.yaml`).
#
# Reward contract (reused from tasks/anchor/smoke/tests/test.sh):
# writes a bare float to /logs/verifier/reward.txt
# (harbor/verifier/verifier.py::_parse_reward_text).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p /logs/verifier

is_stub_policy() {
  local f="$1"
  [ ! -s "$f" ] && return 0
  # Two markers, either of which means un-authored: GENERATOR-STUB, the
  # line every oracles/emit.py skeleton carries (emit.py is the sole
  # writer of policy.rego/policy.guard -- see generate_oracles), and the
  # literal "TODO(Slice D)" those skeletons also carry, matched as a
  # fallback so stripping the first line alone cannot make a placeholder
  # look authored.
  grep -q -e "GENERATOR-STUB" -e "TODO(Slice D)" "$f" 2>/dev/null && return 0
  return 1
}


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
echo "== tier-0: structural asserts (8 applicable) =="
tier0_pass=1
if ! command -v python3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  tier0_pass=0
  {
    echo "python3 and jq are both required to evaluate the tier-0"
    echo "structural asserts (tests/tier0.py drives tests/ops.py, which"
    echo "invokes jq); at least one is missing from this image, so no"
    echo "assert was evaluated -- a run-invalidating condition, not a"
    echo "silent pass."
  } | tee /logs/verifier/tier0-unavailable
elif ! python3 "$DIR/tier0.py" "$ARTIFACT"; then
  tier0_pass=0
fi

echo
echo "== tier-1: cfn-guard =="
# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: every-required-tag-reaches-instances
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
