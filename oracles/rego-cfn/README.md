# oracles/rego-cfn

Rego/OPA policies graded against the **awscdk** arm's synthesized
CloudFormation template (`cdk.out/ScenarioStack.template.json`) — the same
artifact `../cfn-guard/` grades, read by the same engine the TF arms use.

One `.rego` bundle per scenario, present **only** for a scenario whose spec
sets `oracle.awscdk_tier1_engine: rego` (`specs/SCHEMA.md` §4.5). A scenario
that leaves the field at its default (`cfn_guard`) has no directory here at
all; its awscdk tier-1 bundle lives in `../cfn-guard/<id>/policy.guard`.

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

The package name is shared deliberately: the generated
`tests/static_tiers.sh` runs one identical `opa eval -f raw -I -d policy.rego
'data.<pkg>.deny' < "$ARTIFACT"` line on every arm. The two files never load
into one OPA instance — each is copied into its own arm's `tests/` directory
as the only policy there.

## Why the engine exists (ROADMAP.md M8)

cfn-guard 3.2.0 cannot express a **cross-resource join** — there is no way to
say "this `AWS::IAM::ManagedPolicy`'s `Roles` list references the logical id of
that `AWS::IAM::Role`". Encoding such an intent in cfn-guard forces a proxy
(e.g. count equality), and a proxy is unsound in both directions: it passes
solutions that violate the intent and fails solutions that satisfy it, while
the byte-equivalent Terraform solution scores the opposite way. `DECISIONS.md`
Amendment 29 §4 makes equal-strictness cross-arm grading binding, so a scenario
whose intent needs that join must select `rego` here.

`cfn-guard` remains installed in the awscdk arm image and fully supported: it
is a real tool an awscdk team has, and it is retained as a **measured arm
capability**. It is simply not the grading authority whenever a cross-arm
comparison is what the scenario is for.

## Authoring rules

- Amendment 29 §4 is binding: never key identity on a physical name
  (`Properties.RoleName`, `BucketName`, …). Grade existence + type +
  properties, joined on **logical id**.
- Encode every tier-`"1"` `structural_assert` and every `cfn_guard_hints`
  bullet the spec declares — those hints describe the CFN shape and apply to
  this file whichever engine reads them.
- The stub `oracles/emit.py` scaffolds carries a `GENERATOR-STUB` marker that
  the generated `tests/_assert_lib.sh::is_stub_policy()` greps for. Delete that
  line once real rules are in, and not before: leaving it makes tier-1 report
  `SKIPPED_STUB` (a hard verifier failure), removing it early makes an empty
  policy start gating trials.
