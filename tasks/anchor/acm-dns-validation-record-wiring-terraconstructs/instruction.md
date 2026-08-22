We are moving the storefront to a new domain. Create the public hosted
zone for `storefront.example.com` and an ACM certificate covering both
`storefront.example.com` and `www.storefront.example.com`, validated through DNS in that
zone.

The certificate has to be usable by the load balancer we add next
quarter -- so it must reach ISSUED on its own, without anyone clicking
through the console.

Author this using terraconstructs (TypeScript) L2 constructs, synthesized via cdktn.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
