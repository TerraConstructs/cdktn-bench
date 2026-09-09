#!/usr/bin/env bash
# Guards the scenario-hash blast radius: no build artifact may sit on disk
# under scenarios/**.
#
# aws-bench's compute_scenario_hash (aws_bench/scenario/hashing.py) SHA256s
# EVERY non-symlink file under a scenario directory, ignoring only .DS_Store
# and Thumbs.db. It does not consult .gitignore. So a local `npm install`, a
# `cdk synth`, or a `tsc` run inside scenarios/ silently changes the scenario
# source hash and invalidates the POST_SETUP baseline: every later mutating
# trial's reset fails with a source-hash mismatch until an operator re-runs
# `aws-bench env setup`, and the whole tree is re-hashed on every reset.
#
# The scenario's own Dockerfile runs `npm ci && npm run build` at image build,
# so nothing here is needed to deploy — these files are pure hash liability.
# Fix by deleting them (which itself changes the hash, so re-run `env setup`
# afterwards).
set -euo pipefail
cd "$(dirname "$0")/.."

found=$(
  find scenarios \
    \( -name node_modules -o -name cdk.out -o -name 'cdk.out.rev*' \
       -o -name dist \) -prune -print \
    -o -name '*.tsbuildinfo' -print \
    2>/dev/null | sort
)

if [ -n "$found" ]; then
  echo "SCENARIO ARTIFACTS: build output found under scenarios/ -- aws-bench hashes" >&2
  echo "  every file under a scenario dir, so each of these silently invalidates the" >&2
  echo "  POST_SETUP baseline and is re-hashed on every reset. Delete them, then" >&2
  echo "  re-run 'aws-bench env setup' (deleting them moves the hash too):" >&2
  echo "$found" | sed 's/^/    /' >&2
  exit 1
fi

echo "scenario-artifacts: OK (no node_modules/cdk.out*/dist/*.tsbuildinfo under scenarios/)"
