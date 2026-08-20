# Oracle intent: Rename an explicitly-named, in-use security group and roll it out

`named-resource-replacement` — generated verbatim from `specs/named-resource-replacement.yaml`'s `oracle.intent` (`specs/SCHEMA.md` §4.1). This is the single natural-language source of truth that both `../rego/named-resource-replacement/policy.rego` and `../cfn-guard/named-resource-replacement/policy.guard` must encode at the same strictness — the oracle-equivalence CI (Slice E) uses this file as the human-reviewable reference when checking that.

**Do not hand-edit this file.** It is regenerated from the spec on every `emit_oracles` call; edit `oracle.intent` in `specs/named-resource-replacement.yaml` instead.

---

A correct solution leaves this workspace deploying the same system it
described before, with exactly one thing changed: the security group's name
is now `platform-internal-services-ssm-endpoint`.

Three things are graded, in three different places, and the split is
deliberate:

1. TIER 0 (static, every arm). The group carries the new name; the interface
   endpoint still exists and is still wired to that group. This is what
   makes the DO-NOTHING answer fail: the seed already deploys green, so
   without a name assert an agent that changes nothing would score 1.0. See
   `solution/broken/seed-unchanged/`, which exists precisely to keep proving
   that.

2. TIER 1 (Rego / cfn-guard, every arm). The group's 443 ingress stays
   scoped to the VPC CIDR — no 0.0.0.0/0. A policy-family fact rather than a
   tier-0 assert because "no rule anywhere in this group may be open to the
   world" is a quantified statement over a collection, which is what the
   policy engines are for; a jq path can pin one value, not the absence of a
   shape across all of them.

3. LIVE (`tests/live_check.py`, gating) and IDEMPOTENCE (gating). Whether
   the rename ACTUALLY LANDED. On the TF arms the naive edit plans and
   synthesizes perfectly and then fails at apply, leaving the account with
   the old group still attached and the configuration naming a new one. No
   static tier can see that — `terraform show -json` does not emit
   `lifecycle`, verified directly — so the live check reads the deployed
   group's real name from EC2, and the idempotence tier then requires the
   agent's own toolchain to report a converged state against what it
   deployed. A half-applied rename fails both.

What is deliberately NOT graded: how many resources each arm's expansion
produced, and whether the group is expressed as an L2 or as raw HCL. The
arms are compared on the declared behavioural facts only.
