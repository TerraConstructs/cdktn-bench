# GENERATOR-STUB — auto-scaffolded by oracles/emit.py, hand-author the
# real rules below and then DELETE this GENERATOR-STUB line. The generated
# tests/_assert_lib.sh::is_stub_policy() greps this exact file for the
# literal string "GENERATOR-STUB" to decide whether tier-1 should run for
# real or report SKIPPED_STUB — leaving this marker in place after you've
# added real rules would silently disable grading, and removing it from a
# still-unauthored file would make an empty policy start gating trials.
# emit_oracles() never overwrites this file once it exists (specs/SCHEMA.md
# §8.2 rule 7), so edits here are safe across regeneration.
#
# Scenario:      lambda-alias-tracks-unpublished-latest (specs/lambda-alias-tracks-unpublished-latest.yaml)
# Intent doc:    oracles/lambda-alias-tracks-unpublished-latest/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) — specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document.
#
# Tier-"1" structural_asserts this policy must encode (from the spec):
#   (none declared in this spec — this scenario has no tier-"1" asserts)
#
# rego_hints (free-form prose from the spec, not executable — guidance only):
#   (none declared)

package cdktn_bench.lambda_alias_tracks_unpublished_latest

import rego.v1

# TODO(Slice D): replace this placeholder with `deny`/`allow` rules that
# encode every tier-"1" assert and hint listed above. A generated
# static_tiers.sh runs `opa eval -d policy.rego -i plan.json
# 'data.<package>.deny'` (or equivalent) and fails the tier iff that set is
# non-empty — see oracles/rego/README.md.

default allow := false

# Placeholder: always non-compliant until hand-authored, so a forgotten
# scaffold can never silently pass a real trial.
allow if {
	false
}

# TODO(Slice D, optional): if any tier-"1" assert above targets a
# plan-time-unknown attribute (specs/SCHEMA.md §4.2.1 -- an IAM policy or
# similar value-content check whose encoded value can go `(known after
# apply)` when a correct solution references another resource's
# provider-computed output), replace this placeholder with a real
# `not_verifiable` set alongside `deny`/`allow`: fires exactly when the
# graph-edge check already passed but the value-content check cannot be
# evaluated from plan JSON alone. A generated tests/static_tiers.sh
# (generator/gen.py::build_static_tiers_sh) evaluates
# `data.<package>.not_verifiable` after `deny` and, when non-empty, tees
# it to /logs/verifier/tier1-not-verifiable -- non-gating, never affects
# tier1_status/reward, purely a "this could not be checked" record (see
# SCHEMA.md §4.2.1's option-3 bullet and
# oracles/rego/toy-ssm-parameter/policy.rego's own not_verifiable rule for
# the worked example). Leave this empty placeholder in place (it always
# evaluates to an empty set, so no marker is ever written) for a scenario
# with no such gap.
not_verifiable contains msg if {
	false
	msg := ""
}
