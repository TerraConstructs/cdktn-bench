#!/usr/bin/env bash
# ci/run-ci.sh -- driver for `make ci` (mk/ci.mk). See that file's own header
# comment for the contract; this script is the implementation.
#
# For EVERY spec under specs/*.yaml (the real, non-toy scenarios) this runs
# the full battery:
#   1. gen-sync   -- `make gen SPEC=...` must reproduce, byte-for-byte, the
#                     state every path that spec's generation touches was
#                     in immediately before this run (before/after snapshot
#                     diff -- see gen_sync_check's own docstring; NOT a git
#                     comparison) -- proves generated/ is not silently
#                     drifted from specs/.
#   2a. seed-parity    -- `make seed-parity SPEC=...` (BROWNFIELD only,
#                          specs/SCHEMA.md §2.7). PASS/FAIL for a spec with a
#                          `workspace_seed` block; SKIP (rc=3) for every
#                          greenfield spec, which is all of them but
#                          `named-resource-replacement`.
#   2. check-paths     -- `make check-paths SPEC=...`. Reports PASS/FAIL
#                          when the spec has a reference fixture authored
#                          (generator/tests/fixtures/<id>/), or SKIP
#                          (rc=3, non-gating) when none of its arms do yet
#                          -- see run_check's own SKIP handling below. As of
#                          2026-08-06 every real (non-toy) spec is still
#                          SKIP here (Slice D hasn't authored their
#                          reference fixtures) -- toy-ssm-parameter's own
#                          smoke run below is the only spec this actually
#                          proves anything for today.
#   3. falsifiability  -- `make falsifiability SPEC=...`
#   4. grading-proof   -- `make grading-proof SPEC=...`
# specs/_toy/toy-ssm-parameter.yaml is NOT a benchmark scenario (its own file
# header says so) and is deliberately run at a lighter SMOKE level instead
# (gen-sync + check-paths + falsifiability) -- it exists to keep the
# generator/gate pipeline itself exercised end-to-end without paying the
# full per-scenario battery for a fixture that isn't part of the benchmark;
# check-paths is included at this level specifically because toy is the
# only spec with a reference fixture authored, so it is the only place this
# check runs non-vacuously today.
#
# Then, once (not per-scenario): `make test-gates` and `make check`.
#
# Runs EVERY check for EVERY scenario regardless of earlier failures (no
# early exit) so one broken scenario never hides another's result -- see the
# summary table printed at the end. Exits non-zero iff anything failed (a
# SKIP row does not fail the run; see run_check's own docstring).
#
# Docker: used for two things now (2026-08-06 -- previously only the first):
#   - `falsifiability`/`grading-proof`'s own provider-mirror-coverage
#     sub-check (gates/oracle_falsifiability.py::_arm_mirror_provider_versions),
#     which degrades to a WARNING (not a failure) when docker/the image is
#     unavailable -- see that function's own docstring;
#   - `make preflight` (Gate 1 -- gates/preflight.py), run once, globally,
#     right after the image build/verify step below -- a REAL gating check
#     now (previously invoked by neither `make ci` nor ci.yml at all).
# This script does not rebuild arm images itself; it builds them once, up
# front, ONLY if `cdktn-bench/<arm>:dev` is missing AND docker is reachable
# (never on every scenario, and never if an image already exists -- keeps
# per-scenario runtime to the host-toolchain work alone: terraform/npm/tsc,
# which dominates either way). Unlike before, a failed `make build-arms` is
# now FATAL (a real FAIL row, not a swallowed stderr warning) -- see the
# pre-flight block below.
#
# Host-toolchain requirement (same as `make check-paths`/`make falsifiability`/
# `make grading-proof` individually): terraform, node, npm, jq on PATH, plus
# opa/cfn-guard for the tier-1 policy checks, plus -- for any spec that sets
# `oracle.hcl_traversal: true` (specs/SCHEMA.md §4.6) -- hcl2json, which the
# hcl_raw arm's generated tests/static_tiers.sh runs BEFORE `opa eval`. Its
# absence is deliberately a HARD tier-1 failure (TOOL_MISSING), not a silent
# pass, so a runner without it will report that scenario red rather than
# quietly grading it on partial information. Plus
# network the first time `npm ci`/`terraform init` populate their local
# caches. `make test-gates`/`make check` (pure Python + the schema/pytest
# suites) need none of that and always run.
set -uo pipefail
cd "$(dirname "$0")/.."

REPO_ROOT="$(pwd)"
TOY_SPEC="specs/_toy/toy-ssm-parameter.yaml"
ARMS=(awscdk hcl-raw terraconstructs)

# scenario -> check -> status, recorded in encounter order for the final table.
declare -a ROW_SCENARIO=()
declare -a ROW_CHECK=()
declare -a ROW_STATUS=()
OVERALL=0

record() {
  ROW_SCENARIO+=("$1")
  ROW_CHECK+=("$2")
  ROW_STATUS+=("$3")
}

# run_check <scenario-label> <check-label> -- <command...>
# Runs the command, prints PASS/FAIL loudly with a tail of output on
# failure, records the outcome, and (on failure) sets OVERALL=1 -- but never
# exits the script, so every remaining check/scenario still runs.
#
# A command that exits rc=3 is treated as SKIP, not PASS/FAIL: this repo's
# convention (see generator/check_reference_paths.py's own docstring) for
# "this check is non-gating because its prerequisite (a reference fixture,
# a hand-authored solve.sh, ...) hasn't been authored yet" -- exactly the
# NOT_AUTHORED verdict that used to print as an indistinguishable-from-real
# "PASS" in this table (benchmark-integrity finding, 2026-08-06:
# "`check-paths` is VACUOUS for every real scenario, yet `make ci` prints
# 'check-paths PASS' x4"). SKIP does not set OVERALL=1 (still non-gating),
# but is never rendered as PASS, so a reader of the summary table can tell
# "this actually ran and proved something" apart from "this hasn't been
# wired up yet" at a glance.
run_check() {
  local scenario="$1" check="$2"
  shift 2
  if [ "$1" = "--" ]; then shift; fi
  local out status rc
  echo ""
  echo "----> [$scenario] $check"
  out=$("$@" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    status="PASS"
    echo "<---- [$scenario] $check: PASS"
  elif [ "$rc" -eq 3 ]; then
    status="SKIP"
    echo "<---- [$scenario] $check: SKIP (rc=3 -- not authored yet, non-gating)"
    echo "----- last 40 lines of output -----"
    echo "$out" | tail -40
    echo "------------------------------------"
  else
    status="FAIL"
    OVERALL=1
    echo "<---- [$scenario] $check: FAIL (exit $rc)"
    echo "----- last 40 lines of output -----"
    echo "$out" | tail -40
    echo "------------------------------------"
  fi
  record "$scenario" "$check" "$status"
}

# gen_sync_check <spec-path> -- runs `make gen` and requires that every path
# a spec's generation touches comes out byte-identical to how it stood
# immediately before generation ran.
#
# Snapshot-based (temp-dir copy + `diff -r` before/after), NOT git-based.
# Fixes two related findings (2026-08-06):
#   (a) "gen-sync silently PASSES whenever git fails" -- the old
#       implementation was `diff="$(git status --porcelain ... 2>/dev/null)"`
#       with git's own exit status discarded entirely; in any .git-less
#       checkout (source tarball, `git archive`, a sparse/partial-clone
#       quirk) `git status` exits 128 with empty stdout and the check
#       reported PASS, proving nothing.
#   (b) "gen-sync FAILs on a legitimate uncommitted edit" -- comparing
#       against `git status` (tracked-vs-index state) means a correct,
#       already-regenerated-but-not-yet-committed file reads as "drift"
#       forever, even though `make gen` reproduces it byte-for-byte.
# Snapshotting the working tree immediately before generation and diffing
# against it immediately after sidesteps both: no git dependency (so no
# silently-ignored git failure is possible), and no false positive from a
# pre-existing uncommitted-but-correct edit (this run's own "before" state
# already reflects it).
gen_sync_check() {
  local spec="$1" id
  id="$(basename "$spec" .yaml)"
  local paths=(
    "tasks/anchor/${id}-awscdk"
    "tasks/anchor/${id}-hcl-raw"
    "tasks/anchor/${id}-terraconstructs"
    "oracles/rego/${id}"
    "oracles/cfn-guard/${id}"
    "oracles/rego-cfn/${id}"
    "oracles/${id}"
    "local-registry.json"
  )
  local snapshot p rc drift out
  snapshot="$(mktemp -d)"
  for p in "${paths[@]}"; do
    if [ -e "$p" ]; then
      mkdir -p "$snapshot/$(dirname "$p")"
      cp -R "$p" "$snapshot/$p"
    fi
  done

  uv run python generator/gen.py "$spec"
  rc=$?
  if [ "$rc" -ne 0 ]; then
    rm -rf "$snapshot"
    return 1
  fi

  drift=0
  for p in "${paths[@]}"; do
    if [ -e "$snapshot/$p" ] && [ -e "$p" ]; then
      if ! out="$(diff -r "$snapshot/$p" "$p" 2>&1)"; then
        echo "DRIFT: '$p' changed by 'make gen SPEC=$spec':" >&2
        echo "$out" >&2
        drift=1
      fi
    elif [ -e "$snapshot/$p" ] && [ ! -e "$p" ]; then
      echo "DRIFT: '$p' existed before 'make gen SPEC=$spec' and is now GONE" >&2
      drift=1
    elif [ ! -e "$snapshot/$p" ] && [ -e "$p" ]; then
      echo "DRIFT: '$p' is NEW after 'make gen SPEC=$spec' (did not exist before" >&2
      echo "  this run) -- if intentional (e.g. a newly-enabled arm), commit it." >&2
      drift=1
    fi
  done

  rm -rf "$snapshot"
  return "$drift"
}

check_paths_check() {
  uv run python generator/check_reference_paths.py "$1"
}

# BROWNFIELD seed parity (specs/SCHEMA.md §2.7, DECISIONS.md Amendment 28):
# every arm's generated, UN-OVERLAID workspace must build/synth/plan green and
# satisfy every declared `workspace_seed.seed_asserts` entry. rc=3 (this spec
# is greenfield, i.e. declares no workspace_seed) is handled by run_check's
# existing SKIP branch -- which is exactly why this check reuses that
# convention instead of inventing one.
seed_parity_check() {
  uv run python generator/check_reference_paths.py "$1" --seed
}

tier1_coverage_check() {
  uv run python generator/check_tier1_coverage.py "$1"
}

falsifiability_check() {
  uv run python gates/oracle_falsifiability.py "$1"
}

grading_proof_check() {
  uv run python gates/grading_proof.py "$1"
}

# ---------------------------------------------------------------------------
# Pre-flight: build arm images only if missing (never rebuild an existing
# one) and only if docker is reachable at all -- keeps this a graceful
# degrade, not a hard requirement, matching gates/oracle_falsifiability.py's
# own docker-optional contract.
# ---------------------------------------------------------------------------
echo "=== make ci: pre-flight ==="
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  missing=0
  for arm in "${ARMS[@]}"; do
    if ! docker image inspect "cdktn-bench/${arm}:dev" >/dev/null 2>&1; then
      missing=1
    fi
  done
  if [ "$missing" -eq 1 ]; then
    echo "==> some arm image(s) missing -- running 'make build-arms' once"
    # FATAL, not a swallowed warning (benchmark-integrity finding,
    # 2026-08-06: "full-ci cannot fail on a broken arm image" -- a
    # Dockerfile regression, bad pinned digest, or failed sha256 used to be
    # reduced to a stderr WARNING here and `make ci` continued green). A
    # broken build is recorded as a real FAIL row and fails the run.
    run_check "(global)" "build-arms" -- make build-arms
  else
    echo "==> all arm images already present -- skipping docker build (per-scenario runtime stays toolchain-only)"
  fi
  # Gate 1 (gates/preflight.py / `make preflight`): proves each arm's
  # toolchain actually works INSIDE its own container, offline
  # (--network none) -- the one docker-backed check this battery had no
  # gating call site for at all before this fix (same finding as above:
  # "`make preflight`... is invoked by neither `make ci` nor ci.yml").
  # Requires the images built/verified present just above.
  run_check "(global)" "preflight" -- make preflight
else
  echo "==> docker not available/reachable -- skipping image build entirely."
  echo "    falsifiability/grading-proof still run: their own provider-mirror-"
  echo "    coverage sub-check degrades to a WARNING without docker (see"
  echo "    gates/oracle_falsifiability.py::_arm_mirror_provider_versions),"
  echo "    everything else (schema/pytest/check-paths/oracle grading itself)"
  echo "    is unaffected -- this is the 'policy-only checks degrade gracefully'"
  echo "    mode .github/workflows/ci.yml documents."
fi

# ---------------------------------------------------------------------------
# Per-scenario battery.
# ---------------------------------------------------------------------------
for spec in specs/*.yaml; do
  [ -e "$spec" ] || continue
  # specs/split.yaml is split metadata (generator/split.py's own output),
  # not a scenario spec -- excluded the same way specs/_toy/ is excluded
  # from mk/gen.mk's gen-all/parity-all (see that file's own matching skip).
  [ "$(basename "$spec")" = "split.yaml" ] && continue
  id="$(basename "$spec" .yaml)"
  echo ""
  echo "=== scenario: $id ($spec) ==="
  run_check "$id" "gen-sync" -- gen_sync_check "$spec"
  run_check "$id" "check-paths" -- check_paths_check "$spec"
  run_check "$id" "seed-parity" -- seed_parity_check "$spec"
  run_check "$id" "tier1-coverage" -- tier1_coverage_check "$spec"
  run_check "$id" "falsifiability" -- falsifiability_check "$spec"
  run_check "$id" "grading-proof" -- grading_proof_check "$spec"
done

echo ""
echo "=== scenario: toy-ssm-parameter ($TOY_SPEC) [smoke] ==="
run_check "toy-ssm-parameter (smoke)" "gen-sync" -- gen_sync_check "$TOY_SPEC"
# toy-ssm-parameter is the ONLY spec with generator/tests/fixtures/
# authored today (benchmark-integrity finding, 2026-08-06: "the one spec
# that DOES have fixtures ... is run at 'smoke' level, which deliberately
# omits check-paths") -- included here so the G2 path-resolution check is
# exercised by `make ci` for real at least once, not zero times.
run_check "toy-ssm-parameter (smoke)" "check-paths" -- check_paths_check "$TOY_SPEC"
run_check "toy-ssm-parameter (smoke)" "tier1-coverage" -- tier1_coverage_check "$TOY_SPEC"
run_check "toy-ssm-parameter (smoke)" "falsifiability" -- falsifiability_check "$TOY_SPEC"

# ---------------------------------------------------------------------------
# Global (once, not per-scenario).
# ---------------------------------------------------------------------------
echo ""
echo "=== global checks ==="
run_check "(global)" "test-gates" -- make test-gates
run_check "(global)" "check" -- make check

# ---------------------------------------------------------------------------
# Summary table.
# ---------------------------------------------------------------------------
echo ""
echo "=============================== make ci summary ==============================="
printf "%-28s %-16s %s\n" "SCENARIO" "CHECK" "STATUS"
printf "%-28s %-16s %s\n" "--------" "-----" "------"
n="${#ROW_SCENARIO[@]}"
i=0
while [ "$i" -lt "$n" ]; do
  printf "%-28s %-16s %s\n" "${ROW_SCENARIO[$i]}" "${ROW_CHECK[$i]}" "${ROW_STATUS[$i]}"
  i=$((i + 1))
done
echo "=================================================================================="

if [ "$OVERALL" -eq 0 ]; then
  echo "make ci: ALL GREEN"
else
  echo "make ci: FAILED -- see FAIL rows above" >&2
fi
exit "$OVERALL"
