Create a new SSM parameter of type String named `/cdktn-bench-toy/greeting`
with the value `hello-from-cdktn-bench`.

Create a new IAM role that a service can assume to read this parameter.
Trust only the EC2 service principal (`ec2.amazonaws.com`). Grant the
role permission to read this specific parameter's value — nothing
broader, and no permission to write, delete, or list other parameters.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
