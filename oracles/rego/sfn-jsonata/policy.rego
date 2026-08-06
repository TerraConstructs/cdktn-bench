# Hand-authored (Slice D). NOT a generator stub.
#
# Scenario:      sfn-jsonata (specs/sfn-jsonata.yaml)
# Intent doc:    oracles/sfn-jsonata/intent.md
# Graded against `terraform show -json` plan JSON for the hcl_raw arm
# (terraconstructs is excluded from this scenario -- see the spec's own
# arms.terraconstructs.reason) -- specs/SCHEMA.md §4.2/§8. `input` at
# policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.sfn_jsonata.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes the spec's mode-mixing-jsonpath-artifacts catch: ALL of it is
# tier-"1" (see that catch's own description in specs/sfn-jsonata.yaml for
# why -- summary: jq's narrow JSONPath-subset grammar this repo compiles
# cfn_jsonpath/tf_jsonpath into has no "search every string leaf,
# unanchored" primitive the way Rego's native `walk()`/`regex.match()`
# builtins do, so the "no raw un-evaluated JSONPath string ANYWHERE"
# half of this catch has no tier-0 equivalent at all -- and the six
# banned-key checks are kept here alongside it, at the SAME tier, as one
# coherent "well-formed JSONata-mode machine" policy bundle rather than
# splitting one catch's mechanism across two tiers for no semantic reason).
#
# Verified against a real, hand-built `terraform show -json` plan document
# (this scenario's own reference solution, solution/solve.sh's main.tf,
# plus a deliberately-mode-mixed negative -- see
# solution/broken/mode-mixing-jsonpath-artifacts/main.tf) before this
# policy shipped: `opa eval` denies the negative and stays silent on the
# reference solution, for every rule below individually.

package cdktn_bench.sfn_jsonata

import rego.v1

# The five classic JSONPath-only ASL fields, plus ItemsPath (the
# Map-state-specific sixth one) -- specs/sfn-jsonata.yaml's own six
# no-jsonpath-* structural_asserts document each individually as the tier-1
# spec for this rule; this is the native-Rego equivalent of all six at
# once, via walk() instead of six separate "..Field"-style jq paths.
banned_keys := {
	"InputPath", "OutputPath", "Parameters",
	"ResultPath", "ResultSelector", "ItemsPath",
}

state_machines := [pv |
	some pv in input.planned_values.root_module.resources
	pv.type == "aws_sfn_state_machine"
]

# `values.definition` is a jsonencode()'d STRING (same |fromjson case the
# tier-0 asserts document) -- decode it once per state machine resource
# into the full ASL object.
definitions := [doc |
	some sm in state_machines
	doc := json.unmarshal(sm.values.definition)
]

# --- fail-closed: a state machine exists but its definition didn't decode
# into anything walkable at all (should be structurally impossible for any
# artifact that passed tier-0's own query-language-is-jsonata assert first,
# but this policy is also independently invoked by
# generator/check_reference_paths.py against arbitrary fixtures, so it must
# not silently pass on a malformed/empty definition either).
deny contains msg if {
	count(state_machines) > 0
	count(definitions) == 0
	msg := "an aws_sfn_state_machine exists, but its definition did not decode into a usable ASL document"
}

# --- QueryLanguage: belt-and-suspenders alongside the tier-0
# query-language-is-jsonata assert -- this policy bundle is meant to
# comprehensively certify "well-formed JSONata-mode machine, no JSONPath
# leakage" as one unit, not rely on tier-0 alone for the query-language
# half of that claim.
deny contains msg if {
	some doc in definitions
	actual := object.get(doc, "QueryLanguage", null)
	actual != "JSONata"
	msg := sprintf("state machine QueryLanguage is %v, expected \"JSONata\"", [actual])
}

# --- banned JSONPath-only keys, anywhere in the decoded ASL document at any
# depth. `walk(doc, [path, value])` visits every (path, value) node; the
# object KEY a value was found under is the last element of that value's
# own path (Rego's own documented walk() semantics: for {"a": {"b": 1}},
# walk visits ([], obj), (["a"], {"b":1}), (["a","b"], 1) -- so
# path[count(path)-1] on the THIRD visit is "b", the key "b"'s value was
# found under). NOTE: `walk(doc, [path, value])` -- the two-output-argument
# call form -- not `some path, value in walk(doc)`, which iterates
# walk(doc)'s own SET of [path, value] two-element arrays by (set-index,
# element) pairs, not by (path, value) -- an easy, silently type-erroring
# mistake caught here before this policy shipped (`opa eval` rejects it
# outright: "count: invalid argument(s), have: (number, ???)").
deny contains msg if {
	some doc in definitions
	walk(doc, [path, _])
	count(path) > 0
	key := path[count(path) - 1]
	key in banned_keys
	msg := sprintf(
		"JSONata-mode state machine definition contains a JSONPath-mode artifact %q at path %v (mode-mixing)",
		[key, path],
	)
}

# --- raw, un-evaluated "$."-prefixed JSONPath string literal, anywhere in
# the definition text. Operates on the RAW (still JSON-encoded) string --
# same pattern as specs/sfn-jsonata.yaml's own no-raw-jsonpath-string-literal
# structural_assert's `not_regex` check, not the decoded object (a decoded
# JSONata expression string like "{% $states.input.orders %}" never
# contains a literal `"$.` substring immediately after a quote -- JSONata
# references start with `$states`/`$` alone, never `$.`).
deny contains msg if {
	some sm in state_machines
	regex.match(`"\$\.`, sm.values.definition)
	# NOTE: the literal JSONata delimiter text is deliberately NOT embedded
	# in this sprintf format string -- Go's fmt package (which `sprintf`
	# wraps) treats a bare "%" as the start of a verb, and "{% ... %}"
	# breaks that (rendered as literal "%!.(MISSING)" noise in the message,
	# confirmed against a real opa eval run before this fix); described in
	# prose instead.
	msg := sprintf(
		"%s: JSONata-mode definition contains a raw (un-evaluated) \"$.\"-prefixed JSONPath string literal instead of a proper JSONata expression wrapped in percent-sign-brace delimiters",
		[sm.address],
	)
}
