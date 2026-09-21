#!/usr/bin/env bash
# Driver for `make ci` (mk/ci.mk holds the contract; this is the
# implementation). Full battery, per check and per spec: docs/generator.md
# "make ci battery".
#
# For every spec under specs/*.yaml: gen-sync, check-paths, seed-parity,
# tier1-coverage, falsifiability, grading-proof. specs/_toy/toy-ssm-parameter
# is not a benchmark scenario and runs a lighter smoke set. Then, once:
# `make test-gates` and `make check`.
#
# Every check runs for every scenario regardless of earlier failures, so one
# broken scenario never hides another's result; the summary table at the end is
# the report. Exit is non-zero iff anything FAILed — a SKIP row does not fail
# the run.
#
# Requires terraform, node, npm, jq, opa on PATH (plus hcl2json for a
# spec with `oracle.hcl_traversal: true`, whose absence is a hard TOOL_MISSING
# tier-1 failure, never a silent pass), and network the first time `npm ci` /
# `terraform init` populate their caches. Docker is optional: without it the
# image build and Gate 1 are skipped and the provider-mirror sub-check degrades
# to a warning. `make test-gates`/`make check` need none of it and always run.
set -uo pipefail
cd "$(dirname "$0")/.."

REPO_ROOT="$(pwd)"
TOY_SPEC="specs/_toy/toy-ssm-parameter.yaml"
ARMS=(awscdk hcl-raw terraconstructs)

# Every aws-bench scenario shard a task can live under, resolved once from
# generator/shards.toml (one name, "anchor", at shard_count = 1). gen_sync_check
# snapshots each spec's task dir on all of them.
SHARD_NAMES="$(uv run python -c "
import sys
sys.path.insert(0, 'generator')
import shards
print(' '.join(shards.shard_name(k) for k in range(shards.shard_count())))
")"

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
# rc=3 is SKIP, not PASS/FAIL: this repo's NOT_AUTHORED convention (see
# generator/check_reference_paths.py's docstring) for "non-gating because its
# prerequisite — a reference fixture, a hand-authored solve.sh — is not authored
# yet". SKIP never sets OVERALL=1 and is never rendered as PASS, so the summary
# table distinguishes "ran and proved something" from "not wired up yet".
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

# gen_sync_check <spec-path> -- runs `make gen` and requires that every path a
# spec's generation touches comes out byte-identical to how it stood immediately
# before generation ran.
#
# The comparison is snapshot-based (temp-dir copy + `diff -r`), never git-based,
# and must stay that way. `git status` reports nothing in a .git-less checkout
# (source tarball, `git archive`) and would make this check pass vacuously; it
# also reads a correct, regenerated-but-uncommitted file as permanent drift.
gen_sync_check() {
  local spec="$1" id
  id="$(basename "$spec" .yaml)"
  # Task dirs are enumerated over EVERY shard, never a hardcoded tasks/anchor:
  # generator/shards.py may place a spec's arms under tasks/anchor-1..N-1, and a
  # snapshot that misses a shard reports every task on it as untouched no matter
  # what `make gen` did. Covering all N shards is also what makes a task moving
  # between shards surface here as one GONE + one NEW path.
  local paths=()
  local arm shard
  for arm in awscdk hcl-raw terraconstructs; do
    for shard in $SHARD_NAMES; do
      paths+=("tasks/${shard}/${id}-${arm}")
    done
  done
  paths+=(
    "oracles/rego/${id}"
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
# satisfy every declared `workspace_seed.seed_asserts` entry. It reuses the rc=3
# convention so a greenfield spec (no workspace_seed) lands in run_check's SKIP
# branch instead of needing a second convention.
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
# Pre-flight: build arm images only if missing, and only if docker is reachable
# -- docker stays a graceful degrade, not a hard requirement, matching
# gates/oracle_falsifiability.py's own docker-optional contract.
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
    # FATAL, never a swallowed warning: a Dockerfile regression, bad pinned
    # digest or failed sha256 must be a real FAIL row that fails the run.
    run_check "(global)" "build-arms" -- make build-arms
  else
    echo "==> all arm images already present -- skipping docker build (per-scenario runtime stays toolchain-only)"
  fi
  # Gate 1 (gates/preflight.py / `make preflight`): proves each arm's toolchain
  # works INSIDE its own container, offline (--network none). This is its only
  # gating call site, and it requires the images built/verified just above.
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
  # specs/split.yaml is split metadata (generator/split.py's output), not a
  # scenario spec -- excluded the same way mk/gen.mk excludes specs/_toy/.
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
# check-paths is in the smoke set because toy-ssm-parameter is the only spec
# with generator/tests/fixtures/ authored: without this line the path-resolution
# check would run non-vacuously zero times in `make ci`.
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
