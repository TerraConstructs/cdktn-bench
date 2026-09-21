# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   sfn-jsonata
# Intent doc: oracles/sfn-jsonata/intent.md
# TF half:    ../../rego/sfn-jsonata/policy.rego
# `input` is the awscdk arm's synthesized CloudFormation template, not the
# plan JSON the TF half sees (specs/SCHEMA.md §4.5); the generated
# tests/static_tiers.sh evaluates this package's `deny` against that
# template and fails tier 1 on a non-empty set.
#
# STRICTER THAN THE RETIRED CFN-GUARD POLICY, which had no JSON-decode
# builtin and could only regex the still-encoded DefinitionString: its
# QueryLanguage search passed a machine whose top-level language was
# JSONPath and whose nested state named JSONata, and its banned-key
# alternation fired on those six words inside any string VALUE. This walks
# the decoded ASL the way the TF half does. No fixture verdict changes --
# the escape-hatch fixture still denies on ResultPath, raw-jsonpath-literal-
# value-only on the raw "$." literal, jsonata-expression-correctness passes.

package cdktn_bench.sfn_jsonata

import rego.v1

# The five classic JSONPath-only ASL fields plus ItemsPath, the
# Map-state-specific sixth one -- the spec's six no-jsonpath-* asserts.
banned_keys := {
	"InputPath", "OutputPath", "Parameters",
	"ResultPath", "ResultSelector", "ItemsPath",
}

state_machines[id] := r if {
	some id, r in object.get(input, "Resources", {})
	r.Type == "AWS::StepFunctions::StateMachine"
}

definition_string(sm) := s if {
	s := object.get(sm, ["Properties", "DefinitionString"], null)
	is_string(s)
}

definitions[id] := doc if {
	some id, sm in state_machines
	doc := json.unmarshal(definition_string(sm))
}

deny contains msg if {
	count(state_machines) == 0
	msg := "no AWS::StepFunctions::StateMachine exists in the template"
}

# Fail closed per machine, not once for the whole template: a definition
# assembled from Fn::Join/Fn::Sub intrinsics is not a string this policy can
# decode, and a JSONPath artifact hidden inside one must not pass silently.
deny contains msg if {
	some id, _ in state_machines
	not definitions[id]
	msg := sprintf(
		"%s: DefinitionString did not decode into a usable ASL document -- a definition assembled from intrinsics cannot be checked for JSONPath-mode leakage from this template",
		[id],
	)
}

deny contains msg if {
	some id, doc in definitions
	actual := object.get(doc, "QueryLanguage", null)
	actual != "JSONata"
	msg := sprintf("%s: state machine QueryLanguage is %v, expected \"JSONata\"", [id, actual])
}

# `walk(doc, [path, value])` visits every node; the key a value was found
# under is the last element of that value's own path. The two-output-argument
# call form, never `some path, value in walk(doc)`, which iterates the result
# SET by (index, element) and silently type-errors.
deny contains msg if {
	some id, doc in definitions
	walk(doc, [path, _])
	count(path) > 0
	key := path[count(path) - 1]
	key in banned_keys
	msg := sprintf(
		"%s: JSONata-mode state machine definition contains a JSONPath-mode artifact %q at path %v (mode-mixing)",
		[id, key, path],
	)
}

# Read from the RAW, still-encoded text, not the decoded object: a decoded
# JSONata expression never contains a literal `"$.` right after a quote --
# JSONata references start with `$states`/`$` alone. The literal JSONata
# delimiter text stays out of the format string because Go's fmt reads a
# bare "%" as the start of a verb.
deny contains msg if {
	some id, sm in state_machines
	regex.match(`"\$\.`, definition_string(sm))
	msg := sprintf(
		"%s: JSONata-mode definition contains a raw (un-evaluated) \"$.\"-prefixed JSONPath string literal instead of a proper JSONata expression wrapped in percent-sign-brace delimiters",
		[id],
	)
}
