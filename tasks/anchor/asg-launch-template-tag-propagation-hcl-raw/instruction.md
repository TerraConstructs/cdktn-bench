Stand up an Auto Scaling group of worker instances for the batch
platform: the fleet must run at least 2 instances at all times,
scaling up to at most 6 as load grows, in a new VPC with two private
subnets. Instances run AMI ami-0c55b159cbfafe1f0 on t3.small.

Finance reconciles our EC2 spend from tags. Every instance the group
launches, and every EBS volume attached to it, must carry
CostCenter=platform-42 and Environment=prod — including instances the
group launches later when it scales out.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
