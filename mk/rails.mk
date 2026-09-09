# Integrity rails: equipping hash + published-result schema
# (gates/equipping.py, metrics/result_schema.json, metrics/validate_result.py).
# Auto-included by the root Makefile (`-include mk/*.mk`); these targets are
# declared here, never in the root Makefile.

.PHONY: check-result-schema test-gates

# WIRING: a `CHECKS +=` here does NOT reach `make check`. GNU Make expands a
# rule's prerequisite list at parse time, and the root Makefile's
# `check: $(CHECKS)` is parsed before its trailing `-include mk/*.mk`. The
# recipe-less `check: ...` stanza below is what actually wires these in: Make
# unions prerequisites across single-colon stanzas for one target as long as at
# most one carries a recipe (root's does, this one doesn't). Every mk/*.mk
# target that must run in `make check` needs both lines. Mixing `::` with the
# root's `:` is rejected by Make, so that is not an option.
CHECKS += check-result-schema test-gates

check: check-result-schema test-gates

# Two things, so this is not a vacuous "the validator ran": the checked-in
# example row must validate against metrics/result_schema.json, AND the schema
# must have a real PRODUCER — metrics/emit_fixture_rows.py runs Gates 2+3
# (gates.emit_result.build_result_record + to_result_row) over the gates/tests
# fixtures and validates those rows too. A schema change that breaks either
# fails `make check`.
check-result-schema:
	@echo "==> validating metrics/examples against metrics/result_schema.json"
	uv run python metrics/validate_result.py metrics/examples/valid-result.json
	@echo "==> validating gate-emitted rows (metrics/emit_fixture_rows.py) against metrics/result_schema.json"
	uv run python metrics/emit_fixture_rows.py

# The offline test floor: every suite that needs only Python (no docker, no
# AWS, no terraform/node toolchain) runs here, so `make check` and the
# policy-only CI job cover them. A suite left out of this list has no gating
# call site at all and can regress green forever — add new offline suites here.
# cdktn_bench/ is collected as the INSTALLED package (pyproject `package =
# true`, uv installs it editable), not through a sys.path shim.
test-gates:
	@echo "==> pytest: gates/ metrics/ oracles/ generator/ test/ cdktn_bench/"
	uv run pytest gates metrics oracles generator test cdktn_bench -q

# --- Seed parity (BROWNFIELD workspaces, specs/SCHEMA.md §2.7) ---------------
#
# `make seed-parity SPEC=specs/named-resource-replacement.yaml`
#
# DECISIONS.md Amendment 28. A brownfield scenario ships a hand-authored
# `workspace_seed` body per arm AS that arm's entry_file, so the agent opens
# working configuration rather than an empty skeleton. Two things then need
# proving that nothing else in this repo proves:
#
#   1. THE SEED IS GREEN. Every arm's generated, un-overlaid workspace must
#      build/synth/plan with that arm's REAL toolchain. A seed that doesn't is
#      not "existing infrastructure" -- it is a generation failure that would
#      hand every trial on that arm a reward of 0.0 before the agent typed
#      anything.
#   2. THE THREE SEEDS ARE EQUIVALENT. Not by resource census -- the whole
#      thesis of this benchmark is that one L2 construct decomposes into N
#      Terraform resources, so a census would fail every honest seed. By
#      DECLARED BEHAVIOURAL FACTS: each `workspace_seed.seed_asserts` entry is
#      resolved against the artifact that arm's own toolchain just produced,
#      through the SAME generator/jsonpath_jq.py compilation and the SAME
#      `_assert_lib.sh::assert_check` bash function a real trial's tier-0 runs.
#
# Implemented as a MODE of generator/check_reference_paths.py rather than a new
# gate: that script already drops a fixture at entry_file, runs the real
# toolchain and resolves declared paths. --seed is the same procedure with the
# overlay omitted.
#
# Exit-code convention matches its sibling checks: 0 pass, 1 fail, 3 =
# NOT_AUTHORED (this spec declares no workspace_seed, i.e. it is greenfield) so
# ci/run-ci.sh's existing SKIP handling works unchanged.
#
# NOT added to CHECKS / `make check`, for exactly the reason gate-preflight
# below is not: it needs terraform/node/npm/jq on PATH and (first run) network
# for `npm ci`, which `make check` must not assume. `make ci` runs it per spec.
.PHONY: seed-parity

seed-parity:
	@if [ -z "$(SPEC)" ]; then echo "usage: make seed-parity SPEC=specs/foo.yaml" >&2; exit 2; fi
	uv run python generator/check_reference_paths.py $(SPEC) --seed

# --- Gate 1 (preflight) wiring ----------------------------------------------
#
# This target is the call site for gates/preflight.py's CLI, one invocation per
# arm (the root Makefile's own `preflight` target is an independent shell loop
# that never invokes the Python gate). Keeping it called is what keeps that
# gate's JSON `reason` classification — image-not-found,
# docker-daemon-unreachable, oom-killed, entrypoint-not-found,
# preflight-script-failed — exercised code rather than dead weight.
#
# NOT in CHECKS / `make check`: it requires the arm images to already be built
# (`make build-arms`), which `make check` must not assume. Gate 1 is a PRE-JOB
# check gating whether an arm's trials should run at all, not a per-trial
# verdict, so it has no result_schema.json validity_class of its own — a
# preflight failure blocks an arm before any task/trial/equipping context
# exists to attach a row to. Run it with
# `make gate-preflight` (all arms) or `make gate-preflight ARM=awscdk` (one).
.PHONY: gate-preflight

ARM ?=

gate-preflight:
	@if [ -n "$(ARM)" ]; then \
		uv run python -m gates.preflight "$(ARM)"; \
	else \
		status=0; \
		for arm in awscdk hcl-raw terraconstructs; do \
			echo "==> gate 1 (preflight): $$arm"; \
			uv run python -m gates.preflight "$$arm" || status=1; \
		done; \
		exit $$status; \
	fi

# --- Claude Code auth + model wiring ---------------------------------------

.PHONY: run-smoke

# Model can be overridden: `make run-smoke MODEL=claude-haiku-4-5-20251001`.
# Default matches scripts/run-bench.sh's own default.
MODEL ?= claude-sonnet-5

# --path is shard 0's task dir on purpose: `smoke` is hand-authored, read-only
# and always lives under tasks/anchor (generator/shards.py puts every read-only
# task on shard 0). At shard_count > 1 this still smoke-tests shard 0 only — a
# plumbing check, not a corpus run.
#
# Runs one live trial of tasks/anchor/smoke against scenarios/anchor via
# scripts/run-bench.sh, i.e. the registry-free local-path form documented in
# local-registry.md ("Equivalent local-path form").
#
# REQUIRES, neither of which this repo provisions:
#   - A real AWS account with scenarios/anchor already deployed into it
#     (`aws-bench env init` + `env setup` against --env-name cdktn-anchor —
#     see local-registry.md steps 1-2). Without that, `cdktn-bench run` fails
#     at the environment-lookup step before ever invoking the agent.
#     (run-bench.sh execs `cdktn-bench`, not `aws-bench` — DECISIONS.md
#     Amendment 27's superset CLI, same flags; `env init`/`env setup` are the
#     same command objects under either name.)
#   - A real Claude Code credential: either $CLAUDE_CODE_OAUTH_TOKEN, a
#     token file at $AWS_BENCH_CLAUDE_TOKEN_FILE (default ~/.anthropic — an
#     operator-created convention, not a verified `claude setup-token`
#     output path, see scripts/lib/resolve-claude-token.sh's header), or
#     $ANTHROPIC_API_KEY. See scripts/lib/resolve-claude-token.sh for the
#     precedence and test/test_resolve_claude_token.py for the
#     (fake-token-only) coverage of that logic. run-bench.sh warns on
#     stderr (without hard-failing) if neither ends up resolved.
#
# This target makes a real, billed Claude Code API call and touches a real AWS
# account. It is NOT in CHECKS and no other target invokes it — do not run it to
# verify wiring; the token/model plumbing is proven offline by
# `uv run pytest test/`, which exercises scripts/run-bench.sh's argument
# assembly through its own --dry-run mode.
run-smoke:
	MODEL=$(MODEL) ./scripts/run-bench.sh \
		--scenario-path ./scenarios --path ./tasks/anchor \
		--env-name cdktn-anchor \
		-l 1 -k 1 \
		--yes
