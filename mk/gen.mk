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

.PHONY: gen parity falsifiability check-paths tier1-coverage grading-proof gen-all parity-all validate-spec

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
#
# HOST-TOOLCHAIN NOTE (2026-08-23): a spec that sets
# `oracle.hcl_traversal: true` (specs/SCHEMA.md §4.6) additionally needs
# `hcl2json` on PATH -- the hcl_raw arm's generated tests/static_tiers.sh runs
# it over the agent's own *.tf before `opa eval`. Missing, tier-1 reports
# TOOL_MISSING, which is a HARD failure by design, so this gate goes red
# rather than silently grading that scenario on plan JSON alone. Pin +
# checksum: arms/hcl-raw/environment/Dockerfile.
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

# Benchmark-integrity finding (2026-08-06, round 2): "An asymmetric tier-1
# oracle-strictness break passes `make ci` completely" -- falsifiability
# only exercises a tier-1 structural_assert that SOME catch's broken/
# fixture happens to violate; a spec can declare more tier-1 asserts than
# it has catches predicting a tier-1 catch, leaving the excess with zero
# covering negative fixture (proven: apigw-openapi's `route-count-correct`
# had none until this same fix added a covering catch). This is a coarse,
# NUMERIC coverage floor (count(catches) >= count(tier-1 asserts) per arm),
# not a true per-assert mapping -- see
# generator/check_tier1_coverage.py's own module docstring for exactly
# what it does and does not prove. Exit 0 = floor met; exit 3 = SKIP (a
# TRACKED, pre-existing gap no worse than its recorded
# `_KNOWN_UNCOVERED_GAP` baseline, non-gating); exit 1 = FAIL (gating -- a
# gap that got WORSE than its baseline, i.e. NEW drift). Pure spec-model
# computation, no toolchain required.
tier1-coverage:
	@if [ -z "$(SPEC)" ]; then echo "usage: make tier1-coverage SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_tier1_coverage.py $(SPEC)

# Benchmark-integrity finding F2 (2026-08-06): proves a scenario is
# GRADEABLE for real -- a correct reference solution scores reward 1.0 AND
# a tier-1-policy-family negative fixture scores reward 0.0, across every
# enabled arm (six outcomes for a 3-arm spec). Reuses
# gates/oracle_falsifiability.py's own sandbox-preparation code path (the
# F1 fix), same host-toolchain/network assumption as `make falsifiability`.
# CATCH= optionally names which solution/broken/<name> fixture to use as
# the negative on every enabled arm (default: auto-selected PER ARM, see
# gates/grading_proof.py's own auto_select_negative() docstring) --
# generalized 2026-08-06 so this target works for any scenario, not just
# the toy spec's own catch name; generalized again 2026-08-06 (residual-
# findings fix, DECISIONS.md Amendment 9) to select independently per arm
# rather than one spec-wide catch, since a scenario's whole point can be
# that different arms catch the same mistake at different tiers.
grading-proof:
	@if [ -z "$(SPEC)" ]; then echo "usage: make grading-proof SPEC=specs/foo.yaml [CATCH=catch-name]" >&2; exit 2; fi
	uv run python gates/grading_proof.py $(SPEC) $(if $(CATCH),--catch $(CATCH),)

# Regenerate every real spec (specs/_toy/ is a generator-testing fixture, not
# a benchmark scenario — specs/SCHEMA.md §7 — so it is excluded from the
# "generate everything real" bulk targets and only ever run explicitly via
# `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml`).
#
# specs/split.yaml (Slice E, DECISIONS.md Amendment 10 — train/holdout
# scenario split, generator/split.py) is skipped too: it lives alongside the
# specs it splits but is metadata, not a spec (load_spec() would reject its
# shape against spec_model.Spec anyway — the skip below just gives a clean
# "not a spec" message instead of a validation stack trace).
gen-all:
	@set -e; \
	for spec in specs/*.yaml; do \
		[ -e "$$spec" ] || continue; \
		[ "$$(basename "$$spec")" = "split.yaml" ] && continue; \
		echo "==> gen: $$spec"; \
		uv run python generator/gen.py "$$spec"; \
	done

parity-all:
	@set -e; \
	for spec in specs/*.yaml; do \
		[ -e "$$spec" ] || continue; \
		[ "$$(basename "$$spec")" = "split.yaml" ] && continue; \
		echo "==> parity: $$spec"; \
		uv run python generator/check_parity.py "$$spec"; \
	done
