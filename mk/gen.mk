# Generator targets. Auto-included by the root Makefile (`-include mk/*.mk`);
# add targets here rather than in the root Makefile.
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

# Require solution/solve.sh to score reward 1.0 and every declared catch to
# have a solution/broken/<catch-name>/solve.sh scoring reward 0.0, on every
# enabled arm -- otherwise an oracle-violating solution can score 1.0. A
# scenario whose solve.sh is still a generator stub reports NOT_AUTHORED
# (non-gating). Host toolchain required; see docs/generator.md#make-gen-targets.
falsifiability:
	@if [ -z "$(SPEC)" ]; then echo "usage: make falsifiability SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python gates/oracle_falsifiability.py $(SPEC)

# Resolve every declared oracle.structural_assert -- tier "0" and tier "1"
# alike, since tests/static_tiers.sh never executes a tier-1 path, leaving a
# broken one as inert documentation -- against a real synthesized/planned
# artifact from the arm's own toolchain. Host toolchain and network required;
# see docs/generator.md#make-gen-targets.
check-paths:
	@if [ -z "$(SPEC)" ]; then echo "usage: make check-paths SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_reference_paths.py $(SPEC)

# Coarse NUMERIC floor -- count(catches) >= count(tier-1 asserts) per arm --
# closing the gap where `make falsifiability` exercises only the tier-1 asserts
# some catch's broken/ fixture happens to violate. Not a per-assert mapping;
# see generator/check_tier1_coverage.py's docstring for what it cannot prove.
# Exit 0 = floor met, 3 = gap no worse than its `_KNOWN_UNCOVERED_GAP`
# baseline, 1 = gap worsened.
tier1-coverage:
	@if [ -z "$(SPEC)" ]; then echo "usage: make tier1-coverage SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_tier1_coverage.py $(SPEC)

# Prove a scenario is GRADEABLE for real: a correct reference solution scores
# reward 1.0 AND a tier-1-policy-family negative fixture scores reward 0.0, on
# every enabled arm. Same host toolchain as `make falsifiability`. CATCH= names
# the negative fixture; the default is chosen PER ARM
# (gates/grading_proof.py::auto_select_negative), since a scenario may catch one
# mistake at different tiers on different arms (DECISIONS.md Amendment 9).
grading-proof:
	@if [ -z "$(SPEC)" ]; then echo "usage: make grading-proof SPEC=specs/foo.yaml [CATCH=catch-name]" >&2; exit 2; fi
	uv run python gates/grading_proof.py $(SPEC) $(if $(CATCH),--catch $(CATCH),)

# Regenerate every real spec. specs/_toy/ is a generator-testing fixture, not a
# benchmark scenario (specs/SCHEMA.md §7), so the bulk targets skip it; run it
# explicitly with `make gen SPEC=specs/_toy/toy-ssm-parameter.yaml`.
# specs/split.yaml is skipped too: it is the train/holdout split metadata, not
# a spec, and load_spec() would reject it with a stack trace.
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
