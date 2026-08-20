This workspace holds the network configuration for one internal service: a
small VPC with a single private subnet, a security group, and an interface
VPC endpoint for AWS Systems Manager. It is already deployed in this
account.

Our security-group naming convention changed: every security group must now
be prefixed with the name of the team that owns it. This service is owned by
the `platform` team.

Rename the security group in this workspace to
`platform-internal-services-ssm-endpoint`, then roll the change out to this
account with your toolchain's real deploy command. The interface VPC
endpoint must still be reachable on port 443 from inside the VPC when you
are done, and must not become reachable from anywhere else.

This workspace is a terraconstructs (TypeScript) app using its AWS L2 constructs.

`lib/scenario-stack.ts` in this workspace holds this project's existing configuration -- change it as needed. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to change.

Real deploy note: `main.ts` (which you must not edit, see above) defaults to an offline fixture with dummy AWS credentials -- before running your REAL deploy command, export `CDKTN_BENCH_LIVE=1` in your shell so `main.ts` uses this environment's real ambient AWS credentials instead. This is a normal environment variable, not a change to `main.ts` itself.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
