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
#
# The stage join reads `planned_values` only, which the normaliser hoists out
# of every module, so it needs no module-aware path. The route->integration->
# function walk reads `configuration`, which is NOT hoisted: on the
# hcl_modules arm the API, route and integration are declared inside the
# apigateway-v2 module's own body and `configuration.root_module.resources`
# holds only what the agent wrote at the root. The walk below therefore unions
# every configuration scope and qualifies each body's addresses with its call
# path (oracles/rego/README.md, "How a policy addresses a module resource").
# On a module-free plan the prefix is empty and every rule is what it was.

package cdktn_bench.apigwv2_route_settings_zero_vs_unset

import rego.v1

planned := object.get(input, ["planned_values", "root_module", "resources"], [])

# --------------------------------------------------------------------------
# The configuration-side module walk
#
# `config_modules` is the root module node plus every module-call body, paired
# with the path that reached it. A module node path alternates "module_calls" /
# <call name> / "module", so its length is a multiple of 3 and every third
# segment is a literal -- that shape is the filter, because `walk` yields every
# sub-object in the document and only these are modules. For a plan with no
# module in it the set is exactly `[[], root_module]`.
# --------------------------------------------------------------------------

segment_ok(path, i) if {
	i % 3 == 0
	path[i] == "module_calls"
}

segment_ok(_, i) if i % 3 == 1

segment_ok(path, i) if {
	i % 3 == 2
	path[i] == "module"
}

is_module_node_path(path) if {
	count(path) % 3 == 0
	every i, _ in path {
		segment_ok(path, i)
	}
}

config_modules contains [path, node] if {
	walk(input.configuration.root_module, [path, node])
	is_module_node_path(path)
	is_object(node)
}

config_resources contains [path, resource] if {
	some [path, node] in config_modules
	some resource in node.resources
	is_object(resource)
}

# The address prefix a resource configured at module node path `path` carries in
# `planned_values` after hoisting: "" at the root, "module.<call>." per level.
# A module call with count/for_each plans as `module.<call>[k].…`, which no
# prefix built from the configuration can name; such a resource simply fails to
# match below and the rule denies it, which is the fail-closed direction.
module_prefix(path) := concat("", [sprintf("module.%s.", [name]) |
	some i, name in path
	i % 3 == 1
])

# The `module_calls.<call>` node that instantiated module node path `path`: the
# same path with its trailing "module" segment dropped.
calling_node(path) := object.get(input.configuration.root_module, array.slice(path, 0, count(path) - 1), {})

references(resource, attribute) := object.get(object.get(resource, "expressions", {}), attribute, {}).references

# Every configured resource keyed by the absolute address its planned instances
# carry. The two sides then share one address domain.
config_by_address[address] := {"path": path, "resource": resource} if {
	some [path, resource] in config_resources
	address := concat("", [module_prefix(path), resource.address])
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
# rejects every request (tfp-aws#30373). A module that fills the omission from
# its own default states a number that is not 200 and is denied just the same.
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

# The planned address with its trailing instance key removed, which is the
# address the configuration declares. A for_each'd module body resource plans
# as `module.<call>.<type>.<name>["key"]`; only the LAST bracketed segment is
# the resource's own key, so an anchored pattern is what strips it.
_config_address(address) := regex.replace(address, `\[[^\[\]]*\]$`, "")

# Anchored on `planned_values`, not on the configuration: inside a module body
# the route key is `each.key`, and only the planned instance carries the literal
# the ticket names. At the root the planned address is the config address, so
# hcl_raw and awscdk-shaped plans resolve exactly as before.
get_orders_route_addresses := {addr |
	some r in planned
	r.type == "aws_apigatewayv2_route"
	object.get(r, ["values", "route_key"], null) == "GET /orders"
	addr := _config_address(r.address)
}

get_orders_routes[addr] := config_by_address[addr] if {
	some addr in get_orders_route_addresses
	config_by_address[addr]
}

# A reference to a resource declared in the same module body is relative to
# that body; anything else (a `module.<call>.…` output, a `var.`/`each.`/
# `local.` symbol) is already absolute or is not an address at all.
_absolute(prefix, ref) := concat("", [prefix, ref]) if startswith(ref, "aws_")

_absolute(prefix, ref) := ref if not startswith(ref, "aws_")

_target_integrations(entry) := {addr |
	some ref in references(entry.resource, "target")
	startswith(ref, "aws_apigatewayv2_integration.")
	addr := concat("", [module_prefix(entry.path), _bare_address(ref)])
}

# The module inputs that decide an `integration_uri` written as a passthrough:
# `var.<name>` names one directly, and `each.value.<field>` names whichever
# input the resource's own `for_each` iterates. Both are resolved ONE scope up,
# against the argument the caller passed for that input -- the only hop taken.
# An argument that is itself a `var.…` (a module forwarding its caller's input)
# stays unresolved and the rule denies, which is the fail-closed direction.
_hop_input_names(entry) := {name |
	some ref in references(entry.resource, "integration_uri")
	startswith(ref, "var.")
	name := split(trim_prefix(ref, "var."), ".")[0]
} | {name |
	some ref in references(entry.resource, "integration_uri")
	startswith(ref, "each.")
	some fe in object.get(entry.resource, ["for_each_expression", "references"], [])
	startswith(fe, "var.")
	name := split(trim_prefix(fe, "var."), ".")[0]
}

integration_uri_refs(entry) := {ref |
	some raw in references(entry.resource, "integration_uri")
	ref := _absolute(module_prefix(entry.path), raw)
} | {qualified |
	some name in _hop_input_names(entry)
	some arg in references(calling_node(entry.path), name)
	qualified := _absolute(module_prefix(array.slice(entry.path, 0, count(entry.path) - 3)), arg)
}

created_function_addresses := {r.address |
	some r in planned
	r.type == "aws_lambda_function"
}

# A function created INSIDE a module call is named by the caller through that
# call's output (`module.<call>.lambda_function_arn`), never by the function's
# own hoisted address, so every created function's call prefix is a valid
# reference prefix too. With no module-created function the set is empty and
# this second definition never holds: hcl_raw strictness is unchanged.
created_function_call_prefixes := {prefix |
	some addr in created_function_addresses
	startswith(addr, "module.")
	prefix := concat("", ["module.", split(trim_prefix(addr, "module."), ".")[0], "."])
}

references_a_created_function(refs) if {
	some ref in refs
	some addr in created_function_addresses
	startswith(ref, addr)
}

references_a_created_function(refs) if {
	some ref in refs
	some prefix in created_function_call_prefixes
	startswith(ref, prefix)
}

deny contains msg if {
	count(get_orders_route_addresses) == 0
	msg := "no aws_apigatewayv2_route with route_key \"GET /orders\" exists in the plan"
}

deny contains msg if {
	some addr in get_orders_route_addresses
	not config_by_address[addr]
	msg := sprintf("the planned route %s has no configuration this document can read", [addr])
}

deny contains msg if {
	some addr, entry in get_orders_routes
	count(_target_integrations(entry)) == 0
	msg := sprintf(
		"%s targets no aws_apigatewayv2_integration this configuration declares: its `target` names a literal, so the route reaches nothing here",
		[addr],
	)
}

deny contains msg if {
	some addr, entry in get_orders_routes
	some target in _target_integrations(entry)
	not config_by_address[target]
	msg := sprintf("%s targets %s, which this configuration does not declare", [addr, target])
}

deny contains msg if {
	some addr, entry in get_orders_routes
	some target in _target_integrations(entry)
	integration := config_by_address[target]
	not references_a_created_function(integration_uri_refs(integration))
	msg := sprintf(
		"%s: integration_uri references no aws_lambda_function this configuration creates (a hand-typed function ARN reaches a function nothing here declares)",
		[target],
	)
}
