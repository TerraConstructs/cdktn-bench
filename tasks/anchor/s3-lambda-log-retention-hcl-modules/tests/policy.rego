# Hand-authored -- NOT a generator stub; emit_oracles() never overwrites it
# (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-lambda-log-retention (specs/s3-lambda-log-retention.yaml)
# Intent doc: oracles/s3-lambda-log-retention/intent.md
# Graded against `terraform show -json` plan JSON for every TF-shaped arm.
# Encodes the lambda-permission-scoped-to-bucket-tf assert: the Lambda
# permission's source_arn must REFERENCE the bucket this scenario creates.
#
# Read the graph edge from `.configuration`, never the value: `source_arn` is
# absent from `.planned_values` whenever it names another resource's
# provider-computed `.arn` (SCHEMA.md §4.2.1), so a value check would be
# unfalsifiable in both directions.
#
# Read `principal` from `.planned_values`, never
# `.expressions.principal.constant_value`: that slot is populated only for a
# literal written in the resource block, so a principal indirected through a
# `local`/`var`/`for_each` selected nothing and the fail-closed rule below
# denied a correct solution.
#
# On hcl_modules both facts sit one scope away from a root-level plan, forced
# by the module bodies: `s3-bucket//modules/notification` scopes its permission
# from a `local` (main.tf:73), which plan JSON cannot represent, and `lambda`'s
# `allowed_triggers` permissions are `for_each`-expanded (main.tf:336,359),
# which the configuration representation does not expand. `resolved_refs` reads
# both from the module call's own arguments; at the root it is the identity.

package cdktn_bench.s3_lambda_log_retention

import rego.v1

# --------------------------------------------------------------------------
# The configuration-side module walk (oracles/rego/README.md, "How a policy
# addresses a module resource")
#
# The normalised plan hoists every module resource into
# `planned_values.root_module.resources`, so the VALUES side needs no
# module-aware path. The CONFIGURATION side is not hoisted: a module's own
# resource blocks stay under `configuration.root_module.module_calls.<call>.
# module.resources`, and the graph-edge fact below is read from there
# (SCHEMA.md §4.2.1 -- a source_arn VALUE is plan-time-unknown for a correct
# solution). A rule reading `configuration.root_module.resources` alone sees
# nothing at all on the hcl_modules arm and grades an empty set.
#
# `config_modules` is the root module node plus every module-call body, paired
# with the path that reached it. A module node path alternates
# "module_calls" / <call name> / "module", so its length is a multiple of 3 and
# every third segment is a literal -- that shape is the filter, because `walk`
# yields every sub-object in the document. For a plan with no module in it the
# set is exactly `[[], root_module]` and every rule below reduces to what it
# was before this walk existed.
# --------------------------------------------------------------------------

segment_ok(p, i) if {
	i % 3 == 0
	p[i] == "module_calls"
}

segment_ok(p, i) if i % 3 == 1

segment_ok(p, i) if {
	i % 3 == 2
	p[i] == "module"
}

is_module_node_path(p) if {
	count(p) % 3 == 0
	every i, _ in p {
		segment_ok(p, i)
	}
}

config_modules contains [p, m] if {
	walk(input.configuration.root_module, [p, m])
	is_module_node_path(p)
	is_object(m)
}

config_resources contains [p, r] if {
	some [p, m] in config_modules
	some r in m.resources
	is_object(r)
}

# The address prefix a resource configured at module node path `p` carries in
# `planned_values` after hoisting: "" at the root, "module.<call>." per level.
# Instance keys are NOT reconstructed: a module call with count/for_each plans
# as `module.<call>[k].…`, which no prefix built from the configuration can
# name; such a resource fails to match its planned twin and is not selected,
# which is the fail-closed direction.
module_prefix(p) := concat("", [sprintf("module.%s.", [n]) |
	some i, n in p
	i % 3 == 1
])

# The `module_calls.<call>` node that instantiated module node path `p`: the
# same path with its trailing "module" segment dropped.
calling_node(p) := object.get(input.configuration.root_module, array.slice(p, 0, count(p) - 1), {})

# The prefix the CALLER of module node path `p` carries.
parent_prefix(p) := module_prefix(array.slice(p, 0, count(p) - 3))

references(r, attribute) := object.get(object.get(r, "expressions", {}), attribute, {}).references

# Every reference in every argument of a module call, in one set. This is the
# only resolution available for the two things a module body cannot express
# (oracles/rego/README.md): a `local`, which plan JSON has no representation of
# at all, and an `each.value` on a resource whose `for_each` collection the
# document does not expand. It resolves the fact to the CALL rather than to one
# of its arguments, so a reference sitting in a different argument of the same
# call also satisfies it -- the bounded strictness loss of reading one scope up.
call_references(p) := {ref |
	some _, expression in object.get(calling_node(p), "expressions", {})
	some ref in object.get(expression, "references", [])
}

# The module inputs a `for_each`-expanded resource iterates: `each.value.x`
# names one element of that collection, so the argument the caller passed for
# it is what decides the fact.
for_each_inputs(r) := {name |
	some ref in object.get(object.get(r, "for_each_expression", {}), "references", [])
	startswith(ref, "var.")
	name := split(trim_prefix(ref, "var."), ".")[0]
}

# `attribute`'s references spelled in the caller's address domain.
#
# At the root (`module_prefix` empty, no `var.`/`each.`/`local.` hop possible
# against a caller that does not exist) this is the reference list verbatim --
# the hcl_raw and terraconstructs reading, unchanged. Inside a module the
# resource names the module's own input or iteration variable, and the
# reference that decides the fact is what the caller passed.
resolved_refs(p, r, attribute) := direct | through_var | through_each | through_local if {
	direct := {ref |
		some ref in references(r, attribute)
		not startswith(ref, "var.")
		not startswith(ref, "each.")
		not startswith(ref, "local.")
	}
	through_var := {qualified |
		some ref in references(r, attribute)
		startswith(ref, "var.")
		name := split(trim_prefix(ref, "var."), ".")[0]
		some arg in references(calling_node(p), name)
		qualified := concat("", [parent_prefix(p), arg])
	}
	through_each := {qualified |
		some ref in references(r, attribute)
		startswith(ref, "each.")
		some name in for_each_inputs(r)
		some arg in references(calling_node(p), name)
		qualified := concat("", [parent_prefix(p), arg])
	}
	through_local := {qualified |
		some ref in references(r, attribute)
		startswith(ref, "local.")
		some arg in call_references(p)
		qualified := concat("", [parent_prefix(p), arg])
	}
}

# The `[prefix, type, name]` key that joins a configuration resource to its
# planned instances across both sides of the hoist. Not `.address`: a
# `count`/`for_each` meta-argument makes the planned address
# `<address>[key]` while the configuration address stays `<address>`, and an
# `.address` join silently selects NOTHING for such a resource -- a correct
# solution scored 0.0 that way on a sibling scenario.
planned_prefix(r) := concat("", [sprintf("%s.", [segment]) |
	some segment in object.get(r, "x_module_path", [])
])

planned_resources := input.planned_values.root_module.resources

created_buckets := [r |
	some r in planned_resources
	r.type == "aws_s3_bucket"
]

# A bucket created INSIDE a module call is named by the caller through that
# call's output (`module.<call>.s3_bucket_arn`), never by the bucket's own
# hoisted address. With no module-created bucket the set is empty, this second
# reading never holds, and the bare-address match below is the whole rule.
created_bucket_call_prefixes := {prefix |
	some r in created_buckets
	startswith(r.address, "module.")
	prefix := concat("", ["module.", split(trim_prefix(r.address, "module."), ".")[0], "."])
}

references_a_created_bucket(refs) if {
	some ref in refs
	regex.match(`^aws_s3_bucket\.`, ref)
}

references_a_created_bucket(refs) if {
	some ref in refs
	some prefix in created_bucket_call_prefixes
	startswith(ref, prefix)
}

# principal is always plan-time-known (a static literal, never
# provider-computed), so read it from `.planned_values` and join back to the
# `.configuration` resource for the source_arn graph-edge check. A comprehension
# over `.expressions.principal.constant_value` instead selects NOTHING whenever
# the principal is indirected through a `local`, a `var` or a `for_each` value,
# and the fail-closed rule then denies a correct solution.
#
# A SET of keys, not an object keyed by them: a `for_each`-expanded permission
# has N planned instances sharing one key, and an object rule binding one key to
# two different principals raises `eval_conflict_error`, which aborts evaluation
# and scores a correct solution 0.0 with no deny message at all.
s3_invoke_principal_keys := {[planned_prefix(r), r.type, r.name] |
	some r in planned_resources
	r.type == "aws_lambda_permission"
	object.get(r, ["values", "principal"], null) == "s3.amazonaws.com"
}

s3_invoke_permissions := [[p, r] |
	some [p, r] in config_resources
	r.type == "aws_lambda_permission"
	[module_prefix(p), r.type, r.name] in s3_invoke_principal_keys
]

deny contains msg if {
	some [p, rp] in s3_invoke_permissions
	not references_a_created_bucket(resolved_refs(p, rp, "source_arn"))
	msg := sprintf(
		"%s: principal is s3.amazonaws.com but source_arn does not reference the created aws_s3_bucket (no wildcard/hardcoded/omitted SourceArn permitted)",
		[concat("", [module_prefix(p), rp.address])],
	)
}

# Fail-closed: a bucket exists but no s3.amazonaws.com-principal'd Lambda
# permission exists anywhere in the plan at all. Counted over PLANNED
# resources, so a permission declared inside an installed module body counts
# exactly as the root module's own does.
deny contains msg if {
	count(created_buckets) > 0
	count(s3_invoke_principal_keys) == 0
	msg := "an aws_s3_bucket exists, but no aws_lambda_permission resource granting principal s3.amazonaws.com exists anywhere in the plan -- S3 cannot invoke the Lambda function without one"
}
