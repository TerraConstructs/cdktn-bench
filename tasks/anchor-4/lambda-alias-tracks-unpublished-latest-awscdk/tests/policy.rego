# GENERATOR-STUB — auto-scaffolded by oracles/emit.py, hand-author the
# real rules below and then DELETE this GENERATOR-STUB line. The generated
# tests/tiers.py::is_stub_policy() greps this exact file for the
# literal string "GENERATOR-STUB" to decide whether tier-1 should run for
# real or report SKIPPED_STUB — leaving this marker in place after you've
# added real rules would silently disable grading, and removing it from a
# still-unauthored file would make an empty policy start gating trials.
# emit_oracles() never overwrites this file once it exists (specs/SCHEMA.md
# §8.2 rule 7), so edits here are safe across regeneration.
#
# Scenario:      lambda-alias-tracks-unpublished-latest (specs/lambda-alias-tracks-unpublished-latest.yaml)
# Intent doc:    oracles/lambda-alias-tracks-unpublished-latest/intent.md
# Graded against the awscdk arm's synthesized CloudFormation template
# (cdk.out/ScenarioStack.template.json) — specs/SCHEMA.md §4.5/§8. `input`
# at policy-evaluation time is that TEMPLATE document, NOT the
# `terraform show -json` plan JSON that oracles/rego/<id>/policy.rego sees:
# resources live under `input.Resources[<LogicalId>]` with `.Type` and
# `.Properties`, and cross-resource references appear as `{"Ref": ...}` /
# `{"Fn::GetAtt": [...]}` objects naming a LOGICAL ID. That logical-id join
# is the whole reason this engine exists (ROADMAP.md M8): cfn-guard 3.2.0
# cannot express it, and approximating it with a count-equality proxy is
# unsound in both directions.
#
# Amendment 29 §4 is BINDING here: never key identity on a physical name
# (Properties.RoleName, BucketName, ...). Grade existence + type +
# properties, joined on LOGICAL ID.
#
# Tier-"1" structural_asserts this policy must encode (from the spec):
#   (none declared in this spec — this scenario has no tier-"1" asserts)
#
# cfn_guard_hints (free-form prose from the spec, not executable — guidance only;
# these are the CFN-shape hints, and they apply to this file whichever engine
# reads them):
#   (none declared)

package cdktn_bench.lambda_alias_tracks_unpublished_latest

import rego.v1

# TODO: replace this placeholder with `deny` rules that encode every
# tier-"1" assert and hint listed above, against the CloudFormation
# template shape. The generated tests/static_tiers.sh runs
# `opa eval -f raw -I -d policy.rego 'data.<package>.deny' < template.json`
# and fails tier-1 iff that set is non-empty — see oracles/rego-cfn/README.md.

default allow := false

# Placeholder: always non-compliant until hand-authored, so a forgotten
# scaffold can never silently pass a real trial.
allow if {
	false
}

# `not_verifiable` (optional, non-gating) is evaluated by the same generated
# static_tiers.sh block the TF arms use, so the rule name is available here
# too. It is normally left as this empty placeholder on the awscdk arm:
# CFN synth is fully static, so there is no plan-time-unknown gap of the kind
# specs/SCHEMA.md §4.2.1 describes. Leaving it empty writes no marker.
not_verifiable contains msg if {
	false
	msg := ""
}
