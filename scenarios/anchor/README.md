# scenarios/anchor

The near-empty **anchor scenario** (build plan Phase 0, mismatch M1): one trivial CDK
stack whose only job is to satisfy aws-bench's `env init` / `env setup` / `env cleanup`
lifecycle, which hard-requires a real AWS Organizations member account per scenario
(`AwsBenchSingleStepTrial._staged_credentials` raises on an empty account mapping — see
`docs/aws-bench-guide.md` §8.1).

This scenario exports nothing meaningful and is deployed once, reused by every task in
this benchmark. All actual grading is offline (synth/plan + static oracles) inside the
agent's own container — the anchor scenario exists purely to satisfy the harness's
"real AWS account" precondition at ~$0 marginal spend.

Populated in Slice A/F per `aws-bench-datasets-guide.md` §6a (`scenario.toml`,
`scenario/Dockerfile`, `scenario/cdk_app/`, `deploy/deploy.sh`).
