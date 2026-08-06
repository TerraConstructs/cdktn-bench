# mk/gen.mk — Slice C generator targets. Auto-included by the root Makefile
# (`-include mk/*.mk`); do NOT edit the root Makefile itself (see its own
# comment — a concurrent slice workflow is running against it).
#
# Usage:
#   make gen SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make parity SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make gen-all      # regenerate every specs/*.yaml (skips specs/_toy/)
#   make parity-all    # parity-check every specs/*.yaml (skips specs/_toy/)

.PHONY: gen parity falsifiability check-paths grading-proof gen-all parity-all validate-spec

# Validate a spec against generator/spec_model.py without generating anything.
validate-spec:
	@if [ -z "$(SPEC)" ]; then echo "usage: make validate-spec SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/spec_model.py $(SPEC)

# Expand one intent spec into the full generated layout (SCHEMA.md §8).
gen:
	@if [ -z "$(SPEC)" ]; then echo "usage: make gen SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/gen.py $(SPEC)

# Independently re-verify prompt parity across a generated scenario's arms.
parity:
	@if [ -z "$(SPEC)" ]; then echo "usage: make parity SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_parity.py $(SPEC)

# Phase-2 exit criterion (benchmark-integrity review finding "end-to-end
# reward — oracle-violating solution scores 1.0"): require solution/solve.sh
# to score reward 1.0 and every declared catch to have a
# solution/broken/<catch-name>/solve.sh scoring reward 0.0, for every
# enabled arm. A scenario whose solve.sh is still a generator stub reports
# NOT_AUTHORED (non-gating, Slice D pending) rather than failing.
falsifiability:
	@if [ -z "$(SPEC)" ]; then echo "usage: make falsifiability SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python gates/oracle_falsifiability.py $(SPEC)

# Benchmark-integrity finding G2 (2026-08-06): resolve every declared
# oracle.structural_assert (tier "0" AND tier "1" alike -- tier-1 paths are
# never executed by the generated tests/static_tiers.sh, so a broken one is
# otherwise pure inert documentation) against a REAL synthesized/planned
# artifact, built by running the arm's real toolchain against a
# hand-authored, oracle-CORRECT reference fixture
# (generator/tests/fixtures/<spec-id>/<arm>/). Requires terraform/node/npm/jq
# on PATH (and network the first time npm ci populates node_modules) -- same
# host-toolchain assumption as `make falsifiability`; not wired into `make
# check`/test-gates for the same reason (mk/rails.mk's gate-preflight note).
# A spec with no fixtures directory yet reports NOT_AUTHORED (non-gating).
check-paths:
	@if [ -z "$(SPEC)" ]; then echo "usage: make check-paths SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_reference_paths.py $(SPEC)

# Benchmark-integrity finding F2 (2026-08-06): proves a scenario is
# GRADEABLE for real -- a correct reference solution scores reward 1.0 AND
# a tier-1-policy-family negative fixture scores reward 0.0, across every
# enabled arm (six outcomes for a 3-arm spec). Reuses
# gates/oracle_falsifiability.py's own sandbox-preparation code path (the
# F1 fix), same host-toolchain/network assumption as `make falsifiability`.
grading-proof:
	@if [ -z "$(SPEC)" ]; then echo "usage: make grading-proof SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python gates/grading_proof.py $(SPEC)

# Regenerate every real spec (specs/_toy/ is a generator-testing fixture, not
# a benchmark scenario — specs/SCHEMA.md §7 — so it is excluded from the
# "generate everything real" bulk targets and only ever run explicitly via
# `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml`).
gen-all:
	@set -e; \
	for spec in specs/*.yaml; do \
		[ -e "$$spec" ] || continue; \
		echo "==> gen: $$spec"; \
		uv run python generator/gen.py "$$spec"; \
	done

parity-all:
	@set -e; \
	for spec in specs/*.yaml; do \
		[ -e "$$spec" ] || continue; \
		echo "==> parity: $$spec"; \
		uv run python generator/check_parity.py "$$spec"; \
	done
