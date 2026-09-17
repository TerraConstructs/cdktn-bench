Publish the orders service behind an HTTP API (API Gateway v2) on a stage
called `prod`, backed by a Lambda function on `GET /orders` that returns
{"orders": []} with HTTP 200.

Sustained traffic must be limited to 100 requests per second across the
API. Short spikes are normal for this service and must still be served —
up to 200 requests in a burst.

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
