# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Intent doc: oracles/apigwv2-route-settings-zero-vs-unset/intent.md
# CFN half:   ../../rego-cfn/apigwv2-route-settings-zero-vs-unset/policy.rego
# `input` is `terraform show -json` PLAN output; the generated
# tests/static_tiers.sh evaluates this package's `deny` against it and fails
# tier 1 on a non-empty set.
#
# Two joins live here, one per tier-1 assert. Values alone cannot state
# either: the throttling numbers are correct in the artifact of a solution
# that hangs them off the wrong stage, and a hand-typed function ARN is a
# syntactically valid Lambda ARN. Both rules FAIL CLOSED -- an empty
# collection denies rather than passing vacuously.

package cdktn_bench.apigwv2_route_settings_zero_vs_unset

import rego.v1

planned := object.get(input, ["planned_values", "root_module", "resources"], [])

configured := object.get(input, ["configuration", "root_module", "resources"], [])

configured_by_address[addr] := r if {
	some r in configured
	addr := r.address
}

prod_stages := [r |
	some r in planned
	r.type == "aws_apigatewayv2_stage"
	object.get(r, ["values", "name"], null) == "prod"
]

# --- prod-stage-governs-get-orders-throttling ---------------------------

# `route_settings` is a LIST of objects each carrying its own `route_key` in
# plan JSON, where CloudFormation uses a map keyed by the route key.
_route_entries(stage) := [x |
	some x in object.get(stage, ["values", "route_settings"], [])
	object.get(x, "route_key", null) == "GET /orders"
]

# What the SERVICE applies to GET /orders: its route-keyed entry where one
# exists, else the stage default. A stage whose default says 100/200 and
# whose GET /orders entry says 0/0 throttles the route to nothing, so the
# default must not be read as a fallback once the entry exists.
effective_settings(stage) := _route_entries(stage) if count(_route_entries(stage)) > 0

effective_settings(stage) := object.get(stage, ["values", "default_route_settings"], []) if {
	count(_route_entries(stage)) == 0
}

deny contains msg if {
	count(prod_stages) == 0
	msg := "no aws_apigatewayv2_stage named \"prod\" exists in the plan: the API is published on a stage called prod"
}

deny contains msg if {
	some stage in prod_stages
	count(effective_settings(stage)) == 0
	msg := sprintf(
		"%s carries no settings governing \"GET /orders\": neither default_route_settings nor a route_settings entry for that route key",
		[stage.address],
	)
}

deny contains msg if {
	some stage in prod_stages
	some settings in effective_settings(stage)
	object.get(settings, "throttling_rate_limit", null) != 100
	msg := sprintf(
		"%s: the settings governing \"GET /orders\" state throttling_rate_limit=%v, not the 100 requests per second asked for",
		[stage.address, object.get(settings, "throttling_rate_limit", null)],
	)
}

# A missing key and a JSON `null` are violations here, not "not stated, so
# not checked": an omitted burst limit is applied by the service as 0, which
# rejects every request (tfp-aws#30373).
deny contains msg if {
	some stage in prod_stages
	some settings in effective_settings(stage)
	object.get(settings, "throttling_burst_limit", null) != 200
	msg := sprintf(
		"%s: the settings governing \"GET /orders\" state throttling_burst_limit=%v, not the 200-request burst asked for (an omitted or zero burst limit is applied as 0 -- every request 429s)",
		[stage.address, object.get(settings, "throttling_burst_limit", null)],
	)
}

# --- route-reaches-a-function-in-this-plan ------------------------------

# A reference appears as both `TYPE.NAME` and `TYPE.NAME.attr`; the bare
# two-segment address is what a resource is addressed by.
_bare_address(ref) := concat(".", array.slice(split(ref, "."), 0, 2))

get_orders_routes := [r |
	some r in configured
	r.type == "aws_apigatewayv2_route"
	object.get(r, ["expressions", "route_key", "constant_value"], null) == "GET /orders"
]

_target_integrations(route) := {addr |
	some ref in object.get(route, ["expressions", "target", "references"], [])
	startswith(ref, "aws_apigatewayv2_integration.")
	addr := _bare_address(ref)
}

_lambda_references(integration) := [ref |
	some ref in object.get(integration, ["expressions", "integration_uri", "references"], [])
	startswith(ref, "aws_lambda_function.")
]

deny contains msg if {
	count(get_orders_routes) == 0
	msg := "no aws_apigatewayv2_route with route_key \"GET /orders\" exists in the configuration"
}

deny contains msg if {
	some route in get_orders_routes
	count(_target_integrations(route)) == 0
	msg := sprintf(
		"%s targets no aws_apigatewayv2_integration this configuration declares: its `target` names a literal, so the route reaches nothing here",
		[route.address],
	)
}

deny contains msg if {
	some route in get_orders_routes
	some addr in _target_integrations(route)
	not configured_by_address[addr]
	msg := sprintf("%s targets %s, which this configuration does not declare", [route.address, addr])
}

deny contains msg if {
	some route in get_orders_routes
	some addr in _target_integrations(route)
	integration := configured_by_address[addr]
	count(_lambda_references(integration)) == 0
	msg := sprintf(
		"%s: integration_uri references no aws_lambda_function this configuration creates (a hand-typed function ARN reaches a function nothing here declares)",
		[addr],
	)
}
