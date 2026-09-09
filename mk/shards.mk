# Scenario-shard targets (generator/shards.py, DECISIONS.md Amendment 33).
# Auto-included by the root Makefile (`-include mk/*.mk`); shard targets are
# declared here, never in the root Makefile.
#
#   make shards                    materialize scenarios/anchor-k + registry
#   make check-shard-drift         fail if a shard or the registry drifted
#   make check-scenario-artifacts  fail if build output sits under scenarios/
#
# Both checks join `make check` through the recipe-less `check:` stanza
# below, for the GNU Make prerequisite-expansion reason mk/rails.mk states.
# Build output under scenarios/ changes the aws-bench scenario hash, so a
# local artifacts failure means the next `env setup` re-baselines.
.PHONY: shards check-shard-drift check-scenario-artifacts

CHECKS += check-shard-drift check-scenario-artifacts

check: check-shard-drift check-scenario-artifacts

# Rewrites scenarios/anchor-1..N-1 from the TRACKED files of scenarios/anchor
# and the registry's scenarios[] array, for the N in generator/shards.toml.
# A no-op at shard_count = 1. Never touches scenarios/anchor itself: that
# tree is hashed against an already-provisioned account.
shards:
	uv run python generator/shards.py --write

check-shard-drift:
	./ci/check-shard-drift.sh

check-scenario-artifacts:
	./ci/check-scenario-artifacts.sh
