#!/usr/bin/env python3
"""metrics/validate_result.py — validate published result rows.

Validates one or more cdktn-bench result rows against
``metrics/result_schema.json`` (build plan Phase 0 item 4 / the chant-bench
missing-substrate-field lesson, ``docs/chant-bench-diff.md`` §5: the schema
enforces required fields instead of merely documenting them).

Library use::

    from validate_result import validate_result, load_schema
    errors = validate_result(row)          # [] if valid
    errors = validate_result(row, load_schema("/other/schema.json"))

CLI use — accepts a JSON object, a JSON array of objects, or newline-delimited
JSON (one object per line), and exits non-zero if any row fails::

    uv run python metrics/validate_result.py path/to/result.json [more.json ...]
    uv run python metrics/validate_result.py --schema custom_schema.json result.ndjson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import jsonschema

_DEFAULT_SCHEMA_PATH = Path(__file__).with_name("result_schema.json")


def load_schema(schema_path: str | Path | None = None) -> dict[str, Any]:
    """Load the result-row JSON Schema (defaults to metrics/result_schema.json)."""
    path = Path(schema_path) if schema_path is not None else _DEFAULT_SCHEMA_PATH
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_result(
    row: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> list[str]:
    """Validate one result row against schema (default: result_schema.json).

    Returns a list of human-readable error strings; empty list means valid.
    Collects *all* violations (not just the first) so a single run surfaces
    every missing/malformed field at once.
    """
    if schema is None:
        schema = load_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors = []
    for err in sorted(validator.iter_errors(row), key=lambda e: list(e.path)):
        location = "$" + "".join(f"[{p!r}]" for p in err.path)
        errors.append(f"{location}: {err.message}")

    # Semantic check beyond what JSON Schema alone can express: tokens_total
    # should be consistent with tokens_input/tokens_output. Only runs when
    # all three passed schema validation as the right types, so it never
    # masks a schema error with a confusing arithmetic one.
    if not errors and {"tokens_input", "tokens_output", "tokens_total"} <= row.keys():
        expected = row["tokens_input"] + row["tokens_output"]
        if row["tokens_total"] < expected:
            errors.append(
                f"$['tokens_total']: {row['tokens_total']} is less than "
                f"tokens_input + tokens_output ({expected}) — tokens_total "
                f"must cover at least input+output (it may exceed that sum "
                f"if it also folds in cached tokens)"
            )

    return errors


def _iter_rows(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (label, row) pairs from a JSON-object, JSON-array, or NDJSON file."""
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        yield f"{path}", parsed
    elif isinstance(parsed, list):
        for i, row in enumerate(parsed):
            yield f"{path}[{i}]", row
    else:
        # Fall back to newline-delimited JSON: one object per non-blank line.
        for i, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{i}: not valid JSON ({exc})") from exc
            yield f"{path}:{i}", row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="+", type=Path, help="result row file(s): JSON object, JSON array, or NDJSON"
    )
    parser.add_argument(
        "--schema", type=Path, default=None, help="path to result schema (default: metrics/result_schema.json)"
    )
    args = parser.parse_args(argv)

    schema = load_schema(args.schema)

    ok = True
    n_rows = 0
    for path in args.files:
        try:
            rows = list(_iter_rows(path))
        except ValueError as exc:
            print(f"FAIL {exc}", file=sys.stderr)
            ok = False
            continue
        for label, row in rows:
            n_rows += 1
            if not isinstance(row, dict):
                print(f"FAIL {label}: top-level value must be a JSON object, got {type(row).__name__}", file=sys.stderr)
                ok = False
                continue
            errors = validate_result(row, schema)
            if errors:
                ok = False
                print(f"FAIL {label}:", file=sys.stderr)
                for err in errors:
                    print(f"  {err}", file=sys.stderr)
            else:
                print(f"OK   {label}")

    if n_rows == 0:
        print("no result rows found in input", file=sys.stderr)
        return 1

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
