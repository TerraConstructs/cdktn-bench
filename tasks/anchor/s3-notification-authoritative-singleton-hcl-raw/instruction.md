The media bucket needs two things wired up.

Product: when a file is uploaded, the ingest function must run so the
asset is transcoded.

Compliance: when any object is deleted, the audit topic must receive a
notification so deletions show up in the quarterly review.

Both signals need to come straight from the bucket itself, not through
any shared notification or messaging layer other teams might also be
plugged into.

Author this as hand-written Terraform HCL (no modules).

You own only `main.tf` in this workspace -- write your entire solution there. Do not create, modify, or delete `provider.tf`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
