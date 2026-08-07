#!/usr/bin/env bash
# ops/fixtures/iam-e2e-role/provision.sh -- pre-provisioned account fixtures
# for the iam-e2e-role scenario (specs/iam-e2e-role.yaml).
#
# AUTHORIZED BUT NOT RUN. Per the operator's own directive (2026-08-08):
# "I authorize pre-provisioned fixtures (CMK, decoy bucket, ..)" -- this
# script is WRITTEN by the scenario author (this task) and RUN by the
# orchestrator against the dedicated benchmark account, never by the
# scenario-authoring pass itself (which was explicitly directed to make
# NO AWS calls, mutating or read-only). Read this file; do not execute it
# as part of authoring this scenario.
#
# What this creates, all tagged Project=cdktn-bench Scenario=iam-e2e-role
# so they are identifiable and sweepable independently of any per-trial
# resource:
#   1. A customer-managed KMS key + alias/cdktn-bench-iam-e2e-role.
#      Rationale: a per-trial `aws_kms_key` has a mandatory >=7-day
#      deletion window (does not clean up); trials would accumulate keys
#      at ~$1/mo each. This one key is reused by every trial.
#   2. Two SSM parameters under /cdktn-bench-iam-e2e-role/app/:
#        app/config       (String, plain)
#        app/db-password  (SecureString, encrypted under the CMK above)
#      Rationale (specs/iam-e2e-role.yaml's own §5.9-equivalent note,
#      mirroring docs/scenario-proposal-iam-e2e-role.md's own finding):
#      Terraform (the module/harness's own toolchain) CAN create
#      SecureString parameters directly, but this scenario's own module
#      reads the PLAIN one as a data source (exercising the deployer
#      role's own ssm:GetParameter) and the workload role reads BOTH via
#      a real ssm:GetParametersByPath --with-decryption call
#      (harness/assertions.py) -- both need FIXED, predictable names that
#      exist BEFORE any trial starts, and creating/destroying a
#      SecureString parameter every trial adds cost and risk for zero
#      benefit over one shared, reused pair.
#   3. A decoy S3 bucket, cdktn-bench-iam-e2e-tfstate-<account>-us-east-1
#      -- protected, never touched by module/ or by any correct policy.
#      Mechanizes the wildcard-matches-protected-bucket catch (mirrors the
#      real episode's own A11 defect, docs/scenario-proposal-iam-e2e-role.md
#      §1). Deliberately shares the "cdktn-bench-iam-e2e-" prefix with the
#      module's own scratch bucket name
#      (cdktn-bench-iam-e2e-<trial>-scratch) so a naive, overly-broad
#      Resource pattern (arn:aws:s3:::cdktn-bench-iam-e2e-*, WITHOUT the
#      module's own "-scratch" suffix) matches BOTH.
#
# Idempotent: every step checks for the resource's existence first and is
# a no-op if it already exists. Safe to re-run.
#
# Usage (the orchestrator runs this, not this authoring pass):
#   AWS_PROFILE=<the dedicated benchmark account> bash ops/fixtures/iam-e2e-role/provision.sh
#
# Teardown: ops/fixtures/iam-e2e-role/teardown.sh (same directory).
set -euo pipefail

REGION="us-east-1"
ALIAS_NAME="alias/cdktn-bench-iam-e2e-role"
PARAM_PREFIX="/cdktn-bench-iam-e2e-role/app"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$REGION")"
DECOY_BUCKET="cdktn-bench-iam-e2e-tfstate-${ACCOUNT_ID}-${REGION}"

TAGS='[{"TagKey":"Project","TagValue":"cdktn-bench"},{"TagKey":"Scenario","TagValue":"iam-e2e-role"}]'

echo "== account: $ACCOUNT_ID region: $REGION =="

echo "== 1. CMK + alias ($ALIAS_NAME) =="
if aws kms describe-key --key-id "$ALIAS_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "   already exists -- skipping create"
else
  KEY_ID="$(aws kms create-key \
    --region "$REGION" \
    --description "cdktn-bench iam-e2e-role scenario CMK -- encrypts the pre-provisioned SecureString SSM parameter" \
    --tags "$TAGS" \
    --query 'KeyMetadata.KeyId' --output text)"
  aws kms create-alias --region "$REGION" --alias-name "$ALIAS_NAME" --target-key-id "$KEY_ID"
  echo "   created key $KEY_ID, alias $ALIAS_NAME"
fi

echo "== 2. SSM parameters under $PARAM_PREFIX/ =="
if aws ssm get-parameter --name "$PARAM_PREFIX/config" --region "$REGION" >/dev/null 2>&1; then
  echo "   $PARAM_PREFIX/config already exists -- skipping"
else
  aws ssm put-parameter \
    --region "$REGION" \
    --name "$PARAM_PREFIX/config" \
    --type String \
    --value "cdktn-bench-iam-e2e-role-fixture-config" \
    --tags "$TAGS" \
    --overwrite
  echo "   created $PARAM_PREFIX/config"
fi

if aws ssm get-parameter --name "$PARAM_PREFIX/db-password" --region "$REGION" >/dev/null 2>&1; then
  echo "   $PARAM_PREFIX/db-password already exists -- skipping"
else
  aws ssm put-parameter \
    --region "$REGION" \
    --name "$PARAM_PREFIX/db-password" \
    --type SecureString \
    --key-id "$ALIAS_NAME" \
    --value "cdktn-bench-iam-e2e-role-fixture-secret-not-a-real-credential" \
    --tags "$TAGS" \
    --overwrite
  echo "   created $PARAM_PREFIX/db-password (SecureString, under $ALIAS_NAME)"
fi

echo "== 3. decoy bucket ($DECOY_BUCKET) =="
if aws s3api head-bucket --bucket "$DECOY_BUCKET" --region "$REGION" >/dev/null 2>&1; then
  echo "   already exists -- skipping create"
else
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$DECOY_BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$DECOY_BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  aws s3api put-bucket-tagging --bucket "$DECOY_BUCKET" --tagging "{\"TagSet\":$TAGS}"
  aws s3api put-public-access-block --bucket "$DECOY_BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  echo "   created and tagged $DECOY_BUCKET (public access blocked; content is never read, only its NAME/ARN matters)"
fi

echo "== done. Fixtures ready for the iam-e2e-role scenario. =="
