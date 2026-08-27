Create a new AWS Step Functions state machine that processes a batch of
orders and applies a spending-budget check.

The state machine's execution input is shaped like:

  { "orders": [ { "id": "<string>", "qty": <number>, "price": <number> }, ... ] }

Add a state named `ComputeTotals` whose output is a JSON object with two
fields: `orders` -- every input order, each with a `total` field added
equal to that order's quantity multiplied by its price (alongside its
existing `id`, `qty`, and `price` fields) -- and `grandTotal` -- the sum
of every order's `total` across the whole batch.

Add a state named `CheckBudget` that branches on `grandTotal`: if it
exceeds 1000, the execution must fail (reach a Fail state); otherwise
the execution must succeed (reach a Succeed state).

Build the entire state machine using AWS Step Functions' JSONata query
language (`QueryLanguage: JSONata`) for every state's input, output, and
branching logic -- not the classic JSONPath query language.

Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs (the aws-cdk-lib/aws-stepfunctions module).

You own only `lib/scenario-stack.ts` in this workspace -- write your entire solution there. Do not create, modify, or delete `bin/app.ts`: it is a pre-wired bootstrap file (app entrypoint / provider config) that synth/plan depends on and is not part of what you are being asked to write.

IMPORTANT: Write your final answer to `/logs/agent/agent-output.txt`.
