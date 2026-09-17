# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Intent doc: oracles/apigwv2-route-settings-zero-vs-unset/intent.md
# TF half:    ../../rego/apigwv2-route-settings-zero-vs-unset/policy.rego
# `input` is the awscdk arm's synthesized CloudFormation template, not the
# plan JSON the TF half sees (specs/SCHEMA.md §4.5); the generated
# tests/static_tiers.sh evaluates this package's `deny` against that
# template and fails tier 1 on a non-empty set.
#
# REGO AND NOT CFN-GUARD (`oracle.awscdk_tier1_engine: rego`): both facts
# are joins cfn-guard 3.2.0 has no operator for -- a settings block to its
# stage's StageName (one source location being a map keyed by a route key
# containing a space), and a two-hop logical-id walk Route.Target ->
# Integration -> Lambda function.
#
# Two shape differences from the TF half, tracked here at equal strictness:
# per-route settings are a MAP keyed by route key, not a list of
# route_key-carrying objects; a cross-resource reference is a
# `Ref`/`Fn::GetAtt` intrinsic naming a LOGICAL ID, not a reference string.

package cdktn_bench.apigwv2_route_settings_zero_vs_unset

import rego.v1

resources := object.get(input, "Resources", {})

prod_stages[id] := r if {
	some id, r in resources
	r.Type == "AWS::ApiGatewayV2::Stage"
	object.get(r, ["Properties", "StageName"], null) == "prod"
}

# --- prod-stage-governs-get-orders-throttling ---------------------------

_route_entries(stage) := [entry |
	some key, entry in object.get(stage, ["Properties", "RouteSettings"], {})
	key == "GET /orders"
]

_default_entries(stage) := [settings |
	settings := object.get(stage, ["Properties", "DefaultRouteSettings"], null)
	is_object(settings)
]

# What the SERVICE applies to GET /orders: its route-keyed entry where one
# exists, else the stage default -- so a stage default of 100/200 cannot
# launder a GET /orders entry of 0/0.
effective_settings(stage) := _route_entries(stage) if count(_route_entries(stage)) > 0

effective_settings(stage) := _default_entries(stage) if count(_route_entries(stage)) == 0

deny contains msg if {
	count(prod_stages) == 0
	msg := "no AWS::ApiGatewayV2::Stage with StageName \"prod\" exists in the template: the API is published on a stage called prod"
}

deny contains msg if {
	some id, stage in prod_stages
	count(effective_settings(stage)) == 0
	msg := sprintf(
		"%s carries no settings governing \"GET /orders\": neither DefaultRouteSettings nor a RouteSettings entry for that route key",
		[id],
	)
}

deny contains msg if {
	some id, stage in prod_stages
	some settings in effective_settings(stage)
	object.get(settings, "ThrottlingRateLimit", null) != 100
	msg := sprintf(
		"%s: the settings governing \"GET /orders\" state ThrottlingRateLimit=%v, not the 100 requests per second asked for",
		[id, object.get(settings, "ThrottlingRateLimit", null)],
	)
}

# An absent key is a violation here, not "not stated, so not checked": the
# service applies an unconfigured burst limit as 0, which rejects every
# request (tfp-aws#30373).
deny contains msg if {
	some id, stage in prod_stages
	some settings in effective_settings(stage)
	object.get(settings, "ThrottlingBurstLimit", null) != 200
	msg := sprintf(
		"%s: the settings governing \"GET /orders\" state ThrottlingBurstLimit=%v, not the 200-request burst asked for (an omitted or zero burst limit is applied as 0 -- every request 429s)",
		[id, object.get(settings, "ThrottlingBurstLimit", null)],
	)
}

# --- route-reaches-a-function-in-this-plan ------------------------------

# Every logical id an intrinsic anywhere inside `value` names. `walk` finds
# them at any depth, which is what makes this independent of whether the
# template spells the reference as a bare `Ref`, an `Fn::GetAtt`, or either
# one nested inside an `Fn::Join`.
referenced_ids(value) := {id |
	walk(value, [_, node])
	is_object(node)
	id := _intrinsic_target(node)
}

_intrinsic_target(node) := node.Ref if is_string(node.Ref)

_intrinsic_target(node) := node["Fn::GetAtt"][0] if is_array(node["Fn::GetAtt"])

get_orders_routes[id] := r if {
	some id, r in resources
	r.Type == "AWS::ApiGatewayV2::Route"
	object.get(r, ["Properties", "RouteKey"], null) == "GET /orders"
}

_target_integrations(route) := {id |
	some id in referenced_ids(object.get(route, ["Properties", "Target"], null))
	object.get(resources, [id, "Type"], null) == "AWS::ApiGatewayV2::Integration"
}

_uri_functions(integration) := {id |
	some id in referenced_ids(object.get(integration, ["Properties", "IntegrationUri"], null))
	object.get(resources, [id, "Type"], null) == "AWS::Lambda::Function"
}

deny contains msg if {
	count(get_orders_routes) == 0
	msg := "no AWS::ApiGatewayV2::Route with RouteKey \"GET /orders\" exists in the template"
}

deny contains msg if {
	some id, route in get_orders_routes
	count(_target_integrations(route)) == 0
	msg := sprintf(
		"%s targets no AWS::ApiGatewayV2::Integration in this template: its Target names a literal, so the route reaches nothing here",
		[id],
	)
}

deny contains msg if {
	some rid, route in get_orders_routes
	some iid in _target_integrations(route)
	count(_uri_functions(resources[iid])) == 0
	msg := sprintf(
		"%s -> %s: IntegrationUri names no AWS::Lambda::Function in this template (an imported or hand-typed function ARN reaches a function nothing here creates)",
		[rid, iid],
	)
}
