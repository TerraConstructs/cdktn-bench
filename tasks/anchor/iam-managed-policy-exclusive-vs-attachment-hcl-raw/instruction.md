Our batch platform needs two IAM roles:

- `batch-runner`, assumed by ECS tasks, and
- `report-writer`, assumed by Lambda.

Both roles need read access to our reporting data in S3 (the AWS managed
policy AmazonS3ReadOnlyAccess), and both need the same team-defined policy
allowing them to write metrics to CloudWatch. Other teams attach their own
policies to these roles out of band; that must keep working.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
