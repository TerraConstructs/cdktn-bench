"""generator/split.py — train/holdout scenario split (prereg §7.1: "the tuned
skills/MCP equipping must be developed on a held-out scenario split, never
tuned on the benchmark scenarios themselves"; DECISIONS.md Amendment 10).

This module is BOTH the split's definition (a deterministic function of the
current scenario-id set, so it can be re-run whenever scenarios 5-15 land)
and the runtime loader ``generator/gen.py`` consults to refuse emitting
tuned-equipping material for a holdout scenario (see
``gen.py::enforce_no_holdout_equipping``).

Algorithm ("scenario-split-v1", frozen — see SPLIT_ALGORITHM_VERSION):
  1. For every candidate scenario id, score = the first 16 hex chars of
     sha256(f"{SEED}:{spec_id}"), read as an integer. This is a
     deterministic, seed-fixed pseudo-random permutation key — same id,
     same seed, same score, forever; no dependency on file mtimes, spec
     content, or iteration order.
  2. Sort ids by score ascending. This total order is fixed per id
     (doesn't change as ids are added/removed), but an id's RANK can shift
     when the candidate set changes (a lower-scored id joining in front of
     it) — that's expected, see "Re-split procedure" below.
  3. n_train = round(TRAIN_FRACTION * n) (round-half-up). The first
     n_train ids (lowest score) are "train"; the rest are "holdout".

Re-split procedure (for when scenarios 5-15 land):
  1. Run ``uv run python generator/split.py --write`` — recomputes the
     assignment from every non-toy ``specs/*.yaml`` id currently on disk
     and overwrites ``specs/split.yaml``.
  2. Diff the old vs. new ``assignments`` block. Adding scenarios can shift
     the 60/40 CUTOFF RANK even though no individual id's score changes —
     an id near the boundary can flip train->holdout or holdout->train.
     This is expected (not a bug to work around): with only 4-15 scenarios
     "60% train" is inherently a moving cutoff line over a fixed ranking,
     not a stable per-id assignment.
  3. If any id FLIPPED:
       - train -> holdout: any tuned skill/MCP equipping developed against
         that scenario while it was train is now tainted (prereg §7.1's
         whole point — equipping selected using signal from a scenario
         must not be run held-out against that same scenario). Retire that
         equipping and re-tune once a stable train set is confirmed, or
         freeze the split (stop re-running --write) once real tuning work
         begins for a given phase.
       - holdout -> train: no integrity problem (nothing was ever tuned
         against it), but note it in DECISIONS.md so anyone reading
         Amendment 10 for scenario-N's history sees where it moved.
  4. Record the before/after assignment table + which ids flipped (if any)
     as a new DECISIONS.md amendment. Bump ``generated_at`` in
     specs/split.yaml (written automatically by --write).

Deliberately NOT reshuffled per scenario COUNT milestone automatically —
--write is always a manual, logged action, never run implicitly by ``make
gen``/``make ci``, so the split only ever changes when a human runs it and
writes down why.
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from typing import Literal

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
TOY_SPECS_DIR = SPECS_DIR / "_toy"
SPLIT_PATH = SPECS_DIR / "split.yaml"

Group = Literal["train", "holdout"]

# Bump only if the algorithm itself changes (would re-permute every id,
# not just shift the cutoff) — a full, deliberate re-split, distinct from
# the ordinary "scenarios 5-15 landed" cutoff-shift case above.
SPLIT_ALGORITHM_VERSION = 1
SEED = "cdktn-bench-split-v1"
TRAIN_FRACTION = 0.6


def discover_spec_ids() -> list[str]:
    """Every non-toy spec id currently on disk (specs/*.yaml, stem == id
    per SCHEMA.md §0 — specs/_toy/ is excluded, same convention gen.py's
    own ``generate()`` uses for local-registry.json registration).
    ``specs/split.yaml`` itself (this module's own output, living
    alongside the specs it splits) is also excluded — it is split metadata,
    not a spec, and would otherwise show up as a bogus scenario id "split"."""
    return sorted(
        p.stem for p in SPECS_DIR.glob("*.yaml") if p.name != SPLIT_PATH.name
    )


def compute_split(
    spec_ids: list[str],
    seed: str = SEED,
    train_fraction: float = TRAIN_FRACTION,
) -> dict[str, dict[str, object]]:
    """Deterministic {spec_id: {"group": "train"|"holdout", "score": hex,
    "rank": int}} per the algorithm in this module's own docstring.

    Pure function of (spec_ids, seed, train_fraction) — no filesystem
    access beyond what the caller already resolved into spec_ids, so it is
    trivially unit-testable and reproducible off this repo.
    """
    scored = []
    for spec_id in spec_ids:
        digest = hashlib.sha256(f"{seed}:{spec_id}".encode()).hexdigest()
        score_hex = digest[:16]
        scored.append((int(score_hex, 16), score_hex, spec_id))
    scored.sort(key=lambda t: (t[0], t[2]))  # tie-break on id for full determinism

    n = len(scored)
    n_train = math.floor(train_fraction * n + 0.5)  # round-half-up

    assignments: dict[str, dict[str, object]] = {}
    for rank, (_score_int, score_hex, spec_id) in enumerate(scored):
        assignments[spec_id] = {
            "group": "train" if rank < n_train else "holdout",
            "score": score_hex,
            "rank": rank,
        }
    return assignments


def render_split_yaml(assignments: dict[str, dict[str, object]], generated_at: str) -> str:
    n = len(assignments)
    n_train = sum(1 for a in assignments.values() if a["group"] == "train")
    n_holdout = n - n_train
    header = f"""\
# specs/split.yaml — train/holdout scenario split (prereg §7.1, DECISIONS.md
# Amendment 10). GENERATED by `generator/split.py` — do not hand-edit the
# `assignments` block; re-run `uv run python generator/split.py --write` and
# log the diff in DECISIONS.md instead (see generator/split.py's own
# "Re-split procedure" docstring for the full steps).
#
# Rule this file exists to enforce: tuned skills/MCP equipping is developed
# ONLY on scenarios assigned "train" below; a holdout scenario is used
# purely to SELECT among equippings already built on train, never to tune
# them. generator/gen.py's `enforce_no_holdout_equipping()` hard-fails
# `make gen` if a holdout scenario's generated task directory ever contains
# skill/MCP/plugin config (the same equipping-file discovery
# gates/equipping.py's hash already uses) — this file is what that check
# reads.
#
# algorithm_version: SPLIT_ALGORITHM_VERSION in generator/split.py — bump
#   only on a genuine algorithm change (re-permutes every id); ordinary
#   scenario additions just shift the 60/40 cutoff over the existing
#   per-id ranking, see generator/split.py's docstring.
# seed: the fixed string every id's score is hashed against — changing it
#   is equivalent to bumping algorithm_version (also re-permutes everyone).
# train_fraction: the target train share; n_train = round(train_fraction *
#   len(assignments)), round-half-up.
algorithm_version: {SPLIT_ALGORITHM_VERSION}
seed: {SEED!r}
train_fraction: {TRAIN_FRACTION}
generated_at: {generated_at!r}
counts:
  total: {n}
  train: {n_train}
  holdout: {n_holdout}
assignments:
"""
    lines = [header]
    for spec_id in sorted(assignments):
        a = assignments[spec_id]
        lines.append(f"  {spec_id}:\n")
        lines.append(f"    group: {a['group']}\n")
        lines.append(f"    score: {a['score']!r}\n")
        lines.append(f"    rank: {a['rank']}\n")
    return "".join(lines)


def load_split(path: Path = SPLIT_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist — run `uv run python generator/split.py --write` "
            "to create it (see DECISIONS.md Amendment 10)."
        )
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "assignments" not in data:
        raise ValueError(f"{path}: malformed split file (no top-level 'assignments' key)")
    return data


def spec_group(spec_id: str, split_data: dict | None = None) -> Group | None:
    """The split group for spec_id, or None if it isn't in split.yaml yet
    (e.g. a brand-new scenario authored before the next --write / re-split
    — see the module docstring's re-split procedure). Callers that need to
    ENFORCE something for holdout scenarios must treat None as "nothing to
    enforce yet", not as an implicit train/holdout default — a silent
    default in either direction would either block gen.py on scenarios
    genuinely too new to be split yet, or (worse) silently let
    tuned-equipping material past the guard for a not-yet-classified
    scenario.
    """
    if split_data is None:
        split_data = load_split()
    entry = split_data.get("assignments", {}).get(spec_id)
    if entry is None:
        return None
    group = entry["group"]
    if group not in ("train", "holdout"):
        raise ValueError(f"specs/split.yaml: spec {spec_id!r} has invalid group {group!r}")
    return group  # type: ignore[return-value]


def main(argv: list[str]) -> int:
    import datetime

    write = "--write" in argv
    spec_ids = discover_spec_ids()
    assignments = compute_split(spec_ids)
    generated_at = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    rendered = render_split_yaml(assignments, generated_at)

    if write:
        SPLIT_PATH.write_text(rendered)
        print(f"wrote {SPLIT_PATH.relative_to(REPO_ROOT)} ({len(spec_ids)} scenarios)")
    else:
        print(rendered, end="")
        print(
            "\n(dry run — pass --write to overwrite specs/split.yaml; "
            "see generator/split.py's 're-split procedure' docstring first)",
            file=sys.stderr,
        )

    for spec_id in sorted(assignments):
        a = assignments[spec_id]
        print(f"  {spec_id:32s} {a['group']:8s} rank={a['rank']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
