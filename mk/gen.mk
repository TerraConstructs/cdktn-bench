# Generator targets. Auto-included by the root Makefile (`-include mk/*.mk`);
# add targets here rather than in the root Makefile.
#
# Usage:
#   make gen SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make parity SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make tier0-parity SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make normaliser-parity SPEC=specs/_toy/toy-ssm-parameter.yaml
#   make hcl-merge-bytes SPEC=specs/foo.yaml REUSE=dir
#   make gen-all      # regenerate every specs/*.yaml (skips specs/_toy/)
#   make parity-all    # parity-check every specs/*.yaml (skips specs/_toy/)

.PHONY: gen parity falsifiability check-paths tier1-coverage grading-proof gen-all parity-all validate-spec tier0-parity tier0-parity-all normaliser-parity normaliser-parity-all hcl-merge-bytes

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

# Grade every reference and broken-fixture artifact with both tier-0 graders
# -- the `assert_check` bash library recovered from git as it stood before
# DECISIONS.md Amendment 43, and the generated tests/{tier0,ops}.py driver that
# replaced it -- and require identical per-assert outcomes and identical
# tier0_pass. The driver's landing condition, and ON DEMAND afterwards, never
# in `make ci`. Run it when the compilers or the shared grammar change; any
# spec works, whatever `oracle.tier0_engine` says. `--rego` adds the compiled
# Rego backend as a third column (available, not adopted). Same host toolchain
# and runtime class as `make falsifiability`: it runs every fixture for real.
# `OUT=<dir>` keeps the collected artifacts so `--regrade <dir>` can re-check a
# grader change in seconds without them. Exit 3 = NOT_AUTHORED (nothing
# gradeable).
tier0-parity:
	@if [ -z "$(SPEC)" ]; then echo "usage: make tier0-parity SPEC=specs/foo.yaml [OUT=dir]" >&2; exit 2; fi
	uv run python gates/tier0_parity.py $(SPEC) $(if $(OUT),--out $(OUT),)

tier0-parity-all:
	uv run python gates/tier0_parity.py --all $(if $(OUT),--out $(OUT),)

# Zero-drift gate on the plan normaliser: grade every reference and broken
# fixture of every Terraform-shaped arm with the RAW plan and with the
# NORMALISED one, and require identical per-assert tier-0 outcomes, identical
# tier-1 deny/not_verifiable sets, and -- for a plan with no module in it --
# canonical byte identity of the two documents. A MODULE-shaped fixture is held
# to the other contract instead: an assert may move OFF `unresolvable` (the
# resource becoming visible is the hoist working) and never onto it.
# On demand and not in `make ci`, exactly like tier0-parity and for the same
# reason: it runs every fixture for real and needs the host toolchain. Run it
# when the normaliser, the tier-0 compiler or a policy changes. `OUT=<dir>`
# keeps the collected artifacts so `--regrade <dir>` re-checks a normaliser
# change in seconds. Exit 3 = NOT_AUTHORED.
normaliser-parity:
	@if [ -z "$(SPEC)" ]; then echo "usage: make normaliser-parity SPEC=specs/foo.yaml [OUT=dir]" >&2; exit 2; fi
	uv run python gates/plan_normaliser_parity.py $(SPEC) $(if $(OUT),--out $(OUT),)

normaliser-parity-all:
	uv run python gates/plan_normaliser_parity.py --all $(if $(OUT),--out $(OUT),)

# Byte gate on the lifted HCL pre-parser: /logs/verifier/oracle-input.json must
# be byte-for-byte what a baseline copy of the program from REV writes, for the
# reference fixture and every broken fixture an `oracle.hcl_traversal` spec
# ships. `REUSE=<dir>` compares a tree `make tier0-parity OUT=` collected
# and runs no toolchain; without it the fixtures are collected here.
hcl-merge-bytes:
	uv run python gates/hcl_merge_bytes.py $(SPEC) \
	  $(if $(REV),--baseline-rev $(REV),) $(if $(REUSE),--reuse $(REUSE),)

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
