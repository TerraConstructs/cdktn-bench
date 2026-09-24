# --- The `arm x equipping` factorial's own gate (ROADMAP M2) -----------------
#
# A tuned row is only tuned if the material reached the container, and Harbor
# makes both ways of failing silent: skills are installed with
# `cp ... || true`, and claude-code logs an unstartable MCP server and carries
# on. gates/tuned_equipping.py checks the declaration against the artifact.
#
# Two halves, split on what they need:
#   `equipping-check`     host-side bytes only -- in CHECKS, so `make check`
#                         runs it and a hand-edited task dir cannot pass CI.
#   `equipping-preflight` also one `docker run` per declared stdio MCP command,
#                         so it needs the arm images built (`make build-arms`).
#                         NOT in CHECKS, the same reason gate-preflight is not.
.PHONY: equipping-check equipping-preflight

equipping-check:
	uv run python -m gates.tuned_equipping --static-only

equipping-preflight:
	uv run python -m gates.tuned_equipping

# Both lines are required: `CHECKS +=` alone never reaches `make check`, because
# the root Makefile parses `check: $(CHECKS)` before it includes this file (the
# wiring note in mk/rails.mk has the full reason).
CHECKS += equipping-check

check: equipping-check
