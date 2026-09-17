Create the release-artifact bucket for the delivery pipeline.

Only the pipeline identity — the IAM role this configuration is deployed
with — may read or write objects in it. No other principal in the account
may, including other roles and users; the bucket policy is the control we
are relying on, so it has to name that role and nothing broader.

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
