# oracles/rego/named-resource-replacement/policy.rego -- HAND-AUTHORED
# (SCHEMA.md §8.2 rule 7). Encodes specs/named-resource-replacement.yaml's one
# tier-"1" structural_assert (security-group-ingress-stays-scoped-to-the-vpc) +
# oracle.rego_hints. Graded against `terraform show -json` plan JSON for both
# TF-shaped arms (hcl_raw, terraconstructs) -- specs/SCHEMA.md §4.2/§8. `input`
# at policy-evaluation time is that plan JSON document.
#
# Intent doc: oracles/named-resource-replacement/intent.md
#
# WHY THIS FACT IS TIER 1 AND NOT TIER 0. The claim is universally quantified
# over a collection: "NO ingress rule on ANY security group may allow
# 0.0.0.0/0". A jq path can pin one value or assert one shape is absent at one
# location; it cannot soundly express "and nothing else, anywhere in this list"
# without the op table growing a quantifier. The tier-0 assert with the same
# name is the `not_regex` approximation of it, and both are declared on purpose:
# the two are checked against the same artifact by two independent evaluators,
# which is the differential this repo's oracle-equivalence discipline wants.
#
# WHY EGRESS IS OUT OF SCOPE, deliberately: the seed allows all outbound, both
# because that is the L2 default on two of three arms (`allowAllOutbound: true`)
# and because it is ordinary practice for an endpoint-facing group. Denying it
# would make the SEED itself violate this policy, which would make the
# `ingress-widened-to-the-internet` catch unfalsifiable -- its negative fixture
# and its own starting state would be indistinguishable. The seed_assert
# `seed-ingress-is-already-scoped-to-the-vpc` pins that boundary from the other
# side.

package cdktn_bench.named_resource_replacement

import rego.v1

# --------------------------------------------------------------------------
# security-group-ingress-stays-scoped-to-the-vpc
#
# Read from .planned_values (not .configuration): ingress cidr_blocks are
# agent-authored literals, plan-time-KNOWN even for a resource being replaced,
# so this is SCHEMA.md §4.2's default case and not a plan-time-unknown one.
#
# Written so it fails CLOSED on shape drift: `object.get` everywhere, no
# assumption that `ingress` exists at all, and no `count(...) > 0` guard that
# would make the rule vacuously pass on an empty/missing collection.
# --------------------------------------------------------------------------

security_groups := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_security_group"
]

open_ingress_cidrs(sg) := {cidr |
	some rule in object.get(object.get(sg, "values", {}), "ingress", [])
	some cidr in object.get(rule, "cidr_blocks", [])
	cidr == "0.0.0.0/0"
}

open_ingress_ipv6(sg) := {cidr |
	some rule in object.get(object.get(sg, "values", {}), "ingress", [])
	some cidr in object.get(rule, "ipv6_cidr_blocks", [])
	cidr == "::/0"
}

deny contains msg if {
	some sg in security_groups
	count(open_ingress_cidrs(sg)) > 0
	msg := sprintf(
		"%s has an ingress rule open to 0.0.0.0/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[object.get(sg, "address", "aws_security_group.?")],
	)
}

# The IPv6 twin of the same fact. Present because "scoped to the VPC" is the
# claim, not "no IPv4 wildcard" -- a solution that scoped IPv4 correctly and
# opened ::/0 would otherwise pass a rule whose own message says the group is
# not reachable from anywhere else.
deny contains msg if {
	some sg in security_groups
	count(open_ingress_ipv6(sg)) > 0
	msg := sprintf(
		"%s has an ingress rule open to ::/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[object.get(sg, "address", "aws_security_group.?")],
	)
}

# --------------------------------------------------------------------------
# not_verifiable (SCHEMA.md §4.2.1): informational, never denies, never affects
# reward. A solution that expresses ingress via a SEPARATE
# `aws_security_group_rule` / `aws_vpc_security_group_ingress_rule` resource
# rather than an inline `ingress` block is legal Terraform and equally correct,
# but its cidr lives on a different resource type -- checked here too, so this
# is NOT a hole; the marker exists for the one shape that genuinely cannot be
# read from plan JSON: a cidr supplied by a plan-time-unknown expression (e.g.
# `cidr_blocks = [aws_vpc.x.cidr_block]` on a VPC created in the same plan).
# --------------------------------------------------------------------------

standalone_rules := [r |
	some r in input.planned_values.root_module.resources
	r.type in {"aws_security_group_rule", "aws_vpc_security_group_ingress_rule"}
]

deny contains msg if {
	some r in standalone_rules
	object.get(object.get(r, "values", {}), "type", "ingress") == "ingress"
	some cidr in object.get(object.get(r, "values", {}), "cidr_blocks", [])
	cidr == "0.0.0.0/0"
	msg := sprintf(
		"%s opens ingress to 0.0.0.0/0",
		[object.get(r, "address", "aws_security_group_rule.?")],
	)
}

deny contains msg if {
	some r in standalone_rules
	object.get(object.get(r, "values", {}), "cidr_ipv4", "") == "0.0.0.0/0"
	msg := sprintf(
		"%s opens ingress to 0.0.0.0/0",
		[object.get(r, "address", "aws_vpc_security_group_ingress_rule.?")],
	)
}

not_verifiable contains msg if {
	some sg in security_groups
	some rule in object.get(object.get(sg, "values", {}), "ingress", [])
	object.get(rule, "cidr_blocks", null) == null
	object.get(rule, "security_groups", null) == null
	object.get(rule, "self", null) == null
	msg := sprintf(
		"%s has an ingress rule whose source is not readable from plan JSON (every source field resolved to null -- plan-time-unknown expression); its scope could not be checked",
		[object.get(sg, "address", "aws_security_group.?")],
	)
}
