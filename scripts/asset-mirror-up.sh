#!/usr/bin/env bash
# asset-mirror-up.sh -- make sure the build-time asset mirror is listening on
# the ONE port the arm Dockerfiles probe, and say who owns it.
#
# The Dockerfiles default `ARG ASSET_MIRROR` to http://host.lima.internal:8899
# and nobody overrides it, so the port is part of the image contract: a build
# either finds a server there or falls back to upstream. Everything that builds
# an image calls this first -- `make build-arms`, scripts/prebuild-tasks.sh,
# scripts/run-bench.sh -- so a prebuild and the harness's own no-build-arg
# `docker compose build` hash the same RUN strings and share one layer cache.
#
# Prints the PID of a server it started, or nothing when one was already
# listening. The caller owns what it started:
#
#   MIRROR_PID="$(scripts/asset-mirror-up.sh)"
#   trap '[ -n "$MIRROR_PID" ] && kill "$MIRROR_PID" 2>/dev/null' EXIT
#
# Output goes to stderr so the PID is the only thing on stdout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# One owner for the port: the Dockerfiles' ARG default and this server have to
# agree or the probe finds nothing.
PORT="${CDKTN_ASSET_MIRROR_PORT:-$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts'); import asset_mirror; print(asset_mirror.DEFAULT_MIRROR_PORT)")}"

if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  echo "==> asset mirror: already listening on 127.0.0.1:$PORT (left alone)" >&2
  exit 0
fi

log="$(mktemp -t cdktn-asset-mirror)"
PYTHONUNBUFFERED=1 python3 "$REPO_ROOT/scripts/asset_mirror.py" serve --port "$PORT" \
  > "$log" 2>&1 &
pid=$!

for _ in $(seq 1 50); do
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && break
  kill -0 "$pid" 2>/dev/null || { echo "asset mirror died:" >&2; cat "$log" >&2; exit 1; }
  sleep 0.2
done
if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  echo "asset mirror never came up on $PORT:" >&2
  cat "$log" >&2
  kill "$pid" 2>/dev/null || true
  exit 1
fi

echo "==> asset mirror: serving on 127.0.0.1:$PORT (pid $pid)" >&2
echo "$pid"
