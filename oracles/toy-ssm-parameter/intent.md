# Oracle intent: Toy: SSM parameter + read-only IAM role

`toy-ssm-parameter` — generated verbatim from `specs/toy-ssm-parameter.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/toy-ssm-parameter/policy.rego` and `../cfn-guard/toy-ssm-parameter/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/toy-ssm-parameter.yaml` instead.

---

Exactly one AWS::SSM::Parameter (type String) named /cdktn-bench-toy/greeting with value hello-from-cdktn-bench exists in the synthesized artifact. Exactly one IAM role exists whose trust policy permits only ec2.amazonaws.com to assume it. That role's attached policy grants only ssm:GetParameter (and/or ssm:GetParameters) scoped to this specific parameter's ARN — no wildcard resource, no other SSM actions, no other services' actions.
