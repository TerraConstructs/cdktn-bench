# sfn-jsonata live check

Design notes for the hand-authored oracle at
`tasks/*/sfn-jsonata-*/tests/live_check.py` (spec: `specs/sfn-jsonata.yaml`).

## Why a live check is the only thing that can see this catch

The graded fact is what a `{% ... %}` JSONata expression COMPUTES. Every static
tier this scenario has reads the expression as an opaque string: `tsc`
type-checks the TypeScript string type, `cdk synth` copies it verbatim into the
template, `terraform validate`/`plan` treat the whole ASL document as one
JSON-encoded attribute, and the tier-1 cfn-guard/Rego bundles inspect ASL
STRUCTURE (which keys and substrings are present), never JSONata SEMANTICS. A
flipped comparison operator or a wrong arithmetic expression is therefore
syntactically valid JSONata, structurally valid ASL, and invisible to
`reward.txt` -- which is exactly the anti-L2 falsifiability catch
`jsonata-expression-correctness` (prereg §5 / H2).

Step Functions' `TestState` API evaluates one state for real and returns what it
produced. It needs no `roleArn` for Pass and Choice states (a role is required
only for Task states that touch resources) and it CREATES NOTHING, which is why
this scenario stays `[concurrency] mode = "read-only"` despite having a live
check.

## What it asserts

Every case is a property of what the SERVICE computed.

1. `ComputeTotals` on a two-order batch returns each order with the right
   per-order `total` and the right batch `grandTotal`.
2. The same for a second, differently-valued batch -- a hardcoded literal
   `Output` tuned to case 1 cannot also satisfy case 2.
3. `CheckBudget` routes an over-budget batch to a state of ASL `Type` `Fail`.
4. It routes a boundary batch (a grand total exactly AT the cap, which does not
   exceed it) to a `Succeed`.
5. It routes an under-budget batch to a `Succeed`.

Grading only the over-budget side would score `pass` for a condition of
`{% true %}`, for `> 0`, for a `>=` where the prompt says "exceeds", and for a
machine whose `Default` is the Fail state.

A branch is graded by the ASL `Type` of the state TestState names as
`nextState`, not by its name: the prompt fixes the two state names it grades
(`ComputeTotals`, `CheckBudget`) and leaves the Fail/Succeed states unnamed, so
a correct solution may call them anything. That state's `Next` chain is followed
a bounded number of hops, so routing over an intermediate Pass state still
matches.

Each `CheckBudget` case takes its input from a REAL `ComputeTotals` run on that
batch, feeding the observed output and any variables that state assigned into
the graded call. Carrying the total in an assigned variable (`Assign` plus
`{% $grandTotal > 1000 %}`) is as correct as carrying it in the state output,
and a hand-written `{"grandTotal": N}` literal would score the variable form
0.0.

## Outcome contract

`specs/SCHEMA.md` §5, gating. A JSON object on stdout with an `outcome` of:

- `pass` -- every case matched.
- `fail_stale` -- Step Functions evaluated the definition and what it produced
  contradicts at least one case. A TestState `status` other than `SUCCEEDED` is
  also this (the service rejected the agent's own expression), as is a
  definition the API refuses outright (`ValidationException`,
  `InvalidDefinition`, a graded state name that does not exist): those are
  verdicts about the artifact, not about the infrastructure.
- `not_verifiable` -- the check could not be run at all: no artifact, no state
  machine in it, a definition that is not a decodable JSON string, a definition
  that is `(known after apply)` in this plan, no `aws` CLI, no credentials,
  `AccessDenied`, throttling, or any other API error. Never a statement about
  the solution.

`tests/test.sh` downgrades reward to 0.0 for anything that is not `pass`,
because an unverifiable claim must not silently earn reward; `reason` and
`not_verifiable_kind` are what keep an infrastructure failure legible as one
rather than reading as a bad solution.

## Two call shapes

Matching this repo's convention (see `named-resource-replacement`'s own
`live_check.py`):

- verifier-invoked, no args -- prints the JSON, always exits 0. The exit code is
  not the verdict; `.outcome` is.
- fixture-invoked, `--expect {ok,stale}` -- used by `solution/solve.sh` and
  `solution/broken/*/solve.sh` under `LIVE=1`. Prints the same JSON and exits
  non-zero when the observed outcome contradicts what the caller asserted.

## Bounded by construction

One TestState call per case, plus one per chained case's source state, and no
polling. TestState is synchronous and its answer does not converge over time, so
a retry buys nothing except against throttling, which is the one retry the file
implements.
