# M10 engine spike — OPA 1.19.0 vs microsoft/regorus 0.12.0

Results of the evaluation `docs/design/m10-one-rego-engine.md` §2 calls for.
Every Rego policy in the repo was evaluated by both engines over the same
graded artifacts. **50 of 504 (policy, artifact, query) pairs diverge**, in
three independent failure classes. Under regorus's default they abort with no
verdict; under `-n` (the flag needed to match OPA's builtin-error default at
all) 22 of them turn a rejected artifact into an accepted one, silently. Under
the memo's own decision rule ("zero divergences … is the condition for a DRAFT
amendment"), the verifier stays on OPA 1.19.0.

The drivers are reusable: `scripts/spike/` (Dockerfile, `collect_artifacts.py`,
`compare_engines.sh`, `run_comparison.py`, `probes.sh`). Nothing under
`specs/`, `oracles/`, `tasks/`, `generator/` or `gates/` was touched.

## 1. Build recipe

`microsoft/regorus` publishes no release binary, no wheel and no npm package;
its CLI is a cargo *example*, so the pin is tag **plus** commit.

| | |
|---|---|
| tag | `regorus-v0.12.0` |
| tag object | `03582dc3129d4f3b4f66771cbfe3cbcc05a49eab` |
| commit | `c6c679f49b93b05d81bf6fd661931b86fcf416ea` |
| build | `cargo install --example regorus --path . --root /out` (README "Getting Started"), default features, then `strip` |
| stage 1 | `rust:1-bookworm`, 426 s on this host (linux/arm64) |
| stage 2 | `debian:bookworm-slim` + opa + jq |
| image | `cdktn-bench-spike/rego-engines:0.12.0`, `sha256:f0e5ff9dc86f44f8863648d3ce1bef81e58352f7b3188ed964951382b80d184d`, 252 MB |

Binaries in the image (`linux/arm64`):

| binary | bytes | sha256 |
|---|---|---|
| `regorus` 0.12.0 (stripped) | 7 477 888 (7.1 MiB) | `65e15b26895c71d89d6c1ee2d636826b211e476d0bdcc0101a6ea31ee89227e9` |
| `opa` 1.19.0 static | 56 969 368 (54.3 MiB) | `06680087ed236c8c6aaa021660d83178db829a2ad30bdb3482481fada6791b2a` |

The opa hash and URL are the ones `arms/hcl-raw/environment/Dockerfile` pins,
verified byte-for-byte by the same `sha256sum -c -` line. regorus is 7.6× the
smaller binary, not the 6.3 MB the README quotes (that figure is a macOS build).

```sh
docker build --platform linux/arm64 \
  -t cdktn-bench-spike/rego-engines:0.12.0 -f scripts/spike/Dockerfile scripts/spike
```

## 2. What was evaluated, and how

**Artifacts.** `scripts/spike/collect_artifacts.py` drives
`gates/oracle_falsifiability.py::_run_solve` under `gates/aws_stub.py`'s
credential-free environment — the same machinery `make falsifiability` uses —
for the reference solution and every `solution/broken/<name>/solve.sh` of every
arm whose generated `tests/static_tiers.sh` contains an `opa eval` line. Serial,
109.6 min of toolchain time, no AWS call. Its one behaviour change over the gate
is that the per-run working copy is kept, because an `oracle.hcl_traversal`
scenario's real tier-1 input is not `plan.json` but the merged document
`static_tiers.sh`'s own `build_hcl_merge_block` writes to
`/logs/verifier/oracle-input.json`. **The `hcl_traversal` merge is therefore
covered, not skipped**: 43 of the 252 artifacts are that merged document,
produced by the generated Python heredoc verbatim (`hcl2json` + `jsonencode`
re-parse + `_hcl` key).

**Queries.** Both queries the generated verifier runs, parsed out of each arm's
own `tests/static_tiers.sh` so the `-d` library files travel with them:

```sh
opa     eval -f raw -I -d policy.rego [-d hcl_traversal.rego] "data.cdktn_bench.<pkg>.deny"            < artifact.json
opa     eval -f raw -I -d policy.rego [-d hcl_traversal.rego] "data.cdktn_bench.<pkg>.not_verifiable"  < artifact.json
regorus eval        -d policy.rego [-d hcl_traversal.rego] -i artifact.json "data.cdktn_bench.<pkg>.deny"
regorus eval     -n -d policy.rego [-d hcl_traversal.rego] -i artifact.json "data.cdktn_bench.<pkg>.deny"
```

regorus has neither `-f raw` nor `-I`: input is a file, and output is always
OPA's `--format json` envelope. The only normalisation before comparison is
`jq '.result[0].expressions[0].value'` on the regorus side and `sort` on both.
`-n` (non-strict builtin errors) is measured as its own column because it is
regorus's opt-in to OPA's *default*, and the difference is load-bearing (§4.3).

**Coverage of the corpus.** 26 policy files (21 `oracles/rego/*/policy.rego`,
5 `oracles/rego-cfn/*/policy.rego`) plus the shared
`oracles/rego/lib/hcl_traversal.rego` — every Rego file in the repo. Each task's
`tests/policy.rego` was confirmed byte-identical to its `oracles/` source, so
the pairs below are the oracles themselves. 21 specs (20 + `_toy`), 252 fixtures
(each contributing a `deny` and a `not_verifiable` pair), 504 pairs.

## 3. Results

**504 pairs: 454 PASS, 50 DIVERGE.** All 252 `not_verifiable` pairs agree. All
50 divergences are on `deny`, and every one is regorus refusing or silently
truncating a verdict OPA produces — there is no case of regorus denying
something OPA accepts.

| spec | arm | pairs | DIVERGE |
|---|---|---|---|
| acm-dns-validation-record-wiring | hcl-raw | 10 | 0 |
| acm-dns-validation-record-wiring | terraconstructs | 10 | 0 |
| apigw-openapi | hcl-raw | 6 | 0 |
| apigw-openapi | terraconstructs | 6 | 0 |
| apigw-redeploy (multi-step) | hcl-raw | 10 | 0 |
| apigw-redeploy (multi-step) | terraconstructs | 6 | 0 |
| apigwv2-route-settings-zero-vs-unset | awscdk | 10 | 0 |
| apigwv2-route-settings-zero-vs-unset | hcl-raw | 10 | 0 |
| asg-launch-template-tag-propagation | hcl-raw | 6 | 0 |
| asg-launch-template-tag-propagation | terraconstructs | 6 | 0 |
| caller-identity-arn-as-principal | awscdk | 6 | **3** |
| caller-identity-arn-as-principal | hcl-raw | 8 | **4** |
| caller-identity-arn-as-principal | terraconstructs | 8 | **4** |
| ddb-gsi-attribute-definitions | awscdk | 12 | **3** |
| ddb-gsi-attribute-definitions | hcl-raw | 10 | **4** |
| ddb-gsi-attribute-definitions | terraconstructs | 8 | **3** |
| ecr-repo-destroy-force-delete | hcl-raw | 6 | 0 |
| ecr-repo-destroy-force-delete | terraconstructs | 6 | 0 |
| ecs-swappiness | hcl-raw | 6 | **1** |
| ecs-swappiness | terraconstructs | 6 | 0 |
| iam-managed-policy-exclusive-vs-attachment | awscdk | 18 | 0 |
| iam-managed-policy-exclusive-vs-attachment | hcl-raw | 20 | 0 |
| iam-managed-policy-exclusive-vs-attachment | terraconstructs | 10 | 0 |
| lambda-alias-tracks-unpublished-latest | hcl-raw | 8 | 0 |
| lambda-alias-tracks-unpublished-latest | terraconstructs | 8 | 0 |
| lambda-log-group-ownership-and-retention | hcl-raw | 10 | **2** |
| lambda-log-group-ownership-and-retention | terraconstructs | 10 | **2** |
| named-resource-replacement | hcl-raw | 8 | 0 |
| named-resource-replacement | terraconstructs | 8 | 0 |
| s3-acl-vs-object-ownership-log-delivery | hcl-raw | 12 | **3** |
| s3-acl-vs-object-ownership-log-delivery | terraconstructs | 12 | **4** |
| s3-bucket-hardening-decomposition | hcl-raw | 14 | 0 |
| s3-bucket-hardening-decomposition | terraconstructs | 14 | 0 |
| s3-lambda-log-retention | hcl-raw | 4 | 0 |
| s3-lambda-log-retention | terraconstructs | 4 | 0 |
| s3-notification-authoritative-singleton | awscdk | 34 | **1** |
| s3-notification-authoritative-singleton (hcl_traversal) | hcl-raw | 86 | **9** |
| s3-notification-authoritative-singleton (hcl_traversal) | terraconstructs | 14 | 0 |
| s3-notification-custom-resource-tax | hcl-raw | 6 | 0 |
| s3-notification-custom-resource-tax | terraconstructs | 6 | 0 |
| sfn-jsonata | hcl-raw | 8 | **1** |
| singleton-child-resource-clobber | hcl-raw | 10 | **1** |
| singleton-child-resource-clobber | terraconstructs | 8 | **1** |
| toy-ssm-parameter | hcl-raw | 8 | **2** |
| toy-ssm-parameter | terraconstructs | 8 | **2** |

Twelve of the 26 policy files are affected: both `caller-identity-arn-as-principal`
policies, both `ddb-gsi-attribute-definitions` policies, both
`s3-notification-authoritative-singleton` policies, and the `ecs-swappiness`,
`lambda-log-group-ownership-and-retention`,
`s3-acl-vs-object-ownership-log-delivery`, `sfn-jsonata`,
`singleton-child-resource-clobber` and `toy-ssm-parameter` TF policies.

## 4. The divergences

Three independent causes. Counts are of the 50 diverging pairs.

### 4.1 `sprintf` Go-syntax verbs are not implemented — 30 pairs

regorus 0.12.0 rejects `%q`, `%T`, `%p` and `%#v`. Nine policy files plus
`lib/hcl_traversal.rego` use `%q` in their deny messages, 37 occurrences; no
policy uses `%T`, `%p` or `%#v`.

```rego
package repro
import rego.v1

deny contains msg if {
	msg := sprintf("%q", ["abc"])
}
```

| engine | exit | stdout |
|---|---|---|
| `opa eval -f raw -I` | 0 | `["\"abc\""]` |
| `regorus eval` | 1 | *(empty; stderr `error: Go-syntax format verbs %#v. %q, %p and %T are not supported.`)* |
| `regorus eval -n` | 0 | `[]` |

The `-n` row is the dangerous one: the builtin error becomes *undefined*, the
rule does not fire, and **the deny message disappears from an otherwise correct
verdict**. On 22 pairs that empties the whole `deny` set on an artifact OPA
rejects — a broken fixture scoring 0.0 today would score **1.0**. Minimal case
from the corpus:

```sh
regorus eval -n -d oracles/rego/ecs-swappiness/policy.rego \
  -i ecs-swappiness/hcl-raw/broken/swappiness-requires-maxswap/plan.json \
  data.cdktn_bench.ecs_swappiness.deny     # -> []   (opa: one deny message)
```

On the other 12 pairs the deny set stays non-empty but loses messages, so the
reward is unchanged and only `grading_proof`'s recorded reason moves.

### 4.2 Two Rego constructs the scheduler cannot handle — 12 pairs

Hard errors in **both** strict and non-strict mode, exit 1, no verdict at all.

`some _, x in v` inside a comprehension
(`oracles/rego-cfn/caller-identity-arn-as-principal/policy.rego:56`,
`oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego:460`):

```rego
_vals(v) := [x | some _, x in v] if is_object(v)
# opa: works. regorus: error: statements not scheduled in query {query:?}
```

A comprehension in an `else :=` value head
(`oracles/rego/s3-notification-authoritative-singleton/policy.rego:2367`):

```rego
_labels(p) := ["empty"] if {
	count(p) == 0
} else := [x | some x in p]
# opa: works. regorus: error: statements not scheduled in query {query:?}
```

A plain comprehension in a function head, and an `else :=` with a scalar head,
both work — it is the combination that fails. This class hits
`caller-identity-arn-as-principal/awscdk/reference` itself, so the **correct**
solution would be un-gradeable, not merely mis-graded.

### 4.3 Builtin-error strictness defaults are opposite — 8 pairs

`opa eval` treats a builtin error as undefined unless `--strict-builtin-errors`;
regorus does the reverse unless `-n`. The corpus relies on OPA's default —
`json.unmarshal(object.get(bp, ["values","policy"], "null"))` deliberately
yields `null`, and the `object.get(null, …)` that follows is expected to make
one comprehension branch undefined rather than abort:

```rego
package repro
import rego.v1

deny contains msg if {
	doc := json.unmarshal("null")
	some stmt in object.get(doc, "Statement", [])
	msg := sprintf("%v", [stmt])
}
```

| engine | exit | stdout |
|---|---|---|
| `opa eval` | 0 | `[]` |
| `opa eval --strict-builtin-errors` | 2 | *(stderr `eval_type_error: object.get: operand 1 must be object but got null`)* |
| `regorus eval` | 1 | *(stderr `error: \`object.get\` expects object argument. Got \`null\` instead`)* |
| `regorus eval -n` | 0 | `[]` |

`-n` fixes 4 of these 8 outright; the other 4 (`caller-identity-arn-as-principal`
on both TF arms) then fall into §4.1 and still lose a message.

### 4.4 Net effect of running regorus with `-n`

| outcome | pairs |
|---|---|
| agrees with OPA | 458 |
| exit 1, no verdict (§4.2) | 12 |
| exit 0, deny set emptied — **false PASS** (§4.1) | 22 |
| exit 0, deny messages lost, verdict unchanged | 12 |

## 5. Exit-code and output semantics observed

| situation | `opa eval -f raw -I` | `regorus eval` |
|---|---|---|
| rule defined, set non-empty | 0, JSON array | 0, `{"result":[{"expressions":[{"value":…}]}]}` |
| rule defined, set empty | 0, `[]` | 0, envelope with `"value": []` |
| **rule does not exist** | 0, **no output at all** | 0, **`{}`** |
| policy file missing | 2 | 1 |
| policy has a syntax error | 2, `rego_parse_error: unexpected eof token` | 1, caret-annotated `error: expecting expression` |
| query does not parse | 2 | 1 |
| input file missing / unparseable | 0 (unparseable stdin is accepted) | 1 |
| builtin error | 0 (undefined) — 2 with `--strict-builtin-errors` | 1 — 0 with `-n` |

Two consequences for the generated `static_tiers.sh` beyond the divergences:

* **Every exit code differs.** OPA uses 2 for "the verifier's own tooling is
  broken"; regorus uses 1 for that *and* for "your policy hit a builtin error".
  A drop-in swap loses the ability to tell an oracle defect from a policy
  verdict, which the `hcl_traversal` arm's explicit `opa eval ABORTED instead of
  returning a verdict` branch exists to distinguish.
* **The undefined-query output differs**, and the generator's `not_verifiable`
  branch is built on OPA's behaviour: it captures the output first *because*
  `opa eval` on a policy with no `not_verifiable` rule prints nothing rather than
  `[]`. regorus prints `{}` there. `jq -e 'length > 0'` on `{}` is false, so the
  marker still is not written — but by luck, not by design. More bluntly, the
  `deny` branch's `| jq -e 'length == 0'` reads the whole envelope: on a defined
  result `{"result":[…]}` has length 1, so a naive swap would report
  `tier1_status=FAIL` on **every** scenario. Any migration rewrites this shell.

## 6. `--coverage`

regorus's line coverage works on this corpus and is genuinely useful; `opa eval`
has no equivalent. On `ecs-swappiness`'s reference solution:

```sh
regorus eval -d oracles/rego/ecs-swappiness/policy.rego \
  -i ecs-swappiness__hcl-raw__reference.json --coverage \
  data.cdktn_bench.ecs_swappiness.deny
```

prints the verdict envelope, then `COVERAGE REPORT:` — the whole policy source,
ANSI-green for executed lines and red for un-executed ones. 11 lines covered,
4 not: exactly the body of `deny` (lines 73–80), which is the correct answer for
a reference solution that must not be denied. That is the signal a "does this
fixture actually exercise the rule it claims to falsify" gate would want, and it
is the one clear capability OPA does not have. It was also collected for
`rego-cfn` (`apigwv2-route-settings-zero-vs-unset`) and for the `hcl_traversal`
family (`s3-notification-authoritative-singleton`, 2 700-line policy plus
library) — both produce a full report with no error.

## 7. Timing

Per-eval wall time measured inside the container, `date +%s%N` around each
invocation, 504 evaluations each (process start included, since that is what the
verifier pays):

| | opa 1.19.0 | regorus 0.12.0 |
|---|---|---|
| total | 5 374 ms | 1 112 ms |
| median | 7 ms | 1 ms |
| mean | 10.7 ms | 2.2 ms |
| max | 29 ms | 10 ms |
| median on the 2 700-line `s3-notification` policy | 27 ms | 4 ms |

regorus is ~5–7× faster per evaluation and 7.6× smaller. Both are irrelevant next
to the rest of a trial: tier 1 is two evaluations against a `terraform plan` that
takes 25–35 s. The saving is ~10 ms per graded row.

## 8. What was not covered

* **9 broken fixtures produce no tier-1 artifact at all** — `terraform plan` or
  `cdk synth` rejects them first, which is the catch working as designed at tier
  0. They are excluded because there is nothing for either engine to read:
  `asg-launch-template-tag-propagation` (`provider-default-tags-instead` hcl-raw,
  `tags-only-on-the-asg-resource` hcl-raw + terraconstructs),
  `ddb-gsi-attribute-definitions` (`attribute-definitions-include-non-key-attributes`
  hcl-raw, `gsi-key-attribute-not-declared` hcl-raw,
  `include-projection-without-non-key-attributes` terraconstructs + awscdk),
  `s3-lambda-log-retention` (`log-retention-not-a-valid-enum-value` hcl-raw +
  terraconstructs).
* **cfn-guard arms** (no longer reachable — Amendment 45 retired the engine). Scenarios whose awscdk tier 1 was `cfn_guard` had no Rego
  policy for that arm and are out of scope by construction, as the memo says.
* **`rego_hints`, `opa test` unit tests, and any policy path not reachable from
  the two graded queries.** Only `deny` and `not_verifiable` were compared,
  because those are the only two the verifier evaluates.
* **The `hcl2json` + locals-aggregation shell itself.** As the memo scopes it:
  the merged document was reproduced by the generated code and fed to both
  engines, but no Rust replacement for that shell was attempted.
* **linux/amd64.** Everything was built and run on `linux/arm64`. The opa amd64
  hash is carried in the Dockerfile but never exercised.
* **One host, one run, no repeats.** The timings are single-shot medians over
  504 evaluations, not a benchmark with warm-up and repetition.

## 9. Recommendation

The memo's decision rule is explicit: zero divergences across all policies and
their fixtures is the condition for a DRAFT amendment, and any divergence is a
finding written up in `docs/` with the verifier staying on OPA 1.19.0. There are
50, in three independent classes, and the worst class is silent: run with `-n`
(the flag needed to match OPA's builtin-error default at all) and 22 pairs turn
an artifact the oracle rejects today into one it accepts, across six scenarios —
a reward flip from 0.0 to 1.0 on checked-in falsifiability fixtures, invisible
without this diff. So: **stay on OPA 1.19.0, no amendment.** The finding is not
that regorus is unusable — it is fast, small, its coverage report is a capability
this repo has wanted, and 454 of 504 pairs agree exactly — but that the corpus
uses three things it does not implement, and that its CLI's exit codes and
default strictness differ from the ones the generated verifier is written
against. If M10 is revisited, the cheap half is ours: `%q` is one `sprintf`
verb away from `%v`-plus-quotes and could be linted out of the policy corpus,
and the two scheduler constructs have mechanical rewrites (`some _, x in v` →
`x := v[_]`, comprehension-in-`else` → a named helper rule). That would leave
only the strictness default and the exit-code semantics, both of which are shell
changes in `generator/gen.py`. Re-run `scripts/spike/run_comparison.py` after
any such change; the harness is the deliverable that makes the second attempt
cheap.

## Appendix — every pair

252 fixtures, each row two pairs (`deny` and `not_verifiable`). `cause` names
the section above that explains the divergence.

| pair (spec / arm / fixture) | deny | not_verifiable | cause |
|---|---|---|---|
| acm-dns-validation-record-wiring/hcl-raw/reference | PASS | PASS |  |
| acm-dns-validation-record-wiring/hcl-raw/broken/email-validation-instead | PASS | PASS |  |
| acm-dns-validation-record-wiring/hcl-raw/broken/missing-certificate-validation-resource | PASS | PASS |  |
| acm-dns-validation-record-wiring/hcl-raw/broken/no-validation-records-at-all | PASS | PASS |  |
| acm-dns-validation-record-wiring/hcl-raw/broken/one-record-for-two-domains | PASS | PASS |  |
| acm-dns-validation-record-wiring/terraconstructs/reference | PASS | PASS |  |
| acm-dns-validation-record-wiring/terraconstructs/broken/email-validation-instead | PASS | PASS |  |
| acm-dns-validation-record-wiring/terraconstructs/broken/missing-certificate-validation-resource | PASS | PASS |  |
| acm-dns-validation-record-wiring/terraconstructs/broken/no-validation-records-at-all | PASS | PASS |  |
| acm-dns-validation-record-wiring/terraconstructs/broken/one-record-for-two-domains | PASS | PASS |  |
| apigw-openapi/hcl-raw/reference | PASS | PASS |  |
| apigw-openapi/hcl-raw/broken/deployment-missing-integration-dependency | PASS | PASS |  |
| apigw-openapi/hcl-raw/broken/route-count-wrong | PASS | PASS |  |
| apigw-openapi/terraconstructs/reference | PASS | PASS |  |
| apigw-openapi/terraconstructs/broken/deployment-missing-integration-dependency | PASS | PASS |  |
| apigw-openapi/terraconstructs/broken/route-count-wrong | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/hcl-raw/reference | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/hcl-raw/broken/burst-limit-left-unset | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/hcl-raw/broken/integration-targets-a-function-outside-this-plan | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/hcl-raw/broken/settings-on-the-wrong-stage | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/hcl-raw/broken/throttle-set-to-zero | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/awscdk/reference | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/awscdk/broken/burst-limit-left-unset | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/awscdk/broken/integration-targets-a-function-outside-this-plan | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/awscdk/broken/settings-on-the-wrong-stage | PASS | PASS |  |
| apigwv2-route-settings-zero-vs-unset/awscdk/broken/throttle-set-to-zero | PASS | PASS |  |
| asg-launch-template-tag-propagation/hcl-raw/reference | PASS | PASS |  |
| asg-launch-template-tag-propagation/hcl-raw/broken/instance-tags-but-no-volume-tags | PASS | PASS |  |
| asg-launch-template-tag-propagation/hcl-raw/broken/instances-never-tagged | PASS | PASS |  |
| asg-launch-template-tag-propagation/terraconstructs/reference | PASS | PASS |  |
| asg-launch-template-tag-propagation/terraconstructs/broken/instance-tags-but-no-volume-tags | PASS | PASS |  |
| asg-launch-template-tag-propagation/terraconstructs/broken/instances-never-tagged | PASS | PASS |  |
| caller-identity-arn-as-principal/hcl-raw/reference | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/hcl-raw/broken/account-root-principal-over-grant | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/hcl-raw/broken/principal-hardcoded-to-a-foreign-arn | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/hcl-raw/broken/sts-session-arn-as-principal | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/terraconstructs/reference | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/terraconstructs/broken/account-root-principal-over-grant | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/terraconstructs/broken/principal-hardcoded-to-a-foreign-arn | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/terraconstructs/broken/sts-session-arn-as-principal | **DIVERGE** | PASS | strict-builtin |
| caller-identity-arn-as-principal/awscdk/reference | **DIVERGE** | PASS | not-scheduled |
| caller-identity-arn-as-principal/awscdk/broken/account-root-principal-over-grant | **DIVERGE** | PASS | not-scheduled |
| caller-identity-arn-as-principal/awscdk/broken/principal-hardcoded-to-a-foreign-arn | **DIVERGE** | PASS | not-scheduled |
| ddb-gsi-attribute-definitions/hcl-raw/reference | PASS | PASS |  |
| ddb-gsi-attribute-definitions/hcl-raw/broken/attribute-definitions-include-an-unrequested-key | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/hcl-raw/broken/gsi-missing-entirely | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/hcl-raw/broken/gsi-projection-type-is-keys-only-not-include | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/hcl-raw/broken/include-projection-without-non-key-attributes | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/terraconstructs/reference | PASS | PASS |  |
| ddb-gsi-attribute-definitions/terraconstructs/broken/attribute-definitions-include-an-unrequested-key | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/terraconstructs/broken/gsi-missing-entirely | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/terraconstructs/broken/gsi-projection-type-is-keys-only-not-include | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/awscdk/reference | PASS | PASS |  |
| ddb-gsi-attribute-definitions/awscdk/broken/attribute-definitions-include-an-unrequested-key | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/awscdk/broken/attribute-definitions-include-non-key-attributes | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/awscdk/broken/gsi-key-attribute-not-declared | **DIVERGE** | PASS | sprintf-verb |
| ddb-gsi-attribute-definitions/awscdk/broken/gsi-missing-entirely | PASS | PASS |  |
| ddb-gsi-attribute-definitions/awscdk/broken/gsi-projection-type-is-keys-only-not-include | PASS | PASS |  |
| ecr-repo-destroy-force-delete/hcl-raw/reference | PASS | PASS |  |
| ecr-repo-destroy-force-delete/hcl-raw/broken/lifecycle-policy-keeps-wrong-count | PASS | PASS |  |
| ecr-repo-destroy-force-delete/hcl-raw/broken/repository-not-emptied-on-delete | PASS | PASS |  |
| ecr-repo-destroy-force-delete/terraconstructs/reference | PASS | PASS |  |
| ecr-repo-destroy-force-delete/terraconstructs/broken/lifecycle-policy-keeps-wrong-count | PASS | PASS |  |
| ecr-repo-destroy-force-delete/terraconstructs/broken/repository-not-emptied-on-delete | PASS | PASS |  |
| ecs-swappiness/hcl-raw/reference | PASS | PASS |  |
| ecs-swappiness/hcl-raw/broken/swappiness-nested-attribute | PASS | PASS |  |
| ecs-swappiness/hcl-raw/broken/swappiness-requires-maxswap | **DIVERGE** | PASS | sprintf-verb |
| ecs-swappiness/terraconstructs/reference | PASS | PASS |  |
| ecs-swappiness/terraconstructs/broken/swappiness-nested-attribute | PASS | PASS |  |
| ecs-swappiness/terraconstructs/broken/swappiness-requires-maxswap | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/reference | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/account-exclusive-policy-attachment | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/cartesian-metrics-on-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/cartesian-s3-on-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/deprecated-exclusive-role-attribute | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/foreach-roles-metrics-on-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/policy-attached-to-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/role-scoped-exclusive-attachment | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/s3-readonly-missing-on-one-role | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/hcl-raw/broken/trust-principals-not-split-across-both-roles | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/terraconstructs/reference | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/terraconstructs/broken/metrics-policy-on-one-role-from-both-sides | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/terraconstructs/broken/policy-attached-to-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/terraconstructs/broken/s3-readonly-missing-on-one-role | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/terraconstructs/broken/trust-principals-not-split-across-both-roles | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/reference | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/both-roles-trust-ecs-tasks-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/both-roles-trust-lambda-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/metrics-policy-on-one-role-from-both-sides | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/no-team-metrics-policy | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/policy-attached-to-one-role-only | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/s3-readonly-missing-on-one-role | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/single-role-for-both-workloads | PASS | PASS |  |
| iam-managed-policy-exclusive-vs-attachment/awscdk/broken/trust-principals-not-split-across-both-roles | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/hcl-raw/reference | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/hcl-raw/broken/alias-removed-instead-of-repointed | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/hcl-raw/broken/alias-still-serves-the-previous-version | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/hcl-raw/broken/seed-unchanged | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/terraconstructs/reference | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/terraconstructs/broken/alias-removed-instead-of-repointed | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/terraconstructs/broken/alias-still-serves-the-previous-version | PASS | PASS |  |
| lambda-alias-tracks-unpublished-latest/terraconstructs/broken/seed-unchanged | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/hcl-raw/reference | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/hcl-raw/broken/log-group-left-implicit | **DIVERGE** | PASS | sprintf-verb |
| lambda-log-group-ownership-and-retention/hcl-raw/broken/log-group-name-diverges-from-function | **DIVERGE** | PASS | sprintf-verb |
| lambda-log-group-ownership-and-retention/hcl-raw/broken/log-group-retained-on-delete | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/hcl-raw/broken/retention-left-at-the-construct-default | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/terraconstructs/reference | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/terraconstructs/broken/log-group-left-implicit | **DIVERGE** | PASS | sprintf-verb |
| lambda-log-group-ownership-and-retention/terraconstructs/broken/log-group-name-diverges-from-function | **DIVERGE** | PASS | sprintf-verb |
| lambda-log-group-ownership-and-retention/terraconstructs/broken/log-group-retained-on-delete | PASS | PASS |  |
| lambda-log-group-ownership-and-retention/terraconstructs/broken/retention-left-at-the-construct-default | PASS | PASS |  |
| named-resource-replacement/hcl-raw/reference | PASS | PASS |  |
| named-resource-replacement/hcl-raw/broken/ingress-widened-to-the-internet | PASS | PASS |  |
| named-resource-replacement/hcl-raw/broken/rename-replaces-an-in-use-security-group | PASS | PASS |  |
| named-resource-replacement/hcl-raw/broken/seed-unchanged | PASS | PASS |  |
| named-resource-replacement/terraconstructs/reference | PASS | PASS |  |
| named-resource-replacement/terraconstructs/broken/ingress-widened-to-the-internet | PASS | PASS |  |
| named-resource-replacement/terraconstructs/broken/rename-replaces-an-in-use-security-group | PASS | PASS |  |
| named-resource-replacement/terraconstructs/broken/seed-unchanged | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/reference | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/broken/access-logging-turned-off-instead-of-migrated | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/broken/acls-left-enabled-on-the-destination-bucket | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/broken/log-delivery-grant-missing-entirely | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/broken/log-delivery-grant-not-migrated | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/hcl-raw/broken/seed-unchanged | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/reference | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/broken/access-logging-turned-off-instead-of-migrated | PASS | PASS |  |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/broken/acls-left-enabled-on-the-destination-bucket | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/broken/log-delivery-grant-missing-entirely | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/broken/log-delivery-grant-not-migrated | **DIVERGE** | PASS | sprintf-verb |
| s3-acl-vs-object-ownership-log-delivery/terraconstructs/broken/seed-unchanged | **DIVERGE** | PASS | sprintf-verb |
| s3-bucket-hardening-decomposition/hcl-raw/reference | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/bpa-partially-set | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/kms-key-not-referenced | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/sse-left-at-s3-managed | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/subresource-omitted | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/subresource-targets-wrong-bucket | PASS | PASS |  |
| s3-bucket-hardening-decomposition/hcl-raw/broken/tls-policy-misses-object-arn | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/reference | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/bpa-partially-set | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/kms-key-not-referenced | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/sse-left-at-s3-managed | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/subresource-omitted | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/subresource-targets-wrong-bucket | PASS | PASS |  |
| s3-bucket-hardening-decomposition/terraconstructs/broken/tls-policy-misses-object-arn | PASS | PASS |  |
| s3-lambda-log-retention/hcl-raw/reference | PASS | PASS |  |
| s3-lambda-log-retention/hcl-raw/broken/s3-lambda-invoke-permission-scoped | PASS | PASS |  |
| s3-lambda-log-retention/terraconstructs/reference | PASS | PASS |  |
| s3-lambda-log-retention/terraconstructs/broken/s3-lambda-invoke-permission-scoped | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/reference | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/all-wiring-hidden-inside-a-module | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/audit-topic-wired-but-only-a-decoy-topic-carries-a-policy | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/audit-topic-wired-only-to-lifecycle-expiration | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/iam-policy-document-source-arn-ored-with-a-wildcard | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/inline-sns-topic-policy-bucket-named-only-in-the-sid | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/inline-sns-topic-policy-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/inline-sns-topic-policy-source-arn-ored-with-a-wildcard | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-decoy-bucket-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-decoy-bucket-directly | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-decoy-bucket-with-a-literal-notification-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-decoy-for-each-instance | **DIVERGE** | PASS | sprintf-verb |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-different-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-laundered-literal | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-a-second-symbol-holding-the-lambda-arn | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-5-hop-chain | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-dotted-key-local | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-topic-arn-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-topic-arn-direct-policy-attach | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-to-the-topic-arn-with-an-inline-topic-policy | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/lambda-permission-scoped-via-an-interpolated-literal | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/no-lambda-permission-at-all | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/notification-bucket-argument-resolves-to-no-bucket | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/only-one-of-the-two-events-wired | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/second-lambda-permission-scoped-to-the-topic | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-publish-not-permitted | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-conditional-topic-arn | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-decoy-topic-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-decoy-topic-directly | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-decoy-topic-with-an-opaque-notification-topic-arn | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-different-topic | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-attached-to-a-lambda-arn-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-bucket-named-only-in-the-sid | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-source-arn-ored-with-a-decoy-bucket | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-source-arn-ored-with-a-wildcard | **DIVERGE** | PASS | not-scheduled |
| s3-notification-authoritative-singleton/hcl-raw/broken/sns-topic-policy-unscoped-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/tf-json-source-arn-laundered-through-an-object-spelled-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/topic-policy-document-not-readable | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/topic-policy-granting-only-a-non-s3-principal | PASS | PASS |  |
| s3-notification-authoritative-singleton/hcl-raw/broken/two-notification-resources-for-one-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/reference | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/audit-topic-wired-only-to-lifecycle-expiration | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/lambda-permission-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/lambda-permission-scoped-to-a-different-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/only-one-of-the-two-events-wired | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/sns-publish-not-permitted | PASS | PASS |  |
| s3-notification-authoritative-singleton/terraconstructs/broken/sns-topic-policy-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/reference | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/audit-topic-wired-only-to-lifecycle-expiration | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/hand-authored-topic-policy-attached-to-a-decoy-topic | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/hand-authored-topic-policy-attached-to-a-different-topic | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/hand-authored-topic-policy-bucket-named-only-in-the-sid | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/hand-authored-topic-policy-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-scoped-to-a-decoy-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-scoped-to-a-different-bucket | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-scoped-to-the-topic-arn-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/lambda-permission-scoped-via-an-interpolated-literal | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/no-lambda-permission-at-all | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/only-one-of-the-two-events-wired | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/second-lambda-permission-scoped-to-the-topic | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/sns-topic-policy-attached-to-a-lambda-arn-behind-a-local | PASS | PASS |  |
| s3-notification-authoritative-singleton/awscdk/broken/topic-policy-source-arn-ored-with-a-wildcard | **DIVERGE** | PASS | not-scheduled |
| s3-notification-custom-resource-tax/hcl-raw/reference | PASS | PASS |  |
| s3-notification-custom-resource-tax/hcl-raw/broken/notification-permission-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-custom-resource-tax/hcl-raw/broken/notification-targets-the-wrong-function | PASS | PASS |  |
| s3-notification-custom-resource-tax/terraconstructs/reference | PASS | PASS |  |
| s3-notification-custom-resource-tax/terraconstructs/broken/notification-permission-not-scoped-to-bucket | PASS | PASS |  |
| s3-notification-custom-resource-tax/terraconstructs/broken/notification-targets-the-wrong-function | PASS | PASS |  |
| sfn-jsonata/hcl-raw/reference | PASS | PASS |  |
| sfn-jsonata/hcl-raw/broken/jsonata-expression-correctness | PASS | PASS |  |
| sfn-jsonata/hcl-raw/broken/mode-mixing-jsonpath-artifacts | **DIVERGE** | PASS | sprintf-verb |
| sfn-jsonata/hcl-raw/broken/raw-jsonpath-literal-value-only | PASS | PASS |  |
| singleton-child-resource-clobber/hcl-raw/reference | PASS | PASS |  |
| singleton-child-resource-clobber/hcl-raw/broken/existing-log-expiry-rule-dropped | PASS | PASS |  |
| singleton-child-resource-clobber/hcl-raw/broken/exports-rule-added-as-a-second-child-resource | PASS | PASS |  |
| singleton-child-resource-clobber/hcl-raw/broken/exports-rule-added-but-not-enabled | **DIVERGE** | PASS | sprintf-verb |
| singleton-child-resource-clobber/hcl-raw/broken/seed-unchanged | PASS | PASS |  |
| singleton-child-resource-clobber/terraconstructs/reference | PASS | PASS |  |
| singleton-child-resource-clobber/terraconstructs/broken/existing-log-expiry-rule-dropped | PASS | PASS |  |
| singleton-child-resource-clobber/terraconstructs/broken/exports-rule-added-but-not-enabled | **DIVERGE** | PASS | sprintf-verb |
| singleton-child-resource-clobber/terraconstructs/broken/seed-unchanged | PASS | PASS |  |
| toy-ssm-parameter/hcl-raw/reference | PASS | PASS |  |
| toy-ssm-parameter/hcl-raw/broken/parameter-tier-enum | PASS | PASS |  |
| toy-ssm-parameter/hcl-raw/broken/policy-scoped-to-parameter | **DIVERGE** | PASS | sprintf-verb |
| toy-ssm-parameter/hcl-raw/broken/policy-scoped-to-parameter-alt-shape | **DIVERGE** | PASS | sprintf-verb |
| toy-ssm-parameter/terraconstructs/reference | PASS | PASS |  |
| toy-ssm-parameter/terraconstructs/broken/parameter-tier-enum | PASS | PASS |  |
| toy-ssm-parameter/terraconstructs/broken/policy-scoped-to-parameter | **DIVERGE** | PASS | sprintf-verb |
| toy-ssm-parameter/terraconstructs/broken/policy-scoped-to-parameter-alt-shape | **DIVERGE** | PASS | sprintf-verb |
| apigw-redeploy/hcl-raw/reference | PASS | PASS |  |
| apigw-redeploy/hcl-raw/broken/deployment-missing-integration-dependency | PASS | PASS |  |
| apigw-redeploy/hcl-raw/broken/stale-deployment-no-triggers | PASS | PASS |  |
| apigw-redeploy/hcl-raw/broken/triggers-incomplete-hash | PASS | PASS |  |
| apigw-redeploy/hcl-raw/steps/01-initial-deploy/reference | PASS | PASS |  |
| apigw-redeploy/terraconstructs/reference | PASS | PASS |  |
| apigw-redeploy/terraconstructs/broken/deployment-missing-integration-dependency | PASS | PASS |  |
| apigw-redeploy/terraconstructs/steps/01-initial-deploy/reference | PASS | PASS |  |
