# Slice B — integrity rails: equipping hash + published-result schema
# (gates/equipping.py, metrics/result_schema.json, metrics/validate_result.py).
# Lands in `make check` via the root Makefile's `-include mk/*.mk` + CHECKS
# variable — see Makefile's own comment on why slice targets don't touch it
# directly.

.PHONY: check-result-schema test-gates

# NOTE on wiring: the root Makefile's `check: $(CHECKS)` line is parsed
# *before* its own `-include mk/*.mk` (which is the last line of that file),
# and GNU Make expands a rule's prerequisite list immediately at the point
# the rule is parsed — not deferred to build time (unlike variable refs
# inside a recipe body, which *are* deferred). So `CHECKS +=` appended here
# is too late to land in that prerequisite list; verified empirically (a
# minimal repro of the same include order silently drops the appended
# prerequisite). Keeping the `+=` anyway for documentation/consistency with
# the slice convention the root Makefile's own comment describes, but the
# line below — a second, recipe-less `check: ...` stanza — is what actually
# wires these into `make check`: GNU Make unions prerequisites across
# multiple single-colon rule stanzas for the same target as long as at most
# one of them carries a recipe (root's does, this one doesn't), and that
# union isn't subject to the immediate-expansion trap since it's evaluated
# as its own rule line, not as a reference to $(CHECKS). (Double-colon rules
# were the other option the root Makefile's comment names, but GNU Make
# rejects mixing `:`/`::` for the same target, and root already committed to
# `:`.)
CHECKS += check-result-schema test-gates

check: check-result-schema test-gates

# Real check, not a vacuous "the validator ran": validates the checked-in
# example result row against metrics/result_schema.json, so a schema change
# that breaks a previously-valid row (or a schema that's gone malformed)
# fails `make check`. Then goes further and proves the schema has an actual
# PRODUCER: metrics/emit_fixture_rows.py runs Gates 2+3
# (gates.emit_result.build_result_record + to_result_row) against the real
# gates/tests fixtures and validates THOSE rows too — so a gate-emitted
# record round-trips through the schema, not just a hand-authored example
# (the chant-bench "nothing enforced it" gap this schema's description
# names).
check-result-schema:
	@echo "==> validating metrics/examples against metrics/result_schema.json"
	uv run python metrics/validate_result.py metrics/examples/valid-result.json
	@echo "==> validating gate-emitted rows (metrics/emit_fixture_rows.py) against metrics/result_schema.json"
	uv run python metrics/emit_fixture_rows.py

# Hash determinism/sensitivity (gates/test_equipping.py) + schema round-trip
# (metrics/test_validate_result.py) — the pytest suite backing this slice.
# ALSO runs oracles/ + generator/ (benchmark-integrity review finding
# "mk/rails.mk:51 -- make check's test-gates never runs the 75 oracles/ +
# generator/ tests", 2026-08-06): before this fix, `make check` never ran
# either suite at all -- including the tier05_jsonata regression tests
# guarding the materialize()-container-fallback fix (this same review
# round) -- so a regression there could land and stay green in `make check`
# forever. All four suites pass together as of this fix.
test-gates:
	@echo "==> pytest: gates/ metrics/ oracles/ generator/"
	uv run pytest gates metrics oracles generator -q

# --- Gate 1 (preflight) wiring ----------------------------------------------
#
# gates/preflight.py's run_preflight() was orphaned: nothing in the repo
# called it (the root Makefile's own `preflight` target is an independent
# hand-rolled shell loop that never imports/invokes it). This target actually
# calls the Python gate's CLI, one invocation per arm, so its JSON report
# (machine-readable `reason` classification: image-not-found,
# docker-daemon-unreachable, oom-killed, entrypoint-not-found,
# preflight-script-failed, ...) is real, exercised code, not dead weight.
#
# Deliberately NOT added to CHECKS / `make check` — same reasoning as the
# root Makefile's own `preflight` target: it requires the arm images to
# already be built (`make build-arms`), which `make check` must not assume.
# Gate 1 is a PRE-JOB check gating whether an arm's trials should even run,
# not a per-trial verdict — it has no result_schema.json validity_class of
# its own (see that schema's `validity_class` description) because a
# preflight failure blocks an entire arm's trials before any task/trial/
# equipping context exists to attach a schema row to. Run it with
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

# Runs one live trial of tasks/anchor/smoke against scenarios/anchor via
# scripts/run-bench.sh, i.e. the registry-free local-path form documented in
# local-registry.md ("Equivalent local-path form").
#
# REQUIRES, neither of which this repo/slice provisions:
#   - A real AWS account with scenarios/anchor already deployed into it
#     (`aws-bench env init` + `env setup` against --env-name cdktn-anchor —
#     see local-registry.md steps 1-2). Without that, `aws-bench run` fails
#     at the environment-lookup step before ever invoking the agent.
#   - A real Claude Code credential: either $CLAUDE_CODE_OAUTH_TOKEN, a
#     token file at $AWS_BENCH_CLAUDE_TOKEN_FILE (default ~/.anthropic — an
#     operator-created convention, not a verified `claude setup-token`
#     output path, see scripts/lib/resolve-claude-token.sh's header), or
#     $ANTHROPIC_API_KEY. See scripts/lib/resolve-claude-token.sh for the
#     precedence and test/test_resolve_claude_token.py for the
#     (fake-token-only) coverage of that logic. run-bench.sh warns on
#     stderr (without hard-failing) if neither ends up resolved.
#
# This target makes a real, billed Claude Code API call and touches a real
# AWS account. It is deliberately NOT invoked by `make check` (not added to
# CHECKS) or by any other target in this repo — do not run it as part of
# verifying this slice's wiring; the token/model plumbing itself is proven
# offline by `uv run pytest test/`, which exercises scripts/run-bench.sh's
# argument assembly via its own --dry-run mode plus source-level evidence in
# gates/RECON.md.
run-smoke:
	MODEL=$(MODEL) ./scripts/run-bench.sh \
		--scenario-path ./scenarios --path ./tasks/anchor \
		--env-name cdktn-anchor \
		-l 1 -k 1 \
		--yes
