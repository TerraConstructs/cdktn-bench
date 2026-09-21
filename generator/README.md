# generator

The scenario generator (build plan Phase 1, mismatch M2 resolution): reads one YAML
intent spec per scenario from `../specs/`, and expands it into:

- `../tasks/<scenario>/{awscdk,hcl-raw,terraconstructs}/` task directories (prompt body
  shared verbatim across arms; only the target-language line and `environment/`
  differ),
- `../oracles/` invocations wired into each task's `tests/test.sh` (Rego/OPA on every
  arm: a CFN-shaped policy over the CDK arm's synthesized template, a plan-shaped one
  over the two Terraform-shaped arms' `terraform show -json` output),
- reference solutions per arm.

Populated in Slice C. Keeping this mechanical (rather than hand-duplicating tasks) is
what makes the oracle-equivalence CI in Slice E meaningful.
