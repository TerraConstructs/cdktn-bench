Create the release-artifact bucket for the delivery pipeline.

Only the pipeline identity — the IAM role this configuration is deployed
with — may read or write objects in it. No other principal in the account
may, including other roles and users; the bucket policy is the control we
are relying on, so it has to name that role and nothing broader.

Author this as Terraform HCL composed from `terraform-aws-modules` registry modules: they are the real `terraform-aws-modules` sources, served at an allowlisted set of versions you can discover at this environment's registry endpoint.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
