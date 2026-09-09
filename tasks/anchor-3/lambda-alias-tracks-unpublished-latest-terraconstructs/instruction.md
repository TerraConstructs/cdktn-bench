This workspace holds a small internal quote service: one AWS Lambda
function, the IAM role it runs as, and the alias that callers use to reach
it. It is already deployed in this account.

Our quote service must report prices in US dollars from now on. Its
`QUOTE_CURRENCY` environment variable is still set to `EUR` — set it to
`USD` and roll the change out to this account with your toolchain's real
deploy command.

Every caller reaches this function through its alias, so that alias must be
serving `QUOTE_CURRENCY=USD` when you are done.

This workspace is a terraconstructs (TypeScript) app using its AWS L2 constructs.

`lib/scenario-stack.ts` in this workspace holds this project's existing configuration -- change it as needed. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to change.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
