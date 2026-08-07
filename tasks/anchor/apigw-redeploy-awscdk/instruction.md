Build a REST API on Amazon API Gateway, deploy it for REAL to this AWS
account, confirm it serves, apply a prescribed configuration change,
and re-deploy it -- all inside this one task.

Step 1 -- author and deploy revision 1: a REST API named EXACTLY
`apigw-redeploy-api`, with two routes: `GET /hello` and `GET /version`,
each backed by its own Lambda function via a Lambda proxy integration
(any inline/trivial handler body is fine -- its exact response content
is not graded, only that it returns HTTP 200). Deploy the API to a
stage named `prod`. Actually run your toolchain's real deploy command
against this account (not just synth/plan) and confirm, by making a
real HTTP request to the deployed stage, that both `GET /hello` and
`GET /version` return HTTP 200.

Step 2 -- apply the prescribed modification and re-deploy: add ONE
more route, `GET /status`, using a MOCK integration (no Lambda) whose
response is the fixed JSON body `{"status": "ok", "routes": 3}` for
every request. Re-run your toolchain's real deploy command so the
SAME stage (`prod`, same REST API) now serves this new route too. Then
confirm, by making real HTTP requests to the same deployed stage, that
(a) `GET /status` now returns HTTP 200 with exactly that JSON body,
AND (b) `GET /hello` and `GET /version` still return HTTP 200 (the
modification must not regress the routes that already worked).

A second deploy that does not actually create a new, live-serving
deployment behind the stage -- so the stage keeps serving stale
content despite your deploy command exiting successfully -- is exactly
the mistake this task exists to test for; make sure your redeploy
genuinely takes effect, not just that the command you ran returned
success.

Write `/logs/agent/agent-output.json` (see the JSON contract below)
recording the deployed stage's real invoke URL, so it can be
independently re-checked afterward.

Finally, clean up every AWS resource you created (the REST API, both
Lambda functions, their execution role, and any CloudWatch Logs log
groups AWS auto-created for them) so the account is left exactly as
you found it -- this is a real, billed AWS account shared with other
tasks.

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs (apigateway.RestApi, LambdaIntegration, MockIntegration). Deploy for real with `npx cdk deploy`.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.

Additionally, write `/logs/agent/agent-output.json` containing exactly:

```json
{
  "api_url": "<the deployed stage's real invoke URL, e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod/ (trailing slash)>"
}
```
