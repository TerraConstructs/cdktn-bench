#!/usr/bin/env bash
# Runs INSIDE the spike image. Records the engine behaviours the pair table
# cannot show: coverage output, an undefined query, a policy that does not
# parse, and a builtin error (the engines' defaults differ there).
#
# Argument triples are (family, policy, artifact); the query package is derived
# from the policy's own `package` line.
set -uo pipefail
sep() { echo; echo "########## $* ##########"; }

run() {  # run <label> <cmd...>
  local label="$1"; shift
  echo "--- $label"
  echo "\$ $*"
  "$@" > /tmp/out 2> /tmp/err
  echo "exit=$?"
  echo "stdout: $(head -c 1200 /tmp/out)"
  echo "stderr: $(head -c 1200 /tmp/err)"
}

while [ $# -gt 0 ]; do
  family="$1"; policy="$2"; artifact="$3"; lib="$4"; shift 4
  pkg=$(grep -m1 '^package ' "$policy" | awk '{print $2}')
  dopts=(-d "$policy"); [ "$lib" != "-" ] && dopts+=(-d "$lib")

  sep "$family: coverage (regorus only; opa eval has no equivalent)"
  run "regorus eval --coverage deny" regorus eval "${dopts[@]}" -i "$artifact" --coverage "data.$pkg.deny"

  sep "$family: undefined query (a rule that does not exist)"
  run "opa undefined" opa eval -f raw -I "${dopts[@]}" "data.$pkg.no_such_rule_at_all" < "$artifact"
  run "regorus undefined" regorus eval "${dopts[@]}" -i "$artifact" "data.$pkg.no_such_rule_at_all"

  sep "$family: policy with a syntax error"
  broken=/tmp/broken-$$.rego
  { cat "$policy"; echo; echo "deny contains msg if {"; } > "$broken"
  run "opa syntax-error" opa eval -f raw -I -d "$broken" "data.$pkg.deny" < "$artifact"
  run "regorus syntax-error" regorus eval -d "$broken" -i "$artifact" "data.$pkg.deny"
  rm -f "$broken"
done

sep "builtin error on a value the policy did not expect (engine defaults differ)"
cat > /tmp/builtin.rego <<'REGO'
package probe

import rego.v1

deny contains msg if {
	doc := json.unmarshal(input.not_json)
	msg := sprintf("parsed %v", [doc])
}
REGO
echo '{"not_json": "this is not json"}' > /tmp/builtin.json
run "opa (default)" opa eval -f raw -I -d /tmp/builtin.rego "data.probe.deny" < /tmp/builtin.json
run "opa --strict-builtin-errors" opa eval -f raw -I --strict-builtin-errors -d /tmp/builtin.rego "data.probe.deny" < /tmp/builtin.json
run "regorus (default)" regorus eval -d /tmp/builtin.rego -i /tmp/builtin.json "data.probe.deny"
run "regorus -n (non-strict)" regorus eval -n -d /tmp/builtin.rego -i /tmp/builtin.json "data.probe.deny"
