This workspace holds the storage configuration for one archive bucket: a
single S3 bucket, and one retention rule on it that deletes objects under
the `logs/` prefix 30 days after they are written. It is already deployed
in this account.

Storage spend on this archive bucket is growing. Objects written under the
`exports/` prefix are read constantly for their first quarter and almost
never afterwards.

Move objects under the `exports/` prefix into the Glacier Instant Retrieval
storage class 90 days after they are created, then roll the change out to
this account with your toolchain's real deploy command.

Objects under the `logs/` prefix must still be deleted 30 days after they
are written when you are done.

This workspace is a terraconstructs (TypeScript) app using its AWS L2 constructs.

`lib/scenario-stack.ts` in this workspace holds this project's existing configuration -- change it as needed. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to change.

Real deploy note: `main.ts` (which you must not edit, see above) defaults to an offline fixture with dummy AWS credentials -- before running your REAL deploy command, export `CDKTN_BENCH_LIVE=1` in your shell so `main.ts` uses this environment's real ambient AWS credentials instead. This is a normal environment variable, not a change to `main.ts` itself.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
