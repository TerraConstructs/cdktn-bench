# Oracle intent: IAM E2E role derivation: author deployer + workload permissions against real AWS denials

`iam-e2e-role` — generated verbatim from `specs/iam-e2e-role.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/iam-e2e-role/policy.rego` and `../cfn-guard/iam-e2e-role/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/iam-e2e-role.yaml` instead.

---

Exactly two IAM roles exist in the FINAL delivered artifact: one named
`iam-e2e-role-deployer` and one named `iam-e2e-role-workload`, both under
IAM path `/cdktn-bench-task/`. Neither role's trust policy trusts a
wildcard principal; both trust this account's root principal gated by an
`sts:ExternalId` condition (the deployer additionally may trust nothing
else; the workload additionally trusts `ec2.amazonaws.com`). Neither
role's permissions policy grants a bare `Action: "*"` or a full-service
wildcard action (`service:*`); every granted action is a real IAM action
for one of this task's services (ec2, iam, kms, s3, ssm, sts
-- see the pinned action catalogue in this scenario's tier-0 check for the
exact allowed set); no granted S3 `Resource` pattern is broad enough to
match `cdktn-bench-iam-e2e-tfstate-<account>-us-east-1` (a pre-provisioned
bucket this task's own module never creates or references).

This oracle grades the FINAL delivered policy documents' STATIC shape
only -- the two properties above (no admin wildcards, no invalid actions,
no wildcard-trust, no over-broad bucket scope) are exactly and only what a
synth/plan artifact can express. Whether the two roles actually WORK --
whether a real `terraform apply`+`destroy` of module/ succeeds under the
deployer role, and whether the workload role can actually read what a
real workload needs -- is a runtime fact no static artifact can express;
it is checked instead by harness/validate.sh (via this scenario's
hand-authored live check, SCHEMA.md §5 verifier.live_check), which is
GATING for this scenario (three of this scenario's catches are
predicted_tier_caught: "live" by construction -- see missing-kms-for-securestring,
getparametersbypath-not-granted, and missing-tag-on-create above; a
non-gating live check would mean none of those three could ever cost a
real trial any reward).

Known, deliberate scope decision (see specs/iam-e2e-role.yaml's own
DECISIONS.md amendment for the full reasoning): a policy that passes every
static tier here is NOT thereby proven correct -- the static tiers prove
"not obviously over-permissioned"; only the live check proves "actually
works with exactly what was granted." Neither property alone is
sufficient; both are required, deliberately, so that a wildcard-admin
policy (defeats the live check's own purpose by trivially passing it,
were it the only gate) is still rejected by the static tiers, and a
narrowly-scoped-but-incomplete policy (passes every static tier) is still
rejected by the live check.
