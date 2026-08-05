# specs

Intent specs: one YAML file per scenario, the single source of truth `../generator/`
expands into per-arm task directories, oracle invocations, and reference solutions.

Spec shape (finalized in Slice C) captures: the shared natural-language prompt body,
the planted catch(es) and which oracle tier is predicted to catch each one, per-arm
target-language substitution points, and any scenario-level AWS resources needed from
`../scenarios/anchor` or a scenario-specific stack.

See `docs/iac-abstraction-aws-bench-plan.md` Phase 1 for the seed-scenario table this
first batch of specs implements (`s3-lambda-log-retention`, `ecs-swappiness`,
`sfn-jsonata`, `apigw-openapi`).
