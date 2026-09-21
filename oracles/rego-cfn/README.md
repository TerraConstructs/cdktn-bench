# oracles/rego-cfn

Rego/OPA policies graded against the **awscdk** arm's synthesized
CloudFormation template (`cdk.out/ScenarioStack.template.json`), read by the
same `opa eval` the TF arms run over plan JSON.

One `.rego` bundle per scenario. Every scenario has one: OPA/Rego is the tier-1
engine on every arm (`specs/SCHEMA.md` §4.5). A scenario with no tier-`"1"`
awscdk assert keeps the generator's stub here, which tier 1 never reaches.

## Why this is a separate tree from `../rego/`

Same language, same `deny` contract, same package name
(`cdktn_bench.<scenario_id_with_underscores>`) — but a **different `input`
document**:

| tree | arms | `input` at eval time | join key |
|---|---|---|---|
| `../rego/<id>/policy.rego` | `hcl_raw`, `terraconstructs` | `terraform show -json` plan JSON | plan **address** |
| `rego-cfn/<id>/policy.rego` | `awscdk` | CloudFormation template JSON | **logical id** |

Those documents are structurally unrelated: `input.planned_values.root_module.
resources[]` with `.type`/`.address`/`.values` on one side,
`input.Resources[<LogicalId>]` with `.Type`/`.Properties` and `{"Ref": ...}` /
`{"Fn::GetAtt": [...]}` reference objects on the other. A single policy body
that served both would just be two policies sharing a file, with a runtime
shape sniff deciding which half runs — strictly worse to review, and exactly
the place a cross-arm strictness gap hides. They stay separate files.

The package name is shared deliberately: the generated verifier runs one
identical `opa eval -f raw -I -d policy.rego 'data.<pkg>.deny' < "$ARTIFACT"`
line on every arm. The two files never load into one OPA instance — each is
copied into its own arm's `tests/` directory as the only policy there.

## Why this tree exists at all (ROADMAP.md M8, DECISIONS.md Amendment 45)

cfn-guard 3.2.0 cannot express a **cross-resource join** — there is no way to
say "this `AWS::IAM::ManagedPolicy`'s `Roles` list references the logical id of
that `AWS::IAM::Role`". Encoding such an intent in cfn-guard forces a proxy
(count equality, an allowlist, a bare existence check), and a proxy is unsound
in both directions: it passes solutions that violate the intent and fails
solutions that satisfy it, while the byte-equivalent Terraform solution scores
the opposite way. Amendment 29 makes equal-strictness cross-arm grading
binding, so cfn-guard was retired as the oracle and this tree replaced it.

`cfn-guard` remains installed in the awscdk arm image and fully supported: it
is a real tool an awscdk team has, and it is retained as a **measured arm
capability**. It is simply never the grading authority.

## Authoring rules

- Amendment 29 is binding: never key identity on a physical name
  (`Properties.RoleName`, `BucketName`, …). Grade existence + type +
  properties, joined on **logical id**.
- Read a reference the way the TF half does — through ANY expression that
  names the target (`Ref`, `Fn::GetAtt`, and either nested inside `Fn::Join` or
  `Fn::Sub`), not one privileged spelling. The TF half consumes Terraform's
  pre-computed `.references` list, so accepting a single CFN spelling is a
  strictness break, not a simplification.
- Encode every tier-`"1"` `structural_assert` and every `cfn_guard_hints`
  bullet the spec declares — those hints describe the CFN shape and apply to
  this file.
- Fail closed. A rule quantified over a collection denies nothing when the
  collection is empty, so every such rule needs a companion stating the
  shortfall directly.
- A fact the template cannot settle belongs in `not_verifiable` (non-gating,
  logged) — never in a silently-absent `deny`.
- The stub `oracles/emit.py` scaffolds carries a `GENERATOR-STUB` marker that
  the generated `tests/tiers.py::is_stub_policy()` greps for. Delete that line
  once real rules are in, and not before: leaving it makes tier-1 report
  `SKIPPED_STUB` (a hard failure), removing it early makes an empty policy
  start gating trials.
