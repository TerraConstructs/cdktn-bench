#!/bin/bash
# Deploy hook for the anchor scenario. Mirrors
# aws-bench-datasets/scenarios/ec2-multiregion/deploy/deploy.sh (upstream's
# own smoke-test scenario) — see docs/aws-bench-datasets-guide.md §6a.
set -euo pipefail

cd /app/cdk_app

# aws-bench has written ~/.aws/config with one profile per account tag.
# CDK assumes the role declared in the profile (auto-refreshing on expiry)
# when invoked with --profile.
export CDK_DEFAULT_ACCOUNT="$PRIMARY"

npm run build

# Bootstrapping is idempotent.
npx cdk bootstrap --profile PRIMARY "aws://${PRIMARY}/us-east-1"

# One retry for transient create races (IAM propagation, etc.) — matches the
# upstream ec2-multiregion pattern even though this scenario has no IAM-heavy
# resources of its own; QARolesStack still creates roles.
cdk_deploy() {
    if ! npx cdk deploy "$@"; then
        echo "cdk deploy failed; retrying once for transient CFN/IAM races..." >&2
        npx cdk deploy "$@"
    fi
}

cdk_deploy --profile PRIMARY --all --require-approval never --concurrency 2
