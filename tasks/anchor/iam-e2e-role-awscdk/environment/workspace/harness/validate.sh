#!/usr/bin/env bash
# harness/validate.sh -- the assume -> apply -> assert -> destroy loop.
#
# This is the harness the operator's own real episode ran by hand, six
# times, over two days (docs/scenario-proposal-iam-e2e-role.md §2). Run it
# yourself, from your own project workspace, AS MANY TIMES AS YOU NEED
# while iterating on the two roles you author:
#
#   bash harness/validate.sh
#
# It reads /logs/agent/agent-output.json (deployer_role_arn,
# workload_role_arn, external_id -- write this file, or update it, BEFORE
# every run) and:
#   1. assumes the deployer role (sts:AssumeRole with your external_id)
#   2. terraform apply's the FIXED module/ directory under those credentials
#      (revision 1)
#   3. applies it a SECOND time with no config change (forces refresh-time
#      reads, e.g. iam:ListRoleTags -- these only appear on a second apply,
#      never the first)
#   4. makes the harness's OWN direct AWS calls, still under the deployer
#      identity (a test-harness call is not the same thing as a call the
#      module's own HCL makes -- do not assume your deployer policy is
#      complete just because `terraform apply` succeeded)
#   5. assumes the workload role and runs harness/assertions.py under ITS
#      credentials
#   6. destroys everything it created, under the deployer identity, always
#      (even on failure -- see the trap below)
#
# Every denial this script prints is real: a genuine AWS AccessDenied
# against the account this task runs in, not a simulated or synthetic one.
# Fix your role's policy and re-run. You have a limited number of iterations
# for this whole task (see your own instruction for the exact budget) --
# use `aws iam simulate-principal-policy` or read the denial's own action
# name carefully before guessing broadly.
#
# module/ (this script's sibling) is READ-ONLY reference input -- do not
# edit it. This script itself is also read-only reference input.
set -euo pipefail

AGENT_OUTPUT="${AGENT_OUTPUT:-/logs/agent/agent-output.json}"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "$HARNESS_DIR/../module" && pwd)"
REGION="us-east-1"

need() { command -v "$1" >/dev/null 2>&1 || { echo "FAIL: missing dependency '$1' -- this should already be in your image" >&2; exit 2; }; }
need aws
need terraform
need jq
need python3

if [ ! -f "$AGENT_OUTPUT" ]; then
  echo "FAIL: $AGENT_OUTPUT does not exist yet." >&2
  echo "      Write deployer_role_arn, workload_role_arn, and external_id there first" >&2
  echo '      (a plain JSON object, e.g. {"deployer_role_arn": "...", "workload_role_arn": "...", "external_id": "..."})' >&2
  exit 1
fi

DEPLOYER_ROLE_ARN="$(jq -r '.deployer_role_arn // empty' "$AGENT_OUTPUT")"
WORKLOAD_ROLE_ARN="$(jq -r '.workload_role_arn // empty' "$AGENT_OUTPUT")"
EXTERNAL_ID="$(jq -r '.external_id // empty' "$AGENT_OUTPUT")"

for v in DEPLOYER_ROLE_ARN WORKLOAD_ROLE_ARN EXTERNAL_ID; do
  val="${!v}"
  if [ -z "$val" ]; then
    echo "FAIL: $AGENT_OUTPUT is missing a non-empty '${v,,}' field (case-sensitive JSON keys: deployer_role_arn, workload_role_arn, external_id)" >&2
    exit 1
  fi
done

WORKLOAD_ROLE_NAME="${WORKLOAD_ROLE_ARN##*/}"
# harness-generated, NOT agent-chosen -- only exists to keep the S3 bucket
# name and security group name collision-free across repeated runs of this
# same script within your own iteration loop.
TRIAL_ID="$(date -u +%Y%m%d%H%M%S)-$$"

echo "== phase 1: assume the deployer role ($DEPLOYER_ROLE_ARN) =="
CREDS_JSON="$(mktemp)"
if ! aws sts assume-role \
      --role-arn "$DEPLOYER_ROLE_ARN" \
      --role-session-name "iam-e2e-role-deployer-${TRIAL_ID}" \
      --external-id "$EXTERNAL_ID" \
      --duration-seconds 3600 \
      --region "$REGION" \
      --output json > "$CREDS_JSON" 2>/tmp/assume_deployer.err; then
  echo "FAIL: could not assume the deployer role." >&2
  cat /tmp/assume_deployer.err >&2
  echo "      Check: (a) the role's trust policy Principal and its Condition on sts:ExternalId," >&2
  echo "             (b) that YOUR OWN credentials are allowed sts:AssumeRole on this specific role ARN." >&2
  exit 1
fi

export AWS_ACCESS_KEY_ID; AWS_ACCESS_KEY_ID="$(jq -r '.Credentials.AccessKeyId' "$CREDS_JSON")"
export AWS_SECRET_ACCESS_KEY; AWS_SECRET_ACCESS_KEY="$(jq -r '.Credentials.SecretAccessKey' "$CREDS_JSON")"
export AWS_SESSION_TOKEN; AWS_SESSION_TOKEN="$(jq -r '.Credentials.SessionToken' "$CREDS_JSON")"
export AWS_DEFAULT_REGION="$REGION"
rm -f "$CREDS_JSON"

cleanup() {
  echo "== cleanup: terraform destroy (deployer credentials) =="
  export AWS_DEFAULT_REGION="$REGION"
  ( cd "$MODULE_DIR" && terraform destroy -auto-approve -input=false \
      -var "trial_id=$TRIAL_ID" -var "workload_role_name=$WORKLOAD_ROLE_NAME" ) || \
    echo "WARNING: destroy did not exit cleanly -- check for orphaned resources tagged TrialId=$TRIAL_ID" >&2
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION || true
}
trap cleanup EXIT

echo "== phase 2: terraform apply the seeded module/ (revision 1) =="
( cd "$MODULE_DIR" && terraform init -input=false -reconfigure )
( cd "$MODULE_DIR" && terraform apply -auto-approve -input=false \
    -var "trial_id=$TRIAL_ID" -var "workload_role_name=$WORKLOAD_ROLE_NAME" )

echo "== phase 3: a second, no-op apply (forces refresh-time reads) =="
( cd "$MODULE_DIR" && terraform apply -auto-approve -input=false \
    -var "trial_id=$TRIAL_ID" -var "workload_role_name=$WORKLOAD_ROLE_NAME" )

echo "== phase 4: the HARNESS's own AWS calls, still under the deployer identity =="
# Deliberately a call the harness makes directly, never a call module/'s own
# HCL triggers -- the real episode's own such call was ssm:GetInventory (a
# terratest poll, not a provider call); this scenario's own analogue is
# ec2:DescribeVolumeStatus. A policy that only covers what `terraform plan`
# and `terraform apply` themselves need can still fail here.
VOLUME_ID="$(cd "$MODULE_DIR" && terraform output -raw volume_id)"
if ! aws ec2 describe-volume-status --volume-ids "$VOLUME_ID" --region "$REGION" >/dev/null 2>/tmp/dvs.err; then
  echo "FAIL: deployer role denied ec2:DescribeVolumeStatus (a HARNESS-level call -- see this script's phase 4 comment)." >&2
  cat /tmp/dvs.err >&2
  exit 1
fi

echo "== phase 5: assertions under the WORKLOAD role =="
WORKLOAD_CREDS_JSON="$(mktemp)"
# NOTE: this uses the DEPLOYER's own (still-exported) credentials as the
# CALLER of sts:AssumeRole -- the deployer role therefore also needs
# sts:AssumeRole on the workload role for this phase to run at all. If your
# deployer role does not need to assume the workload role for any other
# reason, scope this permission narrowly to the workload role's own ARN.
if ! aws sts assume-role \
      --role-arn "$WORKLOAD_ROLE_ARN" \
      --role-session-name "iam-e2e-role-workload-${TRIAL_ID}" \
      --external-id "$EXTERNAL_ID" \
      --duration-seconds 900 \
      --region "$REGION" \
      --output json > "$WORKLOAD_CREDS_JSON" 2>/tmp/assume_workload.err; then
  echo "FAIL: could not assume the workload role." >&2
  cat /tmp/assume_workload.err >&2
  echo "      Check the workload role's OWN trust policy -- it must trust the account root under the SAME external_id, in addition to ec2.amazonaws.com, for this harness to be able to test it directly (there is no running EC2 instance in this task)." >&2
  exit 1
fi

(
  export AWS_ACCESS_KEY_ID; AWS_ACCESS_KEY_ID="$(jq -r '.Credentials.AccessKeyId' "$WORKLOAD_CREDS_JSON")"
  export AWS_SECRET_ACCESS_KEY; AWS_SECRET_ACCESS_KEY="$(jq -r '.Credentials.SecretAccessKey' "$WORKLOAD_CREDS_JSON")"
  export AWS_SESSION_TOKEN; AWS_SESSION_TOKEN="$(jq -r '.Credentials.SessionToken' "$WORKLOAD_CREDS_JSON")"
  export AWS_DEFAULT_REGION="$REGION"
  python3 "$HARNESS_DIR/assertions.py"
)
ASSERT_STATUS=$?
rm -f "$WORKLOAD_CREDS_JSON"
if [ "$ASSERT_STATUS" -ne 0 ]; then
  echo "FAIL: workload-role assertions failed -- see output above." >&2
  exit 1
fi

echo "== ALL PHASES PASSED: deployer role can apply+destroy the module; workload role can read what it needs =="
