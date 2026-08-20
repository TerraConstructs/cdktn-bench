# oracles/rego/apigw-redeploy/policy.rego -- HAND-AUTHORED (SCHEMA.md §8.2
# rule 7). Encodes specs/apigw-redeploy.yaml's oracle.structural_asserts
# tier-"1" entry (deployment-depends-on-all-methods) + oracle.rego_hints.
# Graded against `terraform show -json` plan JSON for both TF-shaped arms
# (hcl_raw and, if enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document.
#
# Adapted directly from oracles/rego/apigw-openapi/policy.rego's own
# deployment-depends-on-all-methods rule (same catch family, same identity-
# precise depends_on/triggers-reference coverage check, same CORRECTION
# for "covered via the method the integration is attached to" -- see that
# file's own header comment for the full history/rationale, unchanged
# here). route-count-correct is NOT reused here: apigw-redeploy does not
# declare that catch (its own tier-1 coverage floor is met by this one
# rule alone -- generator/check_tier1_coverage.py).
#
# Intent doc: oracles/apigw-redeploy/intent.md

package cdktn_bench.apigw_redeploy

import rego.v1

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
# `http_method = aws_api_gateway_method.X.http_method`).
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
