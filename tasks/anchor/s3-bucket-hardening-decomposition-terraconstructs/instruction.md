We need an S3 bucket for archived customer documents.

Every version of an object must be kept, including after an overwrite or a
delete. Objects must be encrypted at rest with a KMS key that we control,
not with S3's default key. Any request that is not made over TLS must be
rejected. The bucket and its contents must not be reachable by anyone
outside this account under any circumstances.

Author this using terraconstructs (TypeScript) L2 constructs, synthesized via cdktn.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
