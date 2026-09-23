# oracles/rego/apigw-openapi/policy.rego -- HAND-AUTHORED (SCHEMA.md §8.2
# rule 7). Encodes specs/apigw-openapi.yaml's oracle.structural_asserts
# tier-"1" entries (route-count-correct, deployment-depends-on-all-methods,
# lambda-permission-per-function-tf) + oracle.rego_hints. Graded against
# `terraform show -json` plan JSON for both TF-shaped arms (hcl_raw and, if
# enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8. `input` at
# policy-evaluation time is that plan JSON document.
#
# Intent doc: oracles/apigw-openapi/intent.md

package cdktn_bench.apigw_openapi

import rego.v1

# --------------------------------------------------------------------------
# route-count-correct: exactly 3 API Gateway methods (one per route in the
# seeded OpenAPI spec). Graded against .planned_values -- HttpMethod/
# resource wiring is a plan-time-known, agent-authored literal, never a
# provider-computed value (SCHEMA.md §4.2's default case).
# --------------------------------------------------------------------------

methods := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_api_gateway_method"
]

deny contains msg if {
	count(methods) != 3
	msg := sprintf(
		"expected exactly 3 aws_api_gateway_method resources (one per route in the seeded OpenAPI spec), found %d",
		[count(methods)],
	)
}

# --------------------------------------------------------------------------
# deployment-depends-on-all-methods (THE PLANTED CATCH). Full per-resource
# SET identity, not a cardinality proxy (unlike the cfn-guard side of this
# same catch, which cannot do identity matching -- see
# specs/apigw-openapi.yaml's oracle.intent for the full write-up). Every
# aws_api_gateway_integration resource address must be covered by the
# deployment's dependency graph -- either the explicit `depends_on`
# meta-argument (a plain array of resource addresses under
# .configuration...resources[].depends_on, NOT under .expressions), a
# reference from the deployment's own `triggers` attribute (matched by
# prefix, since Terraform's reference list carries both "TYPE.NAME" and
# "TYPE.NAME.attr" forms for the same resource), OR (see CORRECTION below)
# a covered reference to the aws_api_gateway_method that integration is
# attached to.
#
# CORRECTION (2026-08-06, benchmark-integrity review finding
# "apigw-openapi / oracle-equivalence (deployment-depends-on-all-methods)"):
# this used to target ONLY aws_api_gateway_integration addresses, while
# oracle.intent's own words say "depends on every one of the three routes'
# METHODS" and the cfn-guard side of this same catch counts METHODS too
# (cfn-guard has no `AWS::ApiGateway::Integration`-vs-`::Method` distinction
# problem here since it only does cardinality -- see that file's own header
# comment). REFUTED directly: a deployment whose `depends_on` lists the
# three METHODS (`aws_api_gateway_method.m1/m2/m3`) -- literally what
# oracle.intent's own words describe -- was DENIED by the old rule (it only
# ever looked for integration addresses), scoring a correct, intent-literal
# hcl_raw solution 0.0. Fixed by ALSO treating an integration as covered
# when the METHOD it is attached to (identified via
# `aws_api_gateway_integration.<x>.expressions.http_method.references` --
# the idiomatic HCL pattern `http_method =
# aws_api_gateway_method.<x>.http_method` always emits this exact
# plan-time-known reference, verified directly against this scenario's own
# reference solution's plan output) is itself covered by depends_on/
# triggers. This is purely ADDITIVE (a strict superset of what the old rule
# accepted) -- it cannot newly PASS a solution the old rule correctly
# denied, only stop wrongly denying a solution that depends on methods
# instead of (or as well as) integrations.
# --------------------------------------------------------------------------

integrations := [r |
	some r in input.configuration.root_module.resources
	r.type == "aws_api_gateway_integration"
]

integration_addrs := {r.address | some r in integrations}

method_addrs := {addr |
	some r in input.configuration.root_module.resources
	r.type == "aws_api_gateway_method"
	addr := r.address
}

deployments := [r |
	some r in input.configuration.root_module.resources
	r.type == "aws_api_gateway_deployment"
]

# The aws_api_gateway_method address an integration is wired to, extracted
# from its `http_method` expression's references (idiomatic HCL:
# `http_method = aws_api_gateway_method.X.http_method`) -- undefined if the
# integration's http_method was written some other way (e.g. hardcoded on
# both resources independently), in which case this integration can only be
# covered directly, same as before this fix.
integration_method_addr(i) := addr if {
	refs := object.get(object.get(i, "expressions", {}), "http_method", {})
	ref_list := object.get(refs, "references", [])
	some ref in ref_list
	startswith(ref, "aws_api_gateway_method.")
	parts := split(ref, ".")
	addr := sprintf("%s.%s", [parts[0], parts[1]])
}

covered_by_depends_on(dep) := {addr | some addr in object.get(dep, "depends_on", [])}

covered_by_triggers(dep) := covered if {
	refs := object.get(object.get(dep, "expressions", {}), "triggers", {})
	ref_list := object.get(refs, "references", [])
	covered := {addr |
		some addr in (integration_addrs | method_addrs)
		some ref in ref_list
		startswith(ref, addr)
	}
} else := set()

# An integration is covered if ITS OWN address is covered directly, OR the
# method it is attached to is covered (see CORRECTION above).
integration_covered(i, covered) if {
	i.address in covered
}

integration_covered(i, covered) if {
	some addr in covered
	integration_method_addr(i) == addr
}

deny contains msg if {
	count(integration_addrs) > 0
	count(deployments) == 0
	msg := "an aws_api_gateway_rest_api / aws_api_gateway_integration exists but no aws_api_gateway_deployment was found in the plan"
}

deny contains msg if {
	count(integration_addrs) > 0
	some dep in deployments
	covered := covered_by_depends_on(dep) | covered_by_triggers(dep)
	missing := {i.address |
		some i in integrations
		not integration_covered(i, covered)
	}
	count(missing) > 0
	msg := sprintf(
		"%s does not depend on integration(s)/method(s) %v (neither via depends_on nor triggers, directly or via the integration's own method) -- the classic API Gateway deployment race",
		[dep.address, missing],
	)
}

# --------------------------------------------------------------------------
# REMOVED (2026-08-06, benchmark-integrity review finding "apigw-openapi /
# oracle-equivalence (per-function Lambda invoke permission)"): a
# `lambda-permission-per-function-tf` rule used to live here, denying a
# plan where some Lambda function wired via an AWS_PROXY integration had no
# matching `aws_lambda_permission` -- checked ONLY on the TF-shaped arms
# (hcl_raw, terraconstructs), because cfn-guard 3 cannot soundly express
# the identity-precise equivalent for awscdk (see
# oracles/cfn-guard/apigw-openapi/policy.guard's own header comment: a
# cardinality proxy here is hand-verified vacuous, since a correct
# LambdaIntegration's default `allowTestInvoke: true` emits TWO
# permissions per correctly-wired method). That asymmetry meant the
# TF-shaped arms were graded on a criterion awscdk was not -- REFUTED
# directly against a hand-built fixture (3 functions, 1 missing
# permission): denied here (reward 0.0) while the byte-equivalent CFN
# template passed cfn-guard's tier-0 existence-only check (reward 1.0).
# specs/apigw-openapi.yaml's oracle.structural_asserts now documents this
# as an intentional, prereg-compliant DROP (not a replacement) -- every
# arm is checked identically, at tier-0 existence-only, via the
# lambda-permission-exists structural_assert. See that spec's own removal
# note for the full rationale.
# --------------------------------------------------------------------------
