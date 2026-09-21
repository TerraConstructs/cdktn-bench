#!/usr/bin/env bash
# prebuild-tasks.sh — build a run's task images before the run, serially, with
# the pinned build-time downloads served from the local asset mirror.
#
# WHY: a task's environment/Dockerfile embeds its arm's Dockerfile verbatim and
# re-fetches every pinned binary, and Harbor voids a trial whose compose build
# exceeds `build_timeout_sec` (600 s by default). GitHub's release CDN is
# slow-to-unusable from some networks for the 57 MB opa asset, so a cold task
# build can blow that budget.
#
# HOW: `docker build` of the task's own environment/ directory populates the
# local layer cache. The `cdktn-bench-prebuild/<task>:dev` tag exists only to
# keep the warmed layers referenced; nothing consumes the tag.
#
# These layers are the ones Harbor's own no-build-arg `docker compose build`
# reuses: nothing passes ASSET_MIRROR, so both builds hash the same RUN strings
# and hit the same cache. What the mirror has to be is LISTENING on the port
# the Dockerfiles probe -- scripts/asset-mirror-up.sh -- for the whole window.
#
# The mirror is a SOURCE, not an authority: each fetch still runs the sha256
# check hardcoded in the Dockerfile, so a mirrored file that does not match the
# pin fails the build exactly as a corrupted download does.
#
# Usage:
#   scripts/prebuild-tasks.sh <task-dir-basename> [...]
#   scripts/prebuild-tasks.sh -i <name> -i <name>        # a job's include list
#
# Env:
#   CDKTN_ASSET_MIRROR_URL  build against this mirror URL instead of the
#                           Dockerfile default. FORKS THE LAYER CACHE -- it is
#                           passed as a build arg, so Harbor's own build no
#                           longer matches. Only for a docker host where
#                           host.lima.internal does not resolve.
#   CDKTN_ASSET_DIR         asset directory (default ~/.cdktn-bench/assets)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -i|--include-task-name) TASKS+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) TASKS+=("$1"); shift ;;
  esac
done

if [ "${#TASKS[@]}" -eq 0 ]; then
  echo "usage: scripts/prebuild-tasks.sh <task-dir-basename> [...]" >&2
  exit 2
fi

MIRROR_PID="$(scripts/asset-mirror-up.sh)"
cleanup() {
  [ -n "$MIRROR_PID" ] && kill "$MIRROR_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Passing a build arg forks the cache key away from Harbor's no-arg build, so
# this stays empty unless the operator asked for a non-default mirror host.
MIRROR_ARG=()
if [ -n "${CDKTN_ASSET_MIRROR_URL:-}" ]; then
  MIRROR_ARG=(--build-arg "ASSET_MIRROR=$CDKTN_ASSET_MIRROR_URL")
  echo "==> ASSET_MIRROR=$CDKTN_ASSET_MIRROR_URL (build arg: Harbor's build will NOT reuse these layers)"
fi

status=0
for task in "${TASKS[@]}"; do
  env_dir=""
  for candidate in tasks/*/"$task"/environment; do
    [ -f "$candidate/Dockerfile" ] && env_dir="$candidate" && break
  done
  if [ -z "$env_dir" ]; then
    echo "==> ERROR: no tasks/*/$task/environment/Dockerfile" >&2
    status=1
    continue
  fi
  echo "==> prebuilding $task  (context: $env_dir)"
  started=$(date +%s)
  if docker build ${MIRROR_ARG[@]+"${MIRROR_ARG[@]}"} \
      -t "cdktn-bench-prebuild/$task:dev" -f "$env_dir/Dockerfile" "$env_dir"; then
    echo "==> $task built in $(( $(date +%s) - started ))s"
  else
    echo "==> ERROR: $task build failed" >&2
    status=1
  fi
done

exit "$status"
