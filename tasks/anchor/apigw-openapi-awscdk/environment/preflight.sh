#!/usr/bin/env bash
# cdktn-bench / arms/awscdk / preflight.sh
#
# Runs INSIDE the built image (cdktn-bench/awscdk:dev) to prove the arm's
# toolchain works fully offline: no AWS credentials, no network access.
# Exit 0 = toolchain is sound; non-zero = broken image, do not ship.
#
# Usage (from the host):
#   docker run --rm --network none cdktn-bench/awscdk:dev /usr/local/bin/preflight.sh
#
# Also invoked without --network none / creds unset as a weaker smoke test;
# the --network none form is the one that actually proves the "no network"
# claim and is what CI/`make preflight` should use.

set -euo pipefail

blue() { printf '\033[1;34m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m  %s\n' "$*"; }
fail() { printf '  \033[1;31mFAIL\033[0m %s\n' "$*" >&2; }

# Belt-and-suspenders: make sure this run really has no AWS creds and can't
# accidentally succeed by reaching real AWS. We don't rely on network being
# physically unavailable (the caller should also pass --network none); we
# additionally point every AWS SDK/CLI credential source at nothing so a
# credential leak in the base image would fail loudly instead of silently
# working.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE \
      AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_CREDENTIALS_FULL_URI \
      2>/dev/null || true
export AWS_ACCESS_KEY_ID=""
export AWS_SECRET_ACCESS_KEY=""
export AWS_EC2_METADATA_DISABLED=true
export HOME="${HOME:-/root}"
export AWS_SHARED_CREDENTIALS_FILE="/nonexistent/credentials"
export AWS_CONFIG_FILE="/nonexistent/config"
export CDK_DISABLE_VERSION_CHECK=true
export NPM_CONFIG_UPDATE_NOTIFIER=false

WORKDIR="/app/project"
STEP=0
total_steps=5

step() {
  STEP=$((STEP + 1))
  blue "[$STEP/$total_steps] $*"
}

step "node / npm versions"
node --version
npm --version
ok "node $(node --version), npm $(npm --version)"

step "tsc --version"
cd "$WORKDIR"
TSC_VERSION="$(npx --no-install tsc --version)"
echo "$TSC_VERSION"
ok "$TSC_VERSION"

step "cdk --version"
CDK_VERSION="$(npx --no-install cdk --version)"
echo "$CDK_VERSION"
ok "cdk CLI $CDK_VERSION"

step "tsc --noEmit (compiles the workspace's example stack)"
if npx --no-install tsc --noEmit; then
  ok "tsc --noEmit clean"
else
  fail "tsc --noEmit failed"
  exit 1
fi

step "cdk synth --no-lookups (one-construct app, offline)"
OUT_DIR="$(mktemp -d)"
if npm run --silent build && npx --no-install cdk synth --no-lookups --quiet -o "$OUT_DIR" >/tmp/preflight-synth.log 2>&1; then
  TEMPLATE="$OUT_DIR/ScenarioStack.template.json"
  if [ -s "$TEMPLATE" ] && jq -e '.Resources != null' "$TEMPLATE" >/dev/null 2>&1; then
    ok "cdk synth produced $TEMPLATE ($(wc -c < "$TEMPLATE") bytes, valid CFN template)"
  else
    fail "cdk synth ran but $TEMPLATE is missing or doesn't contain the expected construct"
    cat /tmp/preflight-synth.log >&2
    exit 1
  fi
else
  fail "cdk synth failed"
  cat /tmp/preflight-synth.log >&2
  exit 1
fi
rm -rf "$OUT_DIR"

# Clean up the compiled JS the build step left next to the .ts sources so the
# workspace stays in the pristine state an agent (or the Slice C generator)
# expects to find it in.
find "$WORKDIR/bin" "$WORKDIR/lib" -maxdepth 1 \( -name '*.js' -o -name '*.d.ts' \) -delete

blue "preflight: all $total_steps checks passed — awscdk toolchain is sound offline."
