# mk/metrics.mk — wiring for metrics/tokens_to_green.py, the headline
# metric aggregator. Auto-included by the root Makefile (`-include mk/*.mk`);
# do NOT edit the root Makefile itself (see its own comment).
#
# Fixes the "the headline metric script is orphaned from the run pipeline"
# finding (2026-08-06): before this file, no make target invoked
# metrics/tokens_to_green.py at all (grep across Makefile/mk/*/ci/* found
# only prose references in scripts/run-bench.sh's own comments),
# scripts/run-bench.sh never called it post-run, and `make ci`/`make check`
# only ever exercised it via its own unit tests over synthetic rows --
# nothing in the repo produced a directory of metrics/result_schema.json
# rows from a real gate run and fed it through, so there was no end-to-end
# proof that gates/emit_result.py's output and tokens_to_green.py's input
# actually agree in practice (the same orphaned-gate class this repo
# already fixed for gates/preflight.py and for the result schema's own
# "nothing enforced it" gap).

.PHONY: metrics check-metrics-e2e

# Run the real aggregator over a directory of published result rows
# (metrics/result_schema.json-conformant JSON/NDJSON, e.g. produced by a
# real job's gates/emit_result.py --row-out invocations). Writes
# benchmark.json/benchmark.md into --out-dir (default: RESULTS itself,
# matching the script's own CLI default).
#
# Usage:
#   make metrics RESULTS=jobs/claude-sonnet-5
#   make metrics RESULTS=jobs/claude-sonnet-5 OUT_DIR=jobs/claude-sonnet-5/report MAX_ITERS=8 MAX_TOKENS=50000
metrics:
	@if [ -z "$(RESULTS)" ]; then echo "usage: make metrics RESULTS=<dir> [OUT_DIR=<dir>] [MAX_ITERS=N] [MAX_TOKENS=N]" >&2; exit 2; fi
	uv run python metrics/tokens_to_green.py "$(RESULTS)" \
		$(if $(OUT_DIR),--out-dir "$(OUT_DIR)",) \
		$(if $(MAX_ITERS),--max-iters "$(MAX_ITERS)",) \
		$(if $(MAX_TOKENS),--max-tokens "$(MAX_TOKENS)",)

# Wired into `make check` (CHECKS +=, same two-stanza pattern mk/rails.mk's
# own comment explains for why a bare `+=` after root's `check: $(CHECKS)`
# line is parsed too late to land in that prerequisite list on its own).
# Real, end-to-end proof, not just each module's own unit tests in
# isolation: metrics/test_pipeline_e2e.py runs Gate 2+3
# (gates.emit_result.build_result_record/to_result_row) against the real
# gates/tests fixtures via metrics/emit_fixture_rows.py's own
# generate_rows(), writes the resulting rows to a temp directory exactly
# the shape a real job's output would be, feeds that directory through
# metrics.tokens_to_green.main(), and asserts the resulting benchmark.json
# has the shape a real consumer depends on (cells/headline_cells/
# tier_attribution keys present, row counts match, no load_errors) --
# so a producer/consumer format drift between the two modules fails this
# check instead of staying invisible forever.
CHECKS += check-metrics-e2e

check-metrics-e2e:
	@echo "==> pytest: metrics/test_pipeline_e2e.py (emit_fixture_rows -> tokens_to_green end-to-end)"
	uv run pytest metrics/test_pipeline_e2e.py -q

check: check-metrics-e2e
