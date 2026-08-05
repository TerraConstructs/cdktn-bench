#!/usr/bin/env python3
"""metrics/emit_fixture_rows.py — the schema's actual producer, proven.

`metrics/result_schema.json` had no producer: `build_result_record()`'s
records (`gates/emit_result.py`) don't validate against the schema as-is
(missing required fields like `schema_version`/`tokens_total`, plus extra
gate-internal keys like `audit`/`infra`), and nothing in the repo bridged
the two. `check-result-schema` therefore only ever proved that a
hand-authored example (`metrics/examples/valid-result.json`) matched a
hand-authored schema — exactly the chant-bench "silently absent from all 122
published result JSONs because nothing enforced it" gap this schema exists
to close (see its own `description`).

This script closes the loop for real: it runs Gate 2 + Gate 3
(`gates.emit_result.build_result_record`) against the real
`gates/tests/fixtures/<arm>/{genuine,bypass,infra-failure}/` trial dirs, maps
each record through `gates.emit_result.to_result_row()` (the schema
producer), and validates every resulting row against
`metrics/result_schema.json` via `metrics.validate_result.validate_result()`.
Exits non-zero if any generated row fails validation.

Usage::

    uv run python metrics/emit_fixture_rows.py

Wired into `make check-result-schema` (mk/rails.mk) alongside the static
example, so a schema change that breaks what a real gate-emitted record maps
to fails `make check`, not just the hand-authored fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gates.emit_result import build_result_record, to_result_row  # noqa: E402
from gates.tests.conftest import ARMS, FIXTURES_DIR, SCENARIOS  # noqa: E402
from metrics.validate_result import validate_result  # noqa: E402

# @sha256: short-circuits compute_equipping_hash's docker-inspect fallback so
# this script never shells out to docker and stays fast/deterministic.
_FAKE_DIGEST_IMAGE_REF = "cdktn-bench/fixture@sha256:" + "7" * 64
_TASK_DIR = FIXTURES_DIR / "task-dir"


def generate_rows() -> list[tuple[str, dict[str, Any]]]:
    """Yield ``(label, row)`` for every arm x scenario fixture."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for arm in ARMS:
        for scenario in SCENARIOS:
            trial_dir = FIXTURES_DIR / arm / scenario
            record = build_result_record(
                trial_dir,
                arm,
                _TASK_DIR,
                _FAKE_DIGEST_IMAGE_REF,
                {"model": "claude-sonnet-5", "harness": "empty"},
            )
            row = to_result_row(
                record,
                model="claude-sonnet-5",
                harness="empty",
                oracle_version="oracles@fixture",
                scenario="fixture-scenario",
                task=f"fixture/{arm}/{scenario}",
                trial_id=f"{arm}-{scenario}",
                job_id="fixture-job",
            )
            rows.append((f"{arm}/{scenario}", row))
    return rows


def main() -> int:
    ok = True
    for label, row in generate_rows():
        errors = validate_result(row)
        if errors:
            ok = False
            print(f"FAIL {label} (validity_class={row.get('validity_class')}):", file=sys.stderr)
            for err in errors:
                print(f"  {err}", file=sys.stderr)
        else:
            print(f"OK   {label:35} validity_class={row['validity_class']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
