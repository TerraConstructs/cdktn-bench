Add the event-processor Lambda to the platform stack.

Its logs must be retained for 30 days — not indefinitely, we are paying
for that today — and when this stack is torn down, nothing of it may
be left behind in the account.

Author this using terraconstructs (TypeScript) L2 constructs, synthesized via cdktn.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
