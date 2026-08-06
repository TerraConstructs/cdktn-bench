"""metrics/test_pipeline_e2e.py — end-to-end proof that gates/emit_result.py's
output and metrics/tokens_to_green.py's input actually agree in practice.

Fixes the "the headline metric script is orphaned from the run pipeline"
finding (2026-08-06): no make target invoked metrics/tokens_to_green.py at
all, scripts/run-bench.sh never called it post-run, and `make ci`/`make
check` only ever exercised it against synthetic rows hand-built inside its
own test module -- nothing in the repo produced a directory of real
gate-emitted result rows and fed it through the aggregator, so a format
drift between gates/emit_result.py::to_result_row's output and
metrics/tokens_to_green.py's input (or metrics/result_schema.json itself)
could land and stay invisible.

This module: runs Gate 2+3 (gates.emit_result.build_result_record +
to_result_row) against the real gates/tests fixtures via
metrics/emit_fixture_rows.py's own generate_rows() (the same rows
`check-result-schema` already validates against the schema), writes them
to a temp directory in the same shape a real job's output would be (one
JSON file per row), runs the REAL tokens_to_green.main() CLI entry point
over that directory, and asserts the resulting benchmark.json has the
shape a real downstream consumer depends on. Wired into `make check` via
mk/metrics.mk's `check-metrics-e2e`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from metrics.emit_fixture_rows import generate_rows  # noqa: E402
from metrics.tokens_to_green import main  # noqa: E402


def _write_rows_as_a_real_job_would(tmp_path: Path) -> int:
    """One JSON file per row, mirroring a real job's per-trial output
    layout (docs/aws-bench-guide.md §6) -- not one big array file, so this
    also exercises find_row_files()'s recursive directory walk for real."""
    rows = generate_rows()
    for label, row in rows:
        safe_name = label.replace("/", "-")
        (tmp_path / f"{safe_name}.json").write_text(json.dumps(row))
    return len(rows)


def test_gate_emitted_rows_flow_end_to_end_through_tokens_to_green(tmp_path: Path) -> None:
    n_rows = _write_rows_as_a_real_job_would(tmp_path)
    assert n_rows > 0, "metrics/emit_fixture_rows.py::generate_rows() produced nothing to test against"

    rc = main([str(tmp_path)])
    assert rc == 0, "tokens_to_green.main() rejected a real gates/emit_result.py-shaped row"

    out_json_path = tmp_path / "benchmark.json"
    out_md_path = tmp_path / "benchmark.md"
    assert out_json_path.exists()
    assert out_md_path.exists()

    report = json.loads(out_json_path.read_text())
    assert report["n_rows_loaded"] == n_rows
    assert report["n_rows_rejected"] == 0
    assert report["load_errors"] == []

    # Shape a real downstream consumer depends on -- not just "the file
    # exists", but that the keys this pipeline's own review findings
    # added (split stratification, per-scenario breakdown,
    # tier1_not_verifiable accounting) actually round-trip from a real
    # gate-emitted row, not just a hand-authored test fixture.
    for key in ("cells", "headline_cells", "train_cells", "split_composition", "tier_attribution"):
        assert key in report, f"benchmark.json is missing expected top-level key {key!r}"

    assert len(report["cells"]) >= 1
    cell = report["cells"][0]
    for key in (
        "n_valid",
        "n_tier1_not_verifiable",
        "tokens_to_green_km",
        "tokens_to_green_km_own_stopping_point",
        "scenario_coverage",
        "by_scenario",
        "n_iterations_unknown",
    ):
        assert key in cell, f"cell is missing expected key {key!r}"

    # metrics/emit_fixture_rows.py's fixture rows carry no real spec.id
    # (spec_id=None -> "unclassified" -- see that module's own comment),
    # so they must land in split_composition's unclassified bucket, not
    # silently vanish or get miscounted into headline_cells/train_cells.
    assert report["split_composition"]["n_unclassified_rows"] == n_rows
    assert report["headline_cells"] == []
    assert report["train_cells"] == []

    md = out_md_path.read_text()
    assert "HEADLINE" in md
