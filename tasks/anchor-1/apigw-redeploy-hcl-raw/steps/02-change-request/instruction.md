This account already runs the REST API `apigw-redeploy-api`,
deployed to its `prod` stage, serving `GET /hello` and
`GET /version`. The source that produced it is in your workspace,
exactly as it was left; read it before changing anything.

Change request: add ONE more route, `GET /status`, using a MOCK
integration (no Lambda) whose response is the fixed JSON body
`{"status": "ok", "routes": 3}` for every request.

Re-run your toolchain's real deploy command so the SAME stage
(`prod`, same REST API) serves this new route too. Then confirm, by
making real HTTP requests to that same deployed stage, that
(a) `GET /status` returns HTTP 200 with exactly that JSON body,
AND (b) `GET /hello` and `GET /version` still return HTTP 200 --
the change must not regress the routes that already worked.

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

Author this as hand-written Terraform HCL (no modules). Deploy for real with `terraform apply`.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.

Additionally, write `/logs/agent/agent-output.json` containing exactly:

```json
{
  "api_url": "<the deployed stage's real invoke URL, e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod/ (trailing slash)>"
}
```
