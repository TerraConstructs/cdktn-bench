# tasks

Generated task directories, one per `(scenario × arm)` pair:
`tasks/<scenario-id>/<arm>/`. Never hand-authored — produced by `../generator/` from
one intent spec per scenario under `../specs/`, per
`docs/iac-abstraction-aws-bench-plan.md` Phase 1 ("Generator (M2)").

Each generated task dir follows the aws-bench task anatomy (`task.toml`,
`instruction.md`, `environment/Dockerfile` from the arm, `tests/`, `solution/`) per
`docs/aws-bench-datasets-guide.md` §2, with `tests/check.py` / oracle scripts kept
byte-identical in intent (not necessarily byte-identical in code, since CDK-synth vs
Terraform-plan artifacts differ) across arms for the same scenario — that equivalence
is enforced by the oracle-equivalence CI (Slice E).
