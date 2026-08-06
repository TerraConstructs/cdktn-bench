# mk/ci.mk — Slice E CI consolidation. Auto-included by the root Makefile
# (`-include mk/*.mk`); do NOT edit the root Makefile itself (see its own
# comment).
#
# `make ci` is the single entry point that runs, for EVERY spec under
# specs/*.yaml (excluding specs/split.yaml, which is split metadata, not a
# spec) plus specs/_toy/toy-ssm-parameter.yaml at a lighter smoke level:
#
#   real specs:  gen-sync (make gen + a clean working tree), check-paths,
#                falsifiability, grading-proof
#   toy (smoke): gen-sync, falsifiability
#
# ...then, once (not per-scenario): `make test-gates` and `make check`.
#
# Every check for every scenario always runs (no early exit on the first
# failure), so one broken scenario never hides another's result — a
# per-check/per-scenario PASS/FAIL summary table prints at the end, and the
# target exits non-zero iff anything failed. See ci/run-ci.sh (the actual
# driver this target delegates to) for the full per-check contract and the
# docker-optional / image-reuse behavior ("keep per-scenario runtime sane").
#
# Host-toolchain requirement: terraform, node, npm, jq on PATH (same as
# `make check-paths`/`make falsifiability`/`make grading-proof` run
# individually — this target adds no NEW dependency, it just sequences the
# existing ones across every scenario). Docker is optional: if unreachable,
# ci/run-ci.sh skips the image pre-build step and each gate's own
# provider-mirror-coverage sub-check degrades to a warning (never a
# failure) — see .github/workflows/ci.yml's own "docker availability" note
# for which CI jobs need docker for real vs. which stay green without it.
.PHONY: ci

ci:
	@bash ci/run-ci.sh
