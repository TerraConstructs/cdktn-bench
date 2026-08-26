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

This workspace is an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs.

`lib/scenario-stack.ts` in this workspace holds this project's existing configuration -- change it as needed. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to change.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
