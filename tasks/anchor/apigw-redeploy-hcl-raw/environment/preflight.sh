#!/usr/bin/env bash
# preflight.sh — runs INSIDE the cdktn-bench/hcl-raw container.
#
# Proves the arm's toolchain works fully offline: terraform CLI + the
# pre-warmed hashicorp/aws provider filesystem mirror are enough to
# `init` and `validate` a minimal aws_s3_bucket config with zero network
# access. `terraform plan` is attempted too (best-effort, dummy static
# credentials) but is NOT required to pass this gate — see README.md
# "What `terraform plan` needs" for why plan has a strictly higher bar
# than validate.
#
# Exit code 0 iff terraform version + init + validate all succeed.
set -euo pipefail

FIXTURES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

echo "###############################################"
echo "# cdktn-bench / hcl-raw preflight"
echo "###############################################"

echo
echo "== terraform version =="
terraform version

echo
echo "== jq version (bundled for oracle/verifier tooling) =="
jq --version

echo
echo "== provider filesystem mirror contents =="
find /opt/terraform-plugin-mirror -type f | sort

cd "$FIXTURES_DIR"
# Fresh working state every run so this script is idempotent when re-run
# inside a persistent container.
rm -rf .terraform .terraform.lock.hcl

echo
echo "== terraform init (offline: filesystem_mirror only, no direct{} fallback) =="
terraform init -input=false

echo
echo "== terraform validate (offline) =="
terraform validate

echo
echo "== [informational, non-gating] terraform plan (dummy credentials + skip_* flags) =="
if terraform plan -input=false -out=/tmp/hcl-raw-preflight.tfplan 2>&1; then
  echo
  echo "plan: succeeded offline for this fixture (new resource, no data sources, no refresh)."
else
  plan_status=$?
  echo
  echo "plan: did not succeed offline (exit ${plan_status}) — see README.md" \
       "\"What terraform plan needs\" for the caveats this can hit" \
       "(e.g. no network reachability to AWS endpoints at all)." >&2
fi

echo
echo "###############################################"
echo "# PREFLIGHT PASS: terraform version + offline init + offline validate all green"
echo "###############################################"
