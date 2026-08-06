Create a new Amazon ECS task definition compatible with the EC2 launch
type. It must contain exactly one container definition — choose any
reasonable image, name, and memory allocation for it. Tune the
container's memory swappiness behavior to 42.

This is a definition-only task: nothing needs to be deployed, started,
or attached to a cluster or service.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
