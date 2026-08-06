# Oracle intent: Step Functions order-batch transform (JSONata query language)

`sfn-jsonata` — generated verbatim from `specs/sfn-jsonata.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/sfn-jsonata/policy.rego` and `../cfn-guard/sfn-jsonata/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/sfn-jsonata.yaml` instead.

---

Exactly one AWS::StepFunctions::StateMachine exists, whose ASL definition's top-level QueryLanguage is exactly "JSONata". The definition contains a state named ComputeTotals whose output is an object with an `orders` array (every input order plus a `total` field equal to quantity times price) and a `grandTotal` number (the sum of every order's total), computed via a `{% ... %}` JSONata expression. The definition contains a state named CheckBudget that branches on grandTotal via a `{% ... %}` JSONata condition: greater than 1000 leads to a Fail state, otherwise to a Succeed state. Nowhere in the definition does any JSONPath-mode ASL field (InputPath, OutputPath, Parameters, ResultPath, ResultSelector, ItemsPath) appear, and nowhere does a raw, un-evaluated `"$."`-prefixed JSONPath string appear as a literal value in place of a proper JSONata expression.
