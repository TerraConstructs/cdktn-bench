# Tier-0 assert libraries — is there something off the shelf?

The question this memo answers: instead of compiling `oracle.structural_asserts`
to jq (today) or to Rego (the M10 experiment, whose emitted `tests/tier0.rego`
runs 892 lines for 6 asserts —
`tasks/anchor-1/ecr-repo-destroy-force-delete-terraconstructs/tests/tier0.rego`),
is there an existing assertion or policy library that runs directly over JSON
documents and fits this bench?

Short answer: no library gives the bench's three-valued outcome, and every
candidate that could express the paths either duplicates what jq already does
or is less readable than the jq one-liners. The change worth making is not a
new library — it is deleting the bash.

## 1. What tier-0 actually needs

Seven properties, all load-bearing, all sourced from what the repo already
enforces:

1. **Nine ops** — `eq exists not_exists in contains regex set_eq absent_or_eq
   not_regex` (`generator/gen.py` `ASSERT_LIB_SH`, ~line 1755; the same table
   in Python at `oracles/lib/structural.py:220`). `eq` demands *exactly one*
   node; `in`/`set_eq` flatten one level; `contains` is substring on strings and
   membership on lists, never a regex; `not_regex` passes vacuously on zero
   nodes.
2. **Three-valued outcome** — held (rc 0) / contradicted (rc 1) / unresolvable
   (rc 2). "The proof did not run" is not "the artifact is wrong".
   `gates/tier0_parity.py:43` and `oracles/tests/test_op_parity.py:1` compare
   engines on this triple, not on a bool.
3. **A per-assert named result** — `gates/emit_result.py:282` parses
   `  PASS [name]` / `  FAIL [name]: …` out of `verifier/test-stdout.txt`, keyed
   on the kebab-case `structural_assert.name`; the falsifiability gate parses
   `== summary: tier0_pass=N tier1_status=X ==`
   (`gates/oracle_falsifiability.py:172`).
4. **The path grammar** — field access, `..Field` recursive descent, `[*]`,
   `[?(@.F=='V')]` filters including nested-field and `||`-OR'd conditions, bare
   `[?(@=='V')]`, and one or more `|fromjson` hops into `jsonencode`d strings
   (`generator/jsonpath_jq.py:15-55`). Measured over `specs/*.yaml` on
   2026-09-18: 287 declared path literals, 88 with `[*]`, 24 with `|fromjson`,
   20 with `..`, 7 with OR'd filters, 4 with a nested filter field.
5. **Null-drop** — jq returns `null` for an absent key, so results are collected
   and `map(select(. != null))`ed before the op runs; without it `not_exists`
   never passes.
6. **One spec, two paths side by side** — `cfn_jsonpath` and `tf_jsonpath` on
   the same assert entry is *the* oracle-equivalence mechanism, not
   documentation of it (`specs/SCHEMA.md` §4.2). Equal strictness across arms is
   reviewed by reading the two paths on one screen.
7. **Offline, in three images** — `jq`, `python3` (stdlib, no pip), `opa` 1.19.0
   in all three arm Dockerfiles; `cfn-guard` 3.2.0 in `arms/awscdk` only.

## 2. Survey

Everything below runs offline once installed. "Fits?" answers properties 1–4,
not general quality.

### 2a. Query engines

| tool | ver / lang / licence | size | fits? |
|---|---|---|---|
| **jq** (incumbent) | upstream 1.8.2; Debian bookworm apt ships **1.6** (`1.6-2.1+deb12u2`), which is what all three arm images install | ~2 MB, already installed | Yes — it is the grammar the compiler targets. Regex is Oniguruma. See the version note below. |
| gojq | 0.12.19, Go, MIT; bookworm packages 0.12.11 | ~2 MB | Same grammar, Go `regexp` (RE2) instead of Oniguruma, plus documented deliberate divergences from jq. Swapping buys nothing and re-opens the regex-flavour question. |
| jaq | 3.1.1, Rust, MIT; not in bookworm | ~4 MB static musl | A jq subset, fast, fully static. A second dialect to pin for no gain. |
| yq (mikefarah) | 4.53.6, Go, MIT | ~13 MB | Its own expression language, strictly less capable here. Also a trap: `apt-get install yq` on bookworm installs kislyuk's Python `yq` (3.1.0-3), a different tool. |
| JMESPath (`jp`, `jmespath`) | `jp` stale since 2023; Python `jmespath` 1.1.0, MIT | ~5 MB / 20 KB wheel | **No.** The JMESPath specification has no recursive-descent operator and no regex in core. 20 `..` paths and 8 regex asserts are inexpressible. Filters do support OR and multiple fields. |
| RFC 9535 JSONPath (`theory/jsonpath`, `ohler55/ojg`+`oj`, `python-jsonpath` 2.2.1, `jsonpath-ng` 1.8.0) | Go / Python, MIT–Apache-2.0 | binary or 65 KB wheel | Expressive enough for the paths — `python-jsonpath` is RFC 9535-compliant and ships a CLI — but they are *query* libraries: no ops, no outcome model, no named results. Everything in §1.1–1.3 stays hand-written, and the Python ones are pip packages the stdlib-only images do not have. `ojg` is a Goessner-derived dialect, not RFC 9535. |
| dasel, gron | dasel 3.11.2 (own DSL, has `..`); gron unreleased since 2022 | ~4–10 MB | dasel's selector DSL is a third grammar to pin with unconfirmed regex support; gron flattens JSON into greppable text and has no predicate language. |

**The jq version the grader actually runs.** All three Dockerfiles install jq
from bookworm apt, so trials grade under jq 1.6 while the host-side parity
tests (`gates/tier0_parity.py`, `oracles/tests/test_op_parity.py`) run whatever
jq the developer has — 1.7.1 on the machine this memo was written on. Nothing
in the corpus is known to depend on the difference, but it is an unpinned
engine in a bench that pins `opa` and `cfn-guard` by sha256. Worth closing
independently of anything else in this memo.

### 2b. Policy / assertion engines

| tool | ver / lang / licence | size | fits? |
|---|---|---|---|
| **cfn-guard** | 3.2.1, Rust, Apache-2.0; 3.2.0 in the awscdk image | ~3 MB tarball | Partly — §3. AWS documents it as a general-purpose JSON/YAML policy tool, Terraform JSON included; the name is misleading. |
| **OPA / Rego** | 1.19.0 pinned, Go, Apache-2.0 | 57 MB, in all three images | Already the tier-1 engine. Hand-written Rego is readable (§4c); *generated* Rego is not, because the three-valued outcome must be spelled out rule by rule. RE2 regex. |
| Conftest | 0.70.0, Go, Apache-2.0 | ~20 MB | A CLI wrapper around the same Rego. A second binary, a `deny[msg]` convention, no change to readability or to the outcome model. |
| Checkov custom policies | 3.3.19, Python, Apache-2.0 | small wheel, hundreds of MB of deps | Scans its own parsed-IaC graph; Terraform plan JSON is a first-class framework but an arbitrary-JSON custom-rule mode is not. pip install contradicts the stdlib-only images. |
| HashiCorp Sentinel | ~0.41.0, **proprietary, closed source** | binary | Runs offline against mock data, but a closed-source grader cannot be reproduced by a third party reading this bench. |
| kyverno-json | 0.0.x, Go, Apache-2.0 | static binary | Closest in intent — `kyverno json scan --payload` over any JSON, with Terraform plan JSON in the documented quick start. Its assertion trees are built on **JMESPath**, so they inherit the missing recursive descent; outcomes are pass/fail with no "could not evaluate" class; and every release is 0.0.x behind a `KYVERNO_EXPERIMENTAL` gate with no backward-compatibility promise. |
| CUE (`cue vet`) | ~0.17.1, Go, Apache-2.0 | ~15 MB | A *schema* language, and a capable one: `=~` regex (RE2), `[=~"^i"]: T` pattern constraints, and `field?:` vs `field!:` genuinely distinguishing absent from wrong. What it has no way to say is "exactly one element of this array matching a predicate", and it has no arbitrary-depth descent. Errors are path-keyed, not assert-name-keyed, so property 3 needs a translation layer. |
| JSON Schema (ajv 8.20, check-jsonschema 0.38, `jsonschema` 4.26) | MIT / Apache-2.0 | npm+node, or pip (`jsonschema` pulls the Rust-compiled `rpds-py`, so not pure Python) | Same class of mismatch as CUE, plus `contains`/`set_eq` become bespoke keywords, plus no cross-node joins. |
| Google CEL | Apache-2.0 | — | **There is no official CLI.** cel-go ships a demo REPL described as educational; a usable binary means building a Go wrapper of our own. cel-python's interpreter is pure Python but depends on the compiled `google-re2`. The expression language would suit the ops; there is nothing off the shelf to install. |
| JSONLogic | MIT | tiny | Deliberately not a traversal language — a predicate evaluator over a known shape, no descent, no wildcards. A `tests/tier0.json` of JSONLogic reads worse than the jq line it replaces and still needs a driver. |
| `terraform test` | BUSL-1.1 from 1.6.0 | terraform, present on TF arms | `command = plan` plus `mock_provider` does run offline, but it asserts in Terraform's own expression language against the configuration's plan, not against the exported `terraform show -json` document — and it exists on two arms of three, so it cannot be the cross-arm oracle. |
| cfn-lint custom rules | MIT-0, Python | pip, ~5 MB + deps | CloudFormation only, Python-plugin rules. Same arm-asymmetry problem. |
| jd / jsondiff | MIT | small | They answer "do these two documents differ", which needs a golden document. Different question. |

## 3. cfn-guard over Terraform plan JSON — verified, and it nearly works

Run against `cfn-guard 3.2.0` on 2026-09-18 with a synthetic
`terraform show -json` fragment:

* **It reads arbitrary JSON.** `cfn-guard validate --data plan.json --rules
  acm.guard` evaluates against plan JSON; a deliberately wrong expectation
  reports `rc=19` with the offending JSON pointer.
* **It emits the three sets machine-readably.** `--output-format json` returns
  `compliant` / `not_compliant` / `not_applicable` as lists of rule names — a
  natural per-assert named result.
* **`json_parse(...)` covers `|fromjson`** (`parse_string` does not; it silently
  leaves the string unparsed and the rule then fails for the wrong reason).
* **Rule names cannot contain `-`.** `rule hosted-zone-exists` is a parse error,
  so the kebab-case assert names the gates key on need a mapping layer.

Two disqualifying gaps:

* **No recursive descent.** Guard has `*` for one level; there is no `..`. The
  20 paths that need it would have to enumerate depth, which is exactly the
  fragility `..Field` was added to avoid.
* **A path that resolves to nothing is SKIP, and SKIP is a pass.**
  `rule cert_dn { Resources.*[ Type == "AWS::NotThere" ].Properties.DomainName ==
  "x" }` returns `Status = SKIP`, `rc=0`. Under the bench's table that assert is
  *contradicted* (`eq` requires exactly one node). Restoring the distinction
  needs a paired existence rule per assert, which breaks the one-rule-per-assert
  mapping the summary and the gates read. And a genuine traversal error (field
  access into a scalar) is reported as FAIL, not as "unresolvable" — the exact
  collapse the three-valued contract exists to prevent.

`set_eq` is also not expressible: Guard has `IN` (subset) but no set equality,
so "and nothing else" needs a count rule alongside.

## 4. Five asserts, three ways

All three render `specs/acm-dns-validation-record-wiring.yaml`'s five tier-0
asserts for the awscdk arm. All three were executed.

### 4a. jq filters + a generated Python driver (recommended)

```python
ASSERTS = [
    ("hosted-zone-exists",
     '.Resources | .[] | select(.Type=="AWS::Route53::HostedZone")',
     "exists", None),
    ("certificate-exists",
     '.Resources | .[] | select(.Type=="AWS::CertificateManager::Certificate")',
     "exists", None),
    ("certificate-domain-name-is-zone",
     '.Resources | .[] | select(.Type=="AWS::CertificateManager::Certificate") | .Properties.DomainName',
     "eq", "storefront.example.com"),
    ("certificate-san-includes-www-cfn",
     '.Resources | .[] | select(.Type=="AWS::CertificateManager::Certificate") | .Properties.SubjectAlternativeNames | .[]',
     "contains", "www.storefront.example.com"),
    ("validation-method-is-dns",
     '.Resources | .[] | select(.Type=="AWS::CertificateManager::Certificate") | .Properties.ValidationMethod',
     "eq", "DNS"),
]
```

The jq filter column is byte-identical to what `static_tiers.sh` carries today.
The op table and the three-valued outcome move into a generated `tests/ops.py`
(~70 lines of stdlib Python, one `subprocess.run(["jq", …])` per assert). Output
is unchanged: `  PASS [name]`, `  FAIL [name]: op=… expected=… resolved=…`,
`TIER0_PASS=1`. Cost measured: 117 jq invocations in 0.35 s; a real task runs
about six.

### 4b. cfn-guard

```
let zones = Resources.*[ Type == "AWS::Route53::HostedZone" ]
let certs = Resources.*[ Type == "AWS::CertificateManager::Certificate" ]

rule hosted_zone_exists { %zones not empty }
rule certificate_exists { %certs not empty }
rule certificate_domain_name_is_zone when %certs not empty {
  %certs.Properties.DomainName == "storefront.example.com"
}
rule certificate_san_includes_www_cfn when %certs not empty {
  some %certs.Properties.SubjectAlternativeNames[*] == "www.storefront.example.com"
}
rule validation_method_is_dns when %certs not empty {
  %certs.Properties.ValidationMethod == "DNS"
}
```

Reads beautifully. The `when … not empty` guards are what turn a missing
certificate into SKIP-as-pass; removing them does not fix it, it just moves the
vacuous pass (§3).

### 4c. Hand-written Rego

```rego
package tier0
import rego.v1

certs := [r | some r in input.Resources; r.Type == "AWS::CertificateManager::Certificate"]
zones := [r | some r in input.Resources; r.Type == "AWS::Route53::HostedZone"]

held contains "hosted-zone-exists" if count(zones) > 0
held contains "certificate-exists" if count(certs) > 0
held contains "certificate-domain-name-is-zone" if {
	count(certs) == 1
	certs[0].Properties.DomainName == "storefront.example.com"
}
held contains "certificate-san-includes-www-cfn" if {
	some c in certs
	"www.storefront.example.com" in c.Properties.SubjectAlternativeNames
}
held contains "validation-method-is-dns" if {
	count(certs) == 1
	certs[0].Properties.ValidationMethod == "DNS"
}
```

22 lines, runs under the `opa` already in every image, far more readable than
the compiled file — and it does not carry `contradicted` vs `unresolvable`.
Rego's undefined is silent, so every situation jq raises on needs its own
explicit rule. That is the whole difference between these 22 lines and the
generated 892: the compiler is not clumsy, it is paying for a property a
hand-written file quietly drops.

## 5. The spec-folder split

The option: `specs/<id>/spec.yaml` plus `asserts.cfn.<ext>` and
`asserts.tf.<ext>`, hand-authored per backend, with the generator copying rather
than compiling.

What it costs, concretely:

* **Parity review dies.** Today `certificate-domain-name-is-zone` shows
  `cfn_jsonpath` and `tf_jsonpath` on adjacent lines, and the reviewer's only
  job is to see whether they ask the same question at the same strictness. Two
  files in two directories is where a cross-arm strictness gap hides — the same
  argument `specs/SCHEMA.md` §4.5 already makes for keeping the two tier-1 Rego
  bundles apart *and* naming that as the reason the tier-0 path stays shared.
  The one place the corpus genuinely diverges (`certificate-san-includes-www-cfn`
  vs `certificate-san-includes-both-names-tf`) is already handled inside the
  YAML by two asserts with disjoint `applies_to`, with the provider's
  `CustomizeDiff` behaviour documented between them.
* **Seven consumers stop working on paths.** `generator/check_reference_paths.py`
  (resolves every declared path, tier 0 and 1, against a real reference
  artifact), `gates/tier0_parity.py`, `generator/check_tier1_coverage.py`,
  `metrics/tokens_to_green.py` (per-catch attribution keyed on assert name),
  `oracles/emit.py` (scaffolds tier-1 policies from tier-1 assert entries),
  `generator/spec_model.py`'s `steps[].oracle.structural_asserts` name
  projection, and the corpus-wide vocabulary sweep in
  `generator/tests/test_scenario_identity.py`. Each would need a parser for the
  chosen library's syntax to recover `name`, `tier` and `applies_to`, or those
  fields get duplicated into the YAML and can drift.
* **The falsifiability and grading-proof gates are safe either way** — they key
  on the summary line and on `PASS [name]`, both of which any driver can emit.

What it buys: per-backend divergence without a schema escape hatch. The corpus
has one such divergence in 20 specs, already expressible. Not worth it.


## 6. Recommendation

**Primary: keep the jq filters, delete the bash.** Replace
`ASSERT_LIB_SH` + the `assert_check` lines in `tests/static_tiers.sh` with a
generated `tests/tier0.py` (the assert table of §4a) and a generated
`tests/ops.py` (the op table and the three-valued outcome, stdlib only). This is
the same move `docs/design/shell-inventory.md` already names for class 2 —
"a Python verifier entry point replaces it" — and it is the largest single bite
of the ~1,200 lines of emitted bash.

* **Image**: nothing added, nothing removed. `jq`, `python3` and `opa` are
  already in all three Dockerfiles.
* **Generator**: `jsonpath_jq.py` stays exactly as it is — the compiler is not
  the problem. `ASSERT_LIB_SH` and the `assert_check` emission go; `tier0.py`
  and `ops.py` replace them.
* **Summary line and gates**: untouched. `tier0.py` prints the same
  `  PASS [name]` / `  FAIL [name]: …` lines, and `static_tiers.sh` keeps
  printing `== summary: tier0_pass=… tier1_status=… ==` around a single
  `python3 "$DIR/tier0.py"` call whose exit status sets `tier0_pass`.
* **Regex flavour, pinned by construction**: today tier-0 regex is Oniguruma in
  the grader and Python `re` in the authoring-time reference, which is why
  `oracles/lib/structural.py:197` refuses a pattern the two flavours read
  differently and why `specs/SCHEMA.md` §4.2 carries a three-flavour divergence
  table. Moving the two regex ops into the driver makes Python `re` the single
  flavour for tier 0, and `_UNREPRESENTABLE_PATTERN` becomes unnecessary rather
  than load-bearing. The path column stays jq, but jq never sees a pattern
  again.
* **Migration**: zero per-assert work. All 117 asserts are regenerated from the
  unchanged spec YAML; the jq filter text is carried over character for
  character, so a `make gen-all` diff is reviewable as "bash became Python" and
  nothing else. `oracles/tests/test_op_parity.py` gains the Python driver as a
  fourth column and keeps the jq/bash one until it is deleted; `gates/tier0_parity.py`
  grades the new driver against the old `assert_check` for the whole corpus
  before the switch.
* **Reading it cold**: a reviewer sees a list of `(name, jq filter, op,
  expected)` tuples — the same four things the spec declares — with no shell
  quoting, no `$(jq -n --argjson …)` and no `|| tier0_pass=0` suffix.

**Fallback: leave tier 0 exactly as it is.** The status quo is correct, gated,
and parity-tested. If the Python-driver diff is not worth reviewing right now,
the right action is to close the M10 tier-0-to-Rego branch rather than adopt a
new library: `jsonpath_rego.py` and the generated `tests/tier0.rego` files buy
one-engine tidiness at the cost of a 892-line unreadable artifact per task, and
that trade has already been judged.

**Not recommended, with reasons**: cfn-guard (vacuous SKIP on a missing path, no
recursive descent, no `set_eq`, awscdk-only today); kyverno-json and JMESPath
(no recursive descent, two-valued); CUE and JSON Schema (schema languages, no
per-assert named outcome); Sentinel (licence); `terraform test` and cfn-lint
(single-arm, so they cannot be the cross-arm oracle).

**Effort**: one generator change (~150 lines of template moved from bash to
Python), a regeneration of 62 task directories (64 `static_tiers.sh` files, counting per-step ones), one new parity column in
`oracles/tests/test_op_parity.py`, and one corpus-wide `gates/tier0_parity.py`
run as the acceptance condition. No spec edits, no image rebuild, no assert
rewritten.
