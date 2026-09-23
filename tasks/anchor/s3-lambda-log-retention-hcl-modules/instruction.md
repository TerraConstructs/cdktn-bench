Create a new S3 bucket.

Create a new AWS Lambda function. Configure the bucket so that the
function is automatically invoked whenever a new object is uploaded to
it (an s3:ObjectCreated:Put event).

Ensure the Lambda function's logs are retained for 10 days.

Author this as Terraform HCL composed from `terraform-aws-modules` registry modules: they are the real `terraform-aws-modules` sources, served at an allowlisted set of versions you can discover at this environment's registry endpoint.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
