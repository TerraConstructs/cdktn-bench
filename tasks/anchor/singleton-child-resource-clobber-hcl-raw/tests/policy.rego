# oracles/rego/singleton-child-resource-clobber/policy.rego -- HAND-AUTHORED
# (SCHEMA.md §8.2 rule 7). Encodes specs/singleton-child-resource-clobber.yaml's
# one tier-"1" structural_assert (no-storage-rule-is-left-un-enabled) +
# oracle.rego_hints. Graded against `terraform show -json` plan JSON for BOTH
# TF-shaped arms (hcl_raw, terraconstructs) -- specs/SCHEMA.md §4.2/§8. `input`
# at policy-evaluation time is that plan JSON document.
#
# Intent doc: oracles/singleton-child-resource-clobber/intent.md
#
# WHY THIS FACT IS TIER 1 AND NOT TIER 0. The claim is universally quantified
# over a collection whose length the AGENT chooses: "NO rule in this document
# may be left un-enabled". `eq` cannot express it (it fails on any document
# with more than one rule, regardless of the values), and `set_eq: ["Enabled"]`
# runs `unique` before comparing, so it collapses N rules to their distinct
# statuses and says nothing about which rule carried which. The spec declares
# the `set_eq` form anyway, as §4.2 requires, so `make check-paths` resolves
# the node set this policy quantifies over -- but the policy is the thing that
# runs.
#
# READ FROM .planned_values, NOT .configuration (SCHEMA.md §4.2.1). `status` is
# an agent-authored literal on both TF arms -- on terraconstructs it is what
# `LifecycleConfigurationRule.enabled: boolean` is mapped to by
# `lib/aws/storage/bucket.js` -- so it is plan-time-KNOWN. Nothing in this
# scenario is laundered through `jsonencode(...)` or a
# `data "aws_iam_policy_document"` hop, so §4.2.1's contagious-unknown case and
# s3-bucket-hardening-decomposition's one-hop-indirection helper are both
# genuinely inapplicable here rather than merely omitted.
#
# FAILS CLOSED ON SHAPE DRIFT, deliberately: `object.get` at every level, no
# assumption that `rule` exists, and NO `count(...) > 0` guard that would let
# the rule pass vacuously on a document whose rules the provider spells
# somewhere this policy does not look. A rule object with NO `status` key at
# all is denied rather than skipped -- "absent" is not "Enabled", and treating
# it as a pass is exactly the vacuous-satisfaction shape this repo keeps
# finding. (The provider always emits `status` for a rule, because it is a
# required argument; the `<absent>` default exists so that if it ever stops
# doing so, this policy goes LOUD rather than quiet.)

package cdktn_bench.singleton_child_resource_clobber

import rego.v1

lifecycle_configurations := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_s3_bucket_lifecycle_configuration"
]

# --------------------------------------------------------------------------
# no-storage-rule-is-left-un-enabled
#
# The catch this falsifies (exports-rule-added-but-not-enabled): the new rule
# is authored with every value correct -- right prefix, right storage class,
# right day count -- and left switched off. Every value-level tier-0 assert in
# this scenario passes on that artifact, because every value really is
# correct; nothing ever transitions, and nothing errors.
# --------------------------------------------------------------------------

deny contains msg if {
	some cfg in lifecycle_configurations
	some rule in object.get(object.get(cfg, "values", {}), "rule", [])
	status := object.get(rule, "status", "<absent>")
	status != "Enabled"
	msg := sprintf(
		"%s declares a storage rule (id %q) with status %q -- every rule in this bucket's storage-rule document must be \"Enabled\", or the behaviour it describes never happens",
		[
			object.get(cfg, "address", "aws_s3_bucket_lifecycle_configuration.?"),
			object.get(rule, "id", "<unnamed>"),
			status,
		],
	)
}
