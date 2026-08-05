# mk/gen.mk — Slice C generator targets. Auto-included by the root Makefile
# (`-include mk/*.mk`); do NOT edit the root Makefile itself (see its own
# comment — a concurrent slice workflow is running against it).
#
# Usage:
#   make gen SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make parity SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make gen-all      # regenerate every specs/*.yaml (skips specs/_toy/)
#   make parity-all    # parity-check every specs/*.yaml (skips specs/_toy/)

.PHONY: gen parity gen-all parity-all validate-spec

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
