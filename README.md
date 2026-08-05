# cdktn-bench

IaC-abstraction benchmark (AWS CDK L2 vs raw HCL vs terraconstructs) built on the aws-bench runner.
Design source of truth: ../iac-abstraction-benchmark-prereg.md · build plan: ../docs/iac-abstraction-aws-bench-plan.md

Arms (see `DECISIONS.md` Amendment 2 for the full rationale, including the dropped
`terraform-aws-modules` arm): `arms/awscdk` and `arms/hcl-raw` are primary;
`arms/terraconstructs` is a limited-coverage third arm. No Pulumi, no chant.

## Layout

| Path | Purpose |
| --- | --- |
| `arms/{awscdk,hcl-raw,terraconstructs}/` | Per-arm toolchain Dockerfile + generated task dirs |
| `scenarios/anchor/` | Near-empty scenario satisfying aws-bench's real-AWS-account precondition |
| `tasks/` | Generated `<scenario>/<arm>` task directories (never hand-authored) |
| `generator/` | Intent-spec → task-dirs + oracle-wiring expander |
| `oracles/{rego,cfn-guard}/` | Static oracle policies (Terraform-plan / CFN-synth tiers) |
| `gates/` | preflight / audit / emit-result integrity gates + equipping hash |
| `metrics/` | Custom tokens-to-green + tier-attribution aggregation scripts |
| `ci/` | Oracle-equivalence CI + negative tests |
| `specs/` | Intent specs (one YAML per scenario), source of truth for the generator |

## Setup

```bash
make setup       # uv sync
make build-arms  # docker build each arm's environment/Dockerfile
make preflight   # confirm each arm's toolchain works in its container
make check       # placeholder; populated in Slice E
```

See `DECISIONS.md` for the aws-bench pin, packaging notes, and amendment log.
