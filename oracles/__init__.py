"""oracles — oracle scaffolding for cdktn-bench.

Sibling packages/modules:
  - `emit.py`       — `emit_oracles(spec) -> dict[str, str]`, the stable
                       interface `generator/gen.py` (Slice C) calls to
                       produce a scenario's `oracles/<id>/intent.md`,
                       `oracles/rego/<id>/policy.rego`, and
                       `oracles/cfn-guard/<id>/policy.guard`.
  - `lib/structural.py`   — path-based structural asserts over synthesized
                             CFN JSON and Terraform plan JSON.
  - `lib/tier05_jsonata.py` — Tier-0.5 embedded-JSONata-expression oracle.

Not a published package (see `oracles/lib/__init__.py`'s docstring) — this
file exists purely to make `oracles.*` importable from `oracles/tests/`.
"""
