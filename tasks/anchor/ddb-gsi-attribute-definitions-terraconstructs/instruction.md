Create the DynamoDB table for the orders service.

Each order is identified by orderId, belongs to a customerId, and
records when it was placed as createdAt. The support tooling needs to
list one customer's orders newest-first, and for that listing it only
ever shows the order's status and totalAmount -- nothing else should be
read from the index.

Items also carry shippingAddress, lineItems and a paymentReference.

Author this using terraconstructs (TypeScript) L2 constructs, synthesized via cdktn.

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `main.ts`: it is a pre-wired bootstrap file (app entrypoint / offline provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
