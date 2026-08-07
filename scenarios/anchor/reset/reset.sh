#!/bin/bash
# Reset hook for the anchor scenario. Runs INSIDE the scenario container
# (same image as deploy/deploy.sh and cleanup/cleanup.sh, ~/.aws/config
# already written with a `PRIMARY` credential_process profile) BEFORE the
# framework's own generic snapshot-diff reset (aws_bench/resource_management/
# reset/manager.py::ResetManager, invoked right after this script exits --
# see aws_bench/scenario/trial.py::_run_reset / Scenario's own reset/
# docstring).
#
# WHY THIS FILE EXISTS (Slice G fix-round-3, benchmark-integrity review
# finding B2, 2026-08-07): apigw-redeploy is a `[concurrency] mode =
# "mutating"` task -- its agent phase performs a REAL AWS deploy
# (verifier.live_check.enabled) against THIS scenario's account, and
# (per the same fix round's B2 decision, specs/apigw-redeploy.yaml's
# instruction.md) the agent is deliberately told NOT to clean up after
# itself, so those live resources are genuinely still standing when
# aws_bench/task/aws_trial.py's post-trial `_reset_scenario_account()`
# fires. The generic framework reset restores CloudFormation/CDK stack
# drift by diffing against the anchor scenario's own POST_SETUP snapshot
# (taken once, right after `deploy/deploy.sh`'s `cdk deploy --all`) --
# it was never designed to know about resources a completely separate
# process (an agent's own hand-run `terraform apply`/`cdk deploy`/`cdktn
# synth` + apply, OUTSIDE this scenario's own CDK app) created directly
# in the account. Its `AWS::ApiGateway::*` coverage in
# aws_bench/resource_management/cleanup/handlers/ is NIL (no
# custom-delete handler for that service at all -- confirmed by grep,
# 2026-08-07) and its generic CloudControl fallback path for that type +
# `AWS::Logs::LogGroup` is real but UNPROVEN for this scenario's specific
# resources at review time. Rather than depend on that unproven path
# alone, this script SWEEPS THE SCENARIO'S OWN FIXED, WELL-KNOWN RESOURCE
# NAMES DIRECTLY, by name, via `aws` CLI calls that need no snapshot/diff
# machinery at all -- defense in depth: if the generic CCAPI/fastscan path
# also happens to cover these types, this script is a harmless, idempotent
# no-op the second time it runs (every AWS call below is `|| true`'d for
# "already gone").
#
# Resource names are hardcoded to EXACTLY what specs/apigw-redeploy.yaml's
# instruction + all three arms' reference solutions use (see
# tasks/anchor/apigw-redeploy-hcl-raw/solution/solve.sh's own write_rev1/
# write_rev2, and the awscdk/terraconstructs siblings, which construct the
# same names via `apigw-redeploy-*` idiomatic ID derivation) -- NOT
# discovered by tag or heuristic, deliberately: a fixed-name sweep can never
# accidentally catch an unrelated resource that merely resembles this
# scenario's naming, and it stays correct even if the generic scanner's own
# resource-type coverage changes in a future aws-bench release.
#
# Best-effort/idempotent, like cleanup/cleanup.sh: never fails the phase
# (exit 0 always) -- a reset failure here must not block the framework's
# own reset from running afterward, and every AWS call is `|| true`'d so a
# not-found (nothing to sweep, e.g. every OTHER scenario's reset, or a
# non-mutating apigw-redeploy trial where the agent's own deploy never
# happened) is silent, expected, non-fatal.
set -uo pipefail

REST_API_NAME="apigw-redeploy-api"
LAMBDA_FUNCTION_NAMES=("apigw-redeploy-hello" "apigw-redeploy-version")
IAM_ROLE_NAME="apigw-redeploy-lambda-exec"
LOG_GROUP_NAMES=(
  "/aws/lambda/apigw-redeploy-hello"
  "/aws/lambda/apigw-redeploy-version"
  "/aws/apigateway/welcome"
)

echo "[reset.sh] apigw-redeploy fixed-name sweep starting for account ${PRIMARY:-<unset>}"

# --- API Gateway REST API -------------------------------------------------
# Deleting the REST API cascades to its own resources/methods/integrations/
# deployments/stages -- nothing else to delete API-Gateway-side once this
# succeeds. `--query` + a loop (not `--output text | head -1`) because a
# stuck/duplicate prior trial could in principle leave more than one API
# with this exact name; sweep all matches, not just the first.
api_ids="$(aws apigateway get-rest-apis --profile PRIMARY \
  --query "items[?name=='${REST_API_NAME}'].id" --output text 2>/dev/null | tr '\t' '\n' || true)"
if [ -n "$api_ids" ]; then
  while IFS= read -r api_id; do
    [ -n "$api_id" ] || continue
    echo "[reset.sh] deleting REST API ${REST_API_NAME} (${api_id})"
    aws apigateway delete-rest-api --profile PRIMARY --rest-api-id "$api_id" >/dev/null 2>&1 || \
      echo "[reset.sh]   delete-rest-api ${api_id} failed (may already be gone or mid-delete)" >&2
  done <<< "$api_ids"
else
  echo "[reset.sh] no REST API named ${REST_API_NAME} found -- nothing to sweep"
fi

# --- Lambda functions ------------------------------------------------------
for fn in "${LAMBDA_FUNCTION_NAMES[@]}"; do
  if aws lambda get-function --profile PRIMARY --function-name "$fn" >/dev/null 2>&1; then
    echo "[reset.sh] deleting Lambda function ${fn}"
    aws lambda delete-function --profile PRIMARY --function-name "$fn" >/dev/null 2>&1 || \
      echo "[reset.sh]   delete-function ${fn} failed" >&2
  else
    echo "[reset.sh] Lambda function ${fn} not found -- nothing to sweep"
  fi
done

# --- CloudWatch Logs log groups --------------------------------------------
# Lambda/API Gateway auto-create these on first invocation; `terraform
# destroy`/`cdk destroy`/`cdktn destroy` never removes them (same finding
# tasks/anchor/apigw-redeploy-hcl-raw/solution/solve.sh's own cleanup()
# trap documents for its host-side proof runs).
for lg in "${LOG_GROUP_NAMES[@]}"; do
  found="$(aws logs describe-log-groups --profile PRIMARY --log-group-name-prefix "$lg" \
    --query "logGroups[?logGroupName=='${lg}'].logGroupName" --output text 2>/dev/null || true)"
  if [ -n "$found" ]; then
    echo "[reset.sh] deleting log group ${lg}"
    aws logs delete-log-group --profile PRIMARY --log-group-name "$lg" >/dev/null 2>&1 || \
      echo "[reset.sh]   delete-log-group ${lg} failed" >&2
  else
    echo "[reset.sh] log group ${lg} not found -- nothing to sweep"
  fi
done

# --- IAM role ---------------------------------------------------------------
# Deleted LAST, after the Lambda functions that assume it are gone (no hard
# ordering requirement from IAM itself, but avoids a moment where the role
# exists with dangling function references during a concurrent read). Must
# detach every attached managed policy before DeleteRole (IAM refuses
# otherwise) -- this scenario's reference solutions attach exactly
# AWSLambdaBasicExecutionRole, but this loop detaches whatever is actually
# attached rather than hardcoding that one ARN, so a future reference
# solution attaching an additional policy doesn't silently leak the role.
if aws iam get-role --profile PRIMARY --role-name "$IAM_ROLE_NAME" >/dev/null 2>&1; then
  attached_policy_arns="$(aws iam list-attached-role-policies --profile PRIMARY --role-name "$IAM_ROLE_NAME" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || true)"
  for policy_arn in $attached_policy_arns; do
    echo "[reset.sh] detaching ${policy_arn} from ${IAM_ROLE_NAME}"
    aws iam detach-role-policy --profile PRIMARY --role-name "$IAM_ROLE_NAME" --policy-arn "$policy_arn" >/dev/null 2>&1 || true
  done
  inline_policy_names="$(aws iam list-role-policies --profile PRIMARY --role-name "$IAM_ROLE_NAME" \
    --query 'PolicyNames' --output text 2>/dev/null || true)"
  for policy_name in $inline_policy_names; do
    echo "[reset.sh] deleting inline policy ${policy_name} from ${IAM_ROLE_NAME}"
    aws iam delete-role-policy --profile PRIMARY --role-name "$IAM_ROLE_NAME" --policy-name "$policy_name" >/dev/null 2>&1 || true
  done
  echo "[reset.sh] deleting IAM role ${IAM_ROLE_NAME}"
  aws iam delete-role --profile PRIMARY --role-name "$IAM_ROLE_NAME" >/dev/null 2>&1 || \
    echo "[reset.sh]   delete-role ${IAM_ROLE_NAME} failed" >&2
else
  echo "[reset.sh] IAM role ${IAM_ROLE_NAME} not found -- nothing to sweep"
fi

echo "[reset.sh] apigw-redeploy fixed-name sweep done."
exit 0
