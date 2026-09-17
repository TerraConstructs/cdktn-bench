#!/usr/bin/env bash
# Runs INSIDE the spike image (scripts/spike/Dockerfile). Reads a TSV of
# (id, policy, lib, query, artifact) on stdin and, for each row, evaluates the
# query with opa 1.19.0 and with regorus 0.12.0 over the same artifact bytes,
# emitting one JSON object per row on stdout.
#
# The opa line is the one generator/gen.py emits into tests/static_tiers.sh
# (`-f raw -I`, artifact on stdin). regorus has neither flag, so it takes the
# artifact as `-i` and its OPA-shaped result is reduced to the same value by
# jq; that reduction is the only normalisation applied before the comparison.
set -uo pipefail

norm_sorted() {  # a rule set is a set: compare sorted, or pass a scalar through
  jq -cS 'if type=="array" then sort else . end' 2>/dev/null || echo '<UNPARSEABLE>'
}

while IFS=$'\t' read -r id policy lib query artifact; do
  [ -z "${id:-}" ] && continue
  dopts=(-d "$policy")
  [ "$lib" != "-" ] && dopts+=(-d "$lib")

  t0=$(date +%s%N)
  opa_out=$(opa eval -f raw -I "${dopts[@]}" "$query" < "$artifact" 2>/tmp/opa.err)
  opa_rc=$?
  t1=$(date +%s%N)
  regorus_out=$(regorus eval "${dopts[@]}" -i "$artifact" "$query" 2>/tmp/reg.err)
  reg_rc=$?
  t2=$(date +%s%N)
  # regorus defaults to STRICT builtin errors, `opa eval` does not; `-n` is
  # regorus's opt-in to OPA's default, so it is measured as its own column
  # rather than inferred.
  regn_out=$(regorus eval -n "${dopts[@]}" -i "$artifact" "$query" 2>/tmp/regn.err)
  regn_rc=$?

  opa_val=$(printf '%s' "$opa_out" | norm_sorted)
  # regorus prints OPA's `--format json` shape; the graded value is the single
  # expression of the single query result. An undefined query yields no results.
  reg_val=$(printf '%s' "$regorus_out" \
    | jq -cS 'if (.result//[])|length == 0 then null
              else (.result[0].expressions[0].value
                    | if type=="array" then sort else . end) end' 2>/dev/null \
    || echo '<UNPARSEABLE>')
  regn_val=$(printf '%s' "$regn_out" \
    | jq -cS 'if (.result//[])|length == 0 then null
              else (.result[0].expressions[0].value
                    | if type=="array" then sort else . end) end' 2>/dev/null \
    || echo '<UNPARSEABLE>')
  [ -z "$opa_val" ] && opa_val=null
  [ -z "$reg_val" ] && reg_val=null
  [ -z "$regn_val" ] && regn_val=null

  jq -nc \
    --arg id "$id" --arg query "$query" \
    --arg opa_raw "$opa_out" --arg reg_raw "$regorus_out" \
    --argjson opa_val "${opa_val:-null}" --argjson reg_val "${reg_val:-null}" \
    --argjson opa_rc "$opa_rc" --argjson reg_rc "$reg_rc" \
    --argjson regn_val "${regn_val:-null}" --argjson regn_rc "$regn_rc" \
    --arg regn_err "$(tail -c 2000 /tmp/regn.err)" \
    --arg opa_err "$(tail -c 2000 /tmp/opa.err)" --arg reg_err "$(tail -c 2000 /tmp/reg.err)" \
    --argjson opa_ms "$(( (t1-t0)/1000000 ))" --argjson reg_ms "$(( (t2-t1)/1000000 ))" \
    '{id:$id, query:$query, opa:{rc:$opa_rc, value:$opa_val, raw:$opa_raw, err:$opa_err, ms:$opa_ms},
      regorus:{rc:$reg_rc, value:$reg_val, raw:$reg_raw, err:$reg_err, ms:$reg_ms},
      regorus_non_strict:{rc:$regn_rc, value:$regn_val, err:$regn_err},
      agree: ($opa_val == $reg_val),
      agree_non_strict: ($opa_val == $regn_val)}'
done
