#!/usr/bin/env bash
# Guards the hand-maintained copy: tasks/anchor/smoke/environment must stay a
# byte-copy of arms/awscdk/environment (modulo each file's leading comment
# block). If the awscdk arm's image contract moves, this fails `make check`
# instead of letting the anchor smoke task silently validate a stale contract.
# (Slice A verifier finding; superseded once the Slice C generator templates
# task environments instead of hand-copies.)
set -euo pipefail
cd "$(dirname "$0")/.."

src="arms/awscdk/environment"
dst="tasks/anchor/smoke/environment"

strip_leading_comments() {
  # Drop the leading run of full-line comments (# or //) and blank lines.
  awk 'started || !/^([[:space:]]*(#|\/\/).*)?$/ { started=1; print }' "$1"
}

fail=0
while IFS= read -r rel; do
  if [ ! -f "$dst/$rel" ]; then
    echo "DRIFT: $dst/$rel missing (exists in $src)" >&2
    fail=1
    continue
  fi
  if ! diff -q <(strip_leading_comments "$src/$rel") <(strip_leading_comments "$dst/$rel") >/dev/null; then
    echo "DRIFT: $rel differs between $src and $dst (beyond leading comments)" >&2
    fail=1
  fi
done < <(cd "$src" && find . -type f | sed 's|^\./||')

while IFS= read -r rel; do
  if [ ! -f "$src/$rel" ]; then
    echo "DRIFT: $dst/$rel has no counterpart in $src" >&2
    fail=1
  fi
done < <(cd "$dst" && find . -type f | sed 's|^\./||')

if [ "$fail" -eq 0 ]; then
  echo "smoke-drift: OK ($dst matches $src)"
fi
exit "$fail"
