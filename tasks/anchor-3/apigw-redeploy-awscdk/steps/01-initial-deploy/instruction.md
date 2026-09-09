Build and deploy a REST API on Amazon API Gateway, for REAL, in
this AWS account: named EXACTLY
`apigw-redeploy-api`, with two routes -- `GET /hello` and
`GET /version` -- each backed by its own Lambda function via a
Lambda proxy integration (any inline/trivial handler body is fine;
its exact response content is not graded, only that it returns
HTTP 200). Deploy the API to a stage named `prod`.

Actually run your toolchain's real deploy command against this
account (not just synth/plan), and confirm by making real HTTP
requests to the deployed stage that both `GET /hello` and
`GET /version` return HTTP 200.

Standing constraints, in force for everything you do in this workspace:

Write `/logs/agent/agent-output.json` (see the JSON contract below)
recording the deployed stage's real invoke URL, so it can be
independently re-checked afterward.

Environment constraint: any IAM role your solution creates (for
example, a Lambda function's execution role) must be created under
the path `/cdktn-bench-task/` (e.g. `path = "/cdktn-bench-task/"` on a
Terraform `aws_iam_role`, or `path: "/cdktn-bench-task/"` on a CDK/
terraconstructs `iam.Role`) -- this account's deploy credentials only
permit creating and passing roles under that path.

Do NOT delete the REST API, the Lambda functions, their execution
role, or any CloudWatch Logs log groups when you are done -- leave
every resource you created running and deployed. This task's grading
depends on re-checking your work against the live stage after your
work ends, so tearing anything down yourself would erase the only
evidence that your deploy took effect. Cleanup of this account is
handled automatically by the benchmark itself once grading is
complete; it is not part of your task.

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs (apigateway.RestApi, LambdaIntegration). Deploy for real with `npx cdk deploy`.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.

Additionally, write `/logs/agent/agent-output.json` containing exactly:

```json
{
  "api_url": "<the deployed stage's real invoke URL, e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod/ (trailing slash)>"
}
```
