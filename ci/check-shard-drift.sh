#!/usr/bin/env bash
# Guards the generated shard trees: scenarios/anchor-1 .. anchor-(N-1) must be
# exact name-rewrites of scenarios/anchor, and local-registry.json's
# `scenarios` array must list shards 0..N-1, for the N in
# generator/shards.toml. A hand-edited shard is a scenario whose deployed
# account no longer matches its template, which surfaces at `env setup` /
# reset time as a source-hash mismatch; this fails `make check` instead.
#
# It also fails when the generated tasks/ tree is stale for that N: `make
# shards` never regenerates tasks, so raising the knob without `make gen-all`
# would leave the whole corpus on one shard while the extra accounts sit idle.
#
# Regenerate with `make shards` (scenarios + registry) and `make gen-all`
# (tasks). At shard_count = 1 there are no shard dirs and this is a trivial
# pass.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python generator/shards.py --check
