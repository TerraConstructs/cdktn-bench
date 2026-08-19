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

## `cdk_app` runs precompiled JS — rebuild `dist/` before running it locally

`scenario/cdk_app/cdk.json` sets `"app": "node dist/lib/app.js"` (it used to be
`npx ts-node lib/app.ts`). ts-node's in-process type-check peaked at ~1.7 GB
tree RSS inside the 4096 MB deploy container and is the explained cause of the
historical `exit 137` — see `docs/ts7-spike-results.md` and
`docs/ts-runtime-spike2-results.md`. There is deliberately **no** chained
`tsc &&` in this app string (unlike the graded arms' `cdktf.json`/`cdk.json`):
this tree is harness plumbing that no agent ever edits, so the compile is baked
once at image build (`scenario/Dockerfile`: `npm ci && npm run build`) instead
of being paid on every CLI invocation.

Consequence for **local** use (outside the scenario image), e.g. running
`npx cdk synth` in `scenario/cdk_app/` by hand: `dist/` is git-ignored and will
not exist on a fresh clone, and it is **not** rebuilt automatically by
`cdk synth`. Run the build first, and again after **any** `.ts` edit:

```sh
cd scenarios/anchor/scenario/cdk_app
npm ci          # first time only
npm run build   # == tsc, emits dist/lib/app.js + dist/stacks/*.js
npx cdk synth   # now reads the freshly-emitted JS
```

`deploy/deploy.sh` already runs `npm run build` before `cdk deploy`, so the
deploy path stays correct on its own.

> After changing anything under `scenarios/anchor/**` (including the
> Dockerfile/`cdk.json` change above), re-run `env setup` — otherwise resets
> fail with a scenario-source-hash mismatch (see `CLAUDE.md`).
