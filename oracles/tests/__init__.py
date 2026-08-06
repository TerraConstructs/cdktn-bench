"""oracles/tests — pytest suite for the oracle scaffolding.

Only exists to make `oracles/tests/` part of the `oracles` package chain, so
pytest's default (prepend) import mode inserts the repo root — not
`oracles/` itself — onto `sys.path`, which is what lets every test module
here `import oracles.lib.structural` / `import oracles.emit` the same way
`generator/gen.py` will.
"""
