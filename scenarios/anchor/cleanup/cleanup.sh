#!/bin/bash
# Cleanup hook for the anchor scenario — teardown counterpart to
# deploy/deploy.sh. Runs in the scenario container before the framework's own
# teardown (aws_bench/scenario/trial.py CLEANUP phase), which is authoritative.
#
# Unlike ec2-multiregion, no task in this benchmark mutates the anchor
# scenario's account (all grading is offline inside the agent's own
# container — see docs/iac-abstraction-aws-bench-plan.md Phase 0), so there
# are no orphaned EC2/VPC/route-table residuals to sweep before `cdk destroy`.
#
# Best-effort/idempotent: never fails the phase (exit 0 always).
set -uo pipefail

cd /app/cdk_app || { echo "[cleanup.sh] FATAL: /app/cdk_app missing" >&2; exit 0; }

export CDK_DEFAULT_ACCOUNT="$PRIMARY"

echo "[cleanup.sh] anchor teardown for account ${PRIMARY}"

npx cdk destroy --profile PRIMARY --all --force --concurrency 2 || \
    echo "[cleanup.sh]   cdk destroy incomplete; framework cleanup will finish teardown"

echo "[cleanup.sh] Done."
exit 0
