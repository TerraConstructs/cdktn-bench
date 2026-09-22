#!/usr/bin/env bash
# preflight.sh — runs INSIDE the cdktn-bench/hcl-modules container, under
# `docker run --network none`. What it proves, with no route off loopback:
#
#   1. the vendored module tree still hashes to its manifest;
#   2. `terraform init` resolves a registry module source through the loopback
#      responder, with no discovery request — the sidecar is the registry;
#   3. a module that calls a SECOND module by registry address resolves that one
#      too (route53 -> kms 4.0.0), which is why the allowlist carries kms twice;
#   4. a module that calls its own submodules by RELATIVE path resolves those
#      too (ecs -> ./modules/cluster), and the registry-source rule below is
#      scoped so that it does not refuse them;
#   5. `terraform validate` then passes against the provider schema out of the
#      pre-warmed filesystem mirror;
#   6. a version outside the allowlist FAILS, and fails for that reason rather
#      than for a broken environment.
#
# /etc/terraform.d/cli.tfrc names the compose SERVICE `tf-registry`, which a
# single `docker run` has not got, so this script starts the responder itself on
# loopback and writes a second config that is the image's own file with the
# host:port substituted — what is exercised is the shipped config's shape. The
# service name itself is proven by the two-container compose run in ../README.md.
#
# `terraform plan` is deliberately NOT attempted — see the comment where
# arms/hcl-raw/environment/preflight.sh has its plan block.
#
# Exit code 0 iff every numbered claim above holds.
set -euo pipefail

PREFLIGHT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="$PREFLIGHT_DIR/fixtures"
MODULE_ROOT=/opt/terraform-modules
REGISTRY_LOG=/tmp/tf-registry.log
PORT=8081

fail() {
  echo
  echo "PREFLIGHT FAIL: $*" >&2
  exit 1
}

echo "###############################################"
echo "# cdktn-bench / hcl-modules preflight"
echo "###############################################"

echo
echo "== terraform version =="
terraform version

echo
echo "== jq version (bundled for oracle/verifier tooling) =="
jq --version

echo
echo "== vendored module tree vs its manifest =="
python3 /opt/vendor_modules.py --verify --root "$MODULE_ROOT"

echo
echo "== provider filesystem mirror contents =="
# One line per mirrored provider: the .json index files name the source
# address, which is what the nine-provider union claim is about. The provider
# zips themselves are large and arch-specific; count them instead of listing.
find /opt/terraform-plugin-mirror -name '*.json' | sort
echo "provider packages: $(find /opt/terraform-plugin-mirror -name '*.zip' | wc -l | tr -d ' ')"

echo
echo "== registry responder on 127.0.0.1:${PORT} (the sidecar's own command) =="
python3 /opt/tf-registry/responder.py --root "$MODULE_ROOT" --port "$PORT" --bind 127.0.0.1 \
  >"$REGISTRY_LOG" 2>&1 &
responder_pid=$!
trap 'kill "$responder_pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  if grep -q '^PORT=' "$REGISTRY_LOG"; then break; fi
  sleep 0.1
done
grep -q "^PORT=${PORT}\$" "$REGISTRY_LOG" \
  || fail "responder did not report PORT=${PORT}; log: $(cat "$REGISTRY_LOG")"
echo "responder pid ${responder_pid}, $(grep '^PORT=' "$REGISTRY_LOG")"

# The image's own CLI config with the compose service name rewritten to
# loopback. Substituting rather than hand-writing keeps the filesystem_mirror
# block and the providers.v1 restatement exactly as shipped.
CLI_CONFIG=/tmp/preflight-cli.tfrc
sed "s|http://tf-registry:${PORT}/|http://127.0.0.1:${PORT}/|" \
  /etc/terraform.d/cli.tfrc >"$CLI_CONFIG"
grep -q "http://127.0.0.1:${PORT}/v1/modules/" "$CLI_CONFIG" \
  || fail "the shipped cli.tfrc no longer names http://tf-registry:${PORT}/v1/modules/, so this preflight would be testing a config the image does not ship"
export TF_CLI_CONFIG_FILE="$CLI_CONFIG"

run_fixture() {
  local name="$1"
  cd "$FIXTURES_DIR/$name"
  # Fresh working state every run so this script gives the same result when
  # re-run inside a persistent container.
  rm -rf .terraform .terraform.lock.hcl
}

# Amendment 46 (c)'s second half, in the only form that is true: every call the
# ROOT module makes must be a registry source, so an agent cannot copy
# /opt/terraform-modules into its workspace and call it by path. A `Key` with a
# dot in it is a call the installed module makes inside its own tree, and those
# are legitimately relative (ecs -> ./modules/cluster); applied to every entry
# the rule would refuse ecs, eks and rds outright. Asserted here so a module the
# image itself installs can never be the thing that trips the phase-5 deny.
assert_root_calls_are_registry_sources() {
  jq -e 'all(.Modules[]; .Key == "" or (.Key | contains(".")) or (.Source | startswith("registry.terraform.io/")))' \
    .terraform/modules/modules.json >/dev/null \
    || fail "a call the root module makes has a non-registry Source, which the phase-5 verifier denies"
}

echo
echo "== fixture 1/4: module s3-bucket 5.16.1 — init (offline) =="
run_fixture s3-bucket
terraform init -input=false
echo
echo "-- .terraform/modules/modules.json --"
jq -c '.Modules[]' .terraform/modules/modules.json
echo
assert_root_calls_are_registry_sources
echo "== fixture 1/4: terraform validate (offline) =="
terraform validate

# NO `terraform plan` HERE, unlike arms/hcl-raw/environment/preflight.sh.
# Every candidate module in this arm reads `data "aws_caller_identity"` to build
# an ARN or a policy (docs/design/hcl-modules-spec-matrix.md §5), and no
# provider `skip_*` flag suppresses an EXPLICIT data source the way
# skip_requesting_account_id suppresses the provider's own account lookup. Under
# `--network none` that read does not fail fast, it retries: measured at over
# four minutes of "Still reading..." before this was removed. The STS stub
# gates/aws_stub.py answers it in the real gates; a single `docker run` has no
# stub, so plan here would be a slow way of testing the stub's absence. The
# toolchain claim this script makes is init + validate, and it makes it fully.

echo
echo "== fixture 2/4: module route53 6.5.1, which calls kms 4.0.0 — init =="
run_fixture route53
terraform init -input=false
echo
echo "-- .terraform/modules/modules.json --"
jq -c '.Modules[]' .terraform/modules/modules.json
jq -e '[.Modules[] | select(.Source == "registry.terraform.io/terraform-aws-modules/kms/aws" and .Version == "4.0.0")] | length == 1' \
  .terraform/modules/modules.json >/dev/null \
  || fail "route53 6.5.1 did not pull kms 4.0.0 — the transitive registry hop is what the two-version allowlist exists for"
echo
assert_root_calls_are_registry_sources
echo "== fixture 2/4: terraform validate (offline) =="
terraform validate

echo
echo "== fixture 3/4: module ecs 7.6.1, whose own submodules are relative — init =="
run_fixture nested-submodules
terraform init -input=false
echo
echo "-- .terraform/modules/modules.json --"
jq -c '.Modules[]' .terraform/modules/modules.json
assert_root_calls_are_registry_sources
# ...and the rule is not passing vacuously: this fixture is here precisely
# because it DOES install entries whose Source is a relative path.
jq -e '[.Modules[] | select(.Source != "" and (.Source | startswith("registry.terraform.io/") | not))] | length >= 3' \
  .terraform/modules/modules.json >/dev/null \
  || fail "ecs 7.6.1 installed no relative-source submodule, so the scoped registry-source rule was not exercised"
echo
echo "== fixture 3/4: terraform validate (offline) =="
terraform validate

echo
echo "== fixture 4/4 (negative): s3-bucket 9.9.9 is not in the allowlist =="
run_fixture unlisted-version
if terraform init -input=false; then
  fail "terraform init INSTALLED s3-bucket 9.9.9 — the responder is answering outside its allowlist"
fi
echo
echo "init failed as required. Responder's own answer for that version:"
unlisted_body="$(curl -s -o /tmp/unlisted.txt -w '%{http_code}' \
  "http://127.0.0.1:${PORT}/v1/modules/terraform-aws-modules/s3-bucket/aws/9.9.9/download")"
[ "$unlisted_body" = "404" ] \
  || fail "download of an unlisted version answered HTTP ${unlisted_body}, not 404"
cat /tmp/unlisted.txt
echo
grep -q 'the newest available version is 5.16.1' /tmp/unlisted.txt \
  || fail "the 404 body does not name the newest allowlisted version"

echo
echo "== responder access log =="
cat "$REGISTRY_LOG"

# `grep -q X && fail` would abort the script under `set -e` on the NORMAL
# (not-found) path, so these two are written as `if`.
if grep -q '/.well-known/terraform.json' "$REGISTRY_LOG"; then
  fail "terraform issued a service-discovery request — the host block in cli.tfrc is not being honoured, so this arm would depend on resolving registry.terraform.io"
fi
if grep -q 'tarballs/s3-bucket-9.9.9' "$REGISTRY_LOG"; then
  fail "the responder served a tarball for an unlisted version"
fi
grep -q 'tarballs/s3-bucket-5.16.1.tar.gz 200' "$REGISTRY_LOG" \
  || fail "no 200 for the s3-bucket 5.16.1 tarball — the module did not come from this responder"
grep -q 'tarballs/kms-4.0.0.tar.gz 200' "$REGISTRY_LOG" \
  || fail "no 200 for the kms 4.0.0 tarball — the transitive hop did not come from this responder"

echo
echo "###############################################"
echo "# PREFLIGHT PASS: manifest verified; offline init+validate through the"
echo "# loopback registry for a direct, a transitive and a relative-submodule"
echo "# module; an unlisted version refused; no service-discovery request."
echo "###############################################"
