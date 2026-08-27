Add the event-processor Lambda to the platform stack.

Its logs must be retained for 30 days — not indefinitely, we are paying
for that today — and when this stack is torn down, nothing of it may
be left behind in the account.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
