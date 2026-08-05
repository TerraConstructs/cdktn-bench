# oracles/rego

Rego/OPA policies graded against `terraform show -json` plan output, for the
`hcl-raw` and `terraconstructs` arms (both synthesize to Terraform).

One `.rego` bundle per scenario catch (see `docs/iac-abstraction-aws-bench-plan.md`
Phase 1 seed-scenario table for the planted catches these need to assert on).
Populated in Slice D, validated by the oracle-equivalence CI in Slice E.
