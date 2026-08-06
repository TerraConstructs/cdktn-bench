A small OpenAPI 3 specification describing a "Widgets" HTTP API is
provided read-only in your workspace. It has three routes across two
paths. Implement an Amazon API Gateway REST API that provides every
route the specification describes: each route is its own API Gateway
resource and method, individually reachable and individually wired --
not an API whose routes exist only inside an imported OpenAPI document
body. For each route, create a Lambda function to handle it and wire a
Lambda proxy integration from that route to its function, granting API
Gateway permission to invoke the function. Deploy the API to a stage so
all three routes are reachable.

Two supporting files are seeded read-only in your workspace: the
OpenAPI 3 spec itself, at `openapi/widgets-api.json`, describing the
exact routes to implement; and a placeholder Lambda deployment package,
at `lambda/placeholder.zip`, which you may reference if your toolchain
requires an existing code archive rather than inline source (its
contents are not graded -- only that a real Lambda function exists and
is correctly wired).

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write. `openapi/widgets-api.json`, and `lambda/placeholder.zip` are also seeded read-only in this workspace as reference input -- read them as needed, but do not modify them.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
