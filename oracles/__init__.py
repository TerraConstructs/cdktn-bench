"""oracles — oracle scaffolding for cdktn-bench.

Sibling packages/modules:
  - `emit.py`       — `emit_oracles(spec) -> dict[str, str]`, the stable
                       interface `generator/gen.py` calls to
                       produce a scenario's `oracles/<id>/intent.md`,
                       `oracles/rego/<id>/policy.rego` (the TF arms) and
                       `oracles/rego-cfn/<id>/policy.rego` (awscdk).
  - `lib/structural.py`   — path-based structural asserts over synthesized
                             CFN JSON and Terraform plan JSON.

Not a published package (see `oracles/lib/__init__.py`'s docstring) — this
file exists purely to make `oracles.*` importable from `oracles/tests/`.
"""
