"""oracles/lib — shared Python helpers behind the oracle scaffolding.

Not a published package (`pyproject.toml` sets `[tool.uv] package = false`,
DECISIONS.md "Packaging notes" — this repo is content + scripts, not a
library). This `__init__.py` exists only so `oracles/lib/*.py` is importable
as `oracles.lib.<module>` from `oracles/tests/` and, later, from
`generator/gen.py` and each generated task's `tests/static_tiers.sh` (via
`uv run python -m ...`), without every caller hand-rolling `sys.path`
surgery.
"""
