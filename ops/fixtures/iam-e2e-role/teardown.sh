#!/usr/bin/env bash
# ops/fixtures/iam-e2e-role/teardown.sh -- removes the fixtures
# ops/fixtures/iam-e2e-role/provision.sh creates. AUTHORIZED BUT NOT RUN
# (same note as provision.sh) -- the orchestrator runs this, never this
# authoring pass.
#
# NOTE the KMS key deletion is NOT immediate -- AWS enforces a mandatory
# pending-deletion window (7-30 days, default 30 here). This is expected
# and is exactly the cost provision.sh's own header explains this scenario
# avoids paying per-trial by reusing ONE long-lived key.
#
# This does NOT sweep any per-trial resource (the deployer/workload roles,
# module/'s own security group/EBS volume/S3 bucket/instance profile) --
# those are swept by scenarios/anchor/reset/reset.sh's own per-trial
# convention (see this scenario's own DECISIONS.md amendment for the
# reset.sh entry still needed there, not yet added by this pass).
set -euo pipefail

REGION="us-east-1"
ALIAS_NAME="alias/cdktn-bench-iam-e2e-role"
PARAM_PREFIX="/cdktn-bench-iam-e2e-role/app"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$REGION")"
DECOY_BUCKET="cdktn-bench-iam-e2e-tfstate-${ACCOUNT_ID}-${REGION}"

echo "== deleting SSM parameters =="
aws ssm delete-parameter --region "$REGION" --name "$PARAM_PREFIX/config" 2>/dev/null || echo "   $PARAM_PREFIX/config already gone"
aws ssm delete-parameter --region "$REGION" --name "$PARAM_PREFIX/db-password" 2>/dev/null || echo "   $PARAM_PREFIX/db-password already gone"

echo "== deleting decoy bucket $DECOY_BUCKET =="
if aws s3api head-bucket --bucket "$DECOY_BUCKET" --region "$REGION" >/dev/null 2>&1; then
  aws s3 rm "s3://$DECOY_BUCKET" --recursive --region "$REGION" || true
  aws s3api delete-bucket --bucket "$DECOY_BUCKET" --region "$REGION"
else
  echo "   already gone"
fi

echo "== scheduling CMK deletion (alias $ALIAS_NAME) =="
KEY_ID="$(aws kms describe-key --key-id "$ALIAS_NAME" --region "$REGION" --query 'KeyMetadata.KeyId' --output text 2>/dev/null || true)"
if [ -n "$KEY_ID" ] && [ "$KEY_ID" != "None" ]; then
  aws kms delete-alias --alias-name "$ALIAS_NAME" --region "$REGION" || true
  aws kms schedule-key-deletion --key-id "$KEY_ID" --region "$REGION" --pending-window-in-days 30
  echo "   $KEY_ID scheduled for deletion in 30 days"
else
  echo "   already gone"
fi

echo "== done. =="
