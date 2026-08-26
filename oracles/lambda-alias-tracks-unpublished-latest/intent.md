# Oracle intent: Change a Lambda function's configuration behind an alias that names a version nothing republishes

`lambda-alias-tracks-unpublished-latest` — generated verbatim from `specs/lambda-alias-tracks-unpublished-latest.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/lambda-alias-tracks-unpublished-latest/policy.rego` and `../cfn-guard/lambda-alias-tracks-unpublished-latest/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/lambda-alias-tracks-unpublished-latest.yaml` instead.

---

A correct solution leaves this workspace deploying the same system it
described before, with two things true that were not true before: the
function's `QUOTE_CURRENCY` is `USD`, and its alias actually resolves
to a configuration carrying that value.

Two things are graded, in two different places, and the split is the whole
point of the scenario:

1. TIER 0 (static, every arm). The function's environment carries
   `QUOTE_CURRENCY = USD`, and the alias still exists under the name the
   seed gave it. This is
   what makes the DO-NOTHING answer fail — the seed already deploys green,
   so without the environment assert an agent that changed nothing would
   score 1.0 (see `solution/broken/seed-unchanged/`, which exists to keep
   proving exactly that). On the two Terraform arms tier 0 additionally sees
   that the alias is no longer wired to the one version the seed named,
   because `terraform show -json` puts that value in the graded artifact.

2. LIVE (`tests/live_check.py`, gating). Whether the change ACTUALLY REACHED
   the callers. This is the only instrument that can speak for the awscdk
   arm at all: there, the poisoned and the corrected stack synthesize
   CloudFormation templates that are identical apart from one CDK-generated
   logical id, so the account is the only place the difference exists. The
   live check reads the alias's own resolved configuration out of
   Lambda and requires `QUOTE_CURRENCY=USD`.

WHAT IS DELIBERATELY NOT GRADED, and why each is a decision rather than an
oversight:

* HOW the alias comes to point somewhere useful. Deriving the target from
  the function is the maintainable answer and is what a reviewer would ask
  for, but an agent that inspects the account and writes the new version
  number down, or that points the alias at the function's unqualified
  `$`-latest target, has done what the ticket asked. Both are accepted:
  tier 0 only refuses the value the SEED had, and the live check only asks
  what the alias serves. Forcing the derived shape would be
  `apigw-openapi`'s "alternative shape scored wrong" failure repeated
  (docs/adding-scenarios.md §3a).
* How many resources each arm's expansion produced, and whether the Lambda
  package is inline, archived or in S3. The arms are compared on the
  declared behavioural facts only.

NO TIER-1 POLICY FAMILY, deliberately. Tier 1 is for a quantified statement
over a collection that a jq path cannot express ("no rule anywhere in this
group may be open to the world"). This scenario has no such fact: everything
it grades is a single value on a single resource, or a property of the
account. The one candidate considered and rejected was "every alias's
FunctionVersion must be an intrinsic rather than a literal", which cfn-guard
can express — but it does not separate this scenario's catch (BOTH awscdk
shapes emit an `Fn::GetAtt`), it would need a catch and three negative
fixtures invented to justify it, and it would score 0.0 the
account-inspecting answer `oracle.intent` above explicitly accepts. A tier
that cannot fail for a reason this scenario is about is decoration, and the
generated `tests/static_tiers.sh` says `SKIPPED_NO_ASSERTS` rather than
pretending otherwise.
