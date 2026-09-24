The service needs its own ECR repository. Images are scanned on push, and
only the last 10 images are kept.

These environments are created and destroyed on a nightly cycle by the
platform pipeline, which has no manual steps: removing this configuration
has to leave the account clean, with the repository and its images gone.

Deploy the repository to this account with your toolchain's real deploy
command, and leave it in place when you are done.

Author this as Terraform HCL composed from `terraform-aws-modules` registry modules: they are the real `terraform-aws-modules` sources, served at an allowlisted set of versions you can discover at this environment's registry endpoint.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
