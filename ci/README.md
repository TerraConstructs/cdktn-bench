# ci

Oracle-equivalence CI (build plan Phase 1 / §3 of the pre-registration): runs both
oracle tiers (`../oracles/rego`, `../oracles/cfn-guard`) against all three arms'
reference solutions on every commit. A scenario whose oracles diverge in strictness
across arms fails CI and is not usable in a run.

Also home to negative tests (a deliberately broken reference solution per planted
catch must score 0 at the predicted tier — build plan Phase 2 exit criterion) and any
repo-level lint/format checks (mirroring `aws-bench-datasets`'s `make ready` pattern:
build + test + schema checks).

Populated in Slice E.
