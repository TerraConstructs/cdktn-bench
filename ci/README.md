# ci

Oracle-equivalence CI (build plan Phase 1 / §3 of the pre-registration): runs both
oracle tiers (`../oracles/rego`, `../oracles/cfn-guard`) against all three arms'
reference solutions on every commit.

**What this actually proves today (2026-08-06, corrected -- the previous version
of this paragraph claimed a stronger, unbacked guarantee):** `falsifiability`
(`make falsifiability`) proves a tier-1 structural_assert is real ONLY if some
`solution/broken/<catch-name>/` fixture happens to violate it -- a scenario can
declare more tier-1 asserts than it has catches predicting a tier-1 catch,
leaving the rest with ZERO covering negative fixture and free to be silently
gutted (demonstrated directly: editing
`oracles/rego/apigw-openapi/policy.rego`'s `route_count_correct` denial to an
always-false clause changed no `make falsifiability`/`make grading-proof`
verdict at all, until this same fix added a covering `route-count-wrong`
catch). `generator/check_tier1_coverage.py` (`make tier1-coverage`, wired into
`make ci`) is a real, mechanical, NUMERIC floor for this -- for each enabled
arm, `count(catches predicting a tier-1 catch) >= count(tier-1 structural_asserts)`
-- but it is a coarse proxy (pigeonhole), not a true per-assert mapping. As of
this fix: `apigw-openapi` and `s3-lambda-log-retention` meet the floor on every
arm; `ecs-swappiness`, `sfn-jsonata`, and `specs/_toy/toy-ssm-parameter.yaml` do
**not** yet (tracked, pre-existing gaps -- closing them needs additional
hand-verified negative fixtures per scenario, the same work `route-count-wrong`
required for apigw-openapi). A tracked gap that stays at or below its recorded
`_KNOWN_UNCOVERED_GAP` baseline is a non-gating **SKIP** (rc=3), so `make ci`
stays green while the gap stays visible in the summary table rather than
silently invisible; a gap that gets WORSE than its baseline (or shows up on a
spec/arm with no baseline entry at all) is a gating **FAIL** (rc=1) instead --
this is what actually distinguishes "this specific run introduced new drift"
from "this scenario has a pre-existing, tracked authoring gap" mechanically,
not just in prose (2026-08-06 round 2 fix, closing the "the numeric floor is
non-gating precisely where the demonstrated attack landed, so it cannot detect
the break there" gap).

Separately, CORRECTED (2026-08-06 round 2): a numeric pigeonhole floor being
met (`count(catches) >= count(asserts)`) does not by itself prove every
individual tier-1 rule is independently falsifiable -- TWO catches can
incidentally both violate the SAME rule while a third rule goes completely
untouched. This was demonstrated directly for real: `sfn-jsonata`'s only two
awscdk/hcl_raw fixtures reaching `no_raw_jsonpath_string_literal`
(`.../mode-mixing-jsonpath-artifacts[-raw-constructor-escape-hatch]/`) both
also independently trip the SIX-key-alternation `no_jsonpath_mode_keys` rule
at the same time (their raw JSONPath literal is ALSO a banned key's value),
so silently gutting `no_raw_jsonpath_string_literal` alone changed no
`falsifiability`/`grading-proof` verdict -- confirmed by hand (replacing its
cfn-guard condition with an always-true regex left every existing fixture's
PASS/FAIL bit-identical). Fixed by adding
`solution/broken/raw-jsonpath-literal-value-only/` (an extra, non-catch-named
fixture, same convention as the escape-hatch fixture) on BOTH arms: a raw
`"$."`-prefixed literal used as an ASL state's `Output` VALUE with NO banned
key present anywhere, isolating that one rule -- verified the same sabotage
now flips `make falsifiability` to FAIL for `sfn-jsonata`. The general
version of this gap (an uncovered-in-ISOLATION rule elsewhere, on this or
another scenario) is not fully closed -- there is still no true differential
check that runs both oracle bundles over a shared corpus of artifacts and
fails on verdict disagreement, which would catch it structurally rather than
fixture-by-fixture -- a scenario whose two bundles diverge in strictness in a
way that happens to be covered by existing catches on both sides is not yet
caught by anything in this repo.

Also home to negative tests (a deliberately broken reference solution per planted
catch must score 0 at the predicted tier — build plan Phase 2 exit criterion) and any
repo-level lint/format checks (mirroring `aws-bench-datasets`'s `make ready` pattern:
build + test + schema checks).

## `make ci` (Slice E)

`run-ci.sh` is the driver behind `make ci` (`../mk/ci.mk`): for every real spec under
`../specs/*.yaml` it runs gen-sync (`make gen` must reproduce, byte-for-byte, the
state every touched path was in immediately before that run — a before/after
snapshot diff, NOT a git comparison, see `gen_sync_check`'s own docstring),
`check-paths`, `tier1-coverage`, `falsifiability`, and `grading-proof`;
`../specs/_toy/toy-ssm-parameter.yaml` runs a lighter gen-sync + check-paths +
tier1-coverage + falsifiability smoke check instead (it isn't a benchmark
scenario). Then, once: `make test-gates` and `make check`. Every check for every
scenario always runs — no early exit — and a PASS/FAIL/SKIP summary table prints
at the end (SKIP = rc=3, this repo's "not proven yet, non-gating" convention —
see `run_check`'s own docstring — never rendered as PASS). See `run-ci.sh`'s own
header comment for the full contract, including which half of the battery needs
docker (the provider-mirror-coverage sub-check, degrades to a warning without
it; `make preflight`, now a real gating step whenever docker is reachable)
versus the host terraform/node/npm/jq toolchain (everything else). A failed
`make build-arms` in the pre-flight step is now fatal (a real FAIL row), not a
swallowed stderr warning.

`check-smoke-drift.sh` (Slice A/D) is a narrower, standing guard — `tasks/anchor/smoke/`
must stay a byte-copy of `../arms/awscdk/environment/` — that `make check` (and
therefore `make ci`) runs on every invocation, independent of any per-spec loop.

`../.github/workflows/ci.yml` runs both `make check` (a docker-free `policy-only` job)
and `make ci` (a `full-ci` job with docker + the pinned terraform/opa/cfn-guard
toolchain) on every push/PR.
