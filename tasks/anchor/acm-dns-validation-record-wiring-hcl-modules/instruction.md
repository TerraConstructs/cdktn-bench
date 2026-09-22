We are moving the storefront to a new domain. Create the public hosted
zone for `storefront.example.com` and an ACM certificate covering both
`storefront.example.com` and `www.storefront.example.com`, validated through DNS in that
zone.

The certificate has to be usable by the load balancer we add next
quarter -- so it must reach ISSUED on its own, without anyone clicking
through the console.

Author this as Terraform HCL composed from `terraform-aws-modules` registry modules: they are the real `terraform-aws-modules` sources, served at an allowlisted set of versions you can discover at this environment's registry endpoint.

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
