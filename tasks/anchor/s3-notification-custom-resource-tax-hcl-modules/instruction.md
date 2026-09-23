Claims documents land in an S3 bucket and must be handed to the claims
processor function as they arrive.

Platform constraint for this account: a stack may only contain the
compute it is being deployed to run. The claims processor is the only
function this stack is allowed to create — no helpers, no
deployment-time functions, no functions belonging to the tooling.

Author this as Terraform HCL composed from `terraform-aws-modules` registry modules: they are the real `terraform-aws-modules` sources, served at an allowlisted set of versions you can discover at this environment's registry endpoint.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
