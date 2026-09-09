"""End-to-end grading proof: shows each arm is actually GRADEABLE.

Across every enabled arm in one command: the correct reference solution scores
reward 1.0, AND a negative fixture that genuinely exercises the arm's tier-1
Rego/cfn-guard chain scores reward 0.0. Deliberately thin -- it reuses
`gates.oracle_falsifiability.check_arm`, the same sandbox-preparation path
`make falsifiability` runs, and only picks the two rows per arm that answer
that question.

Exit 0 iff, for every enabled arm, the good solve.sh scored 1.0 AND (an
explicit `--catch`/`CATCH=` fixture scored 0.0, or -- with no override --
either that arm's auto-selected tier-1 fixture scored 0.0, or the arm has no
fixture reaching tier 1 at all, reported as a per-arm SKIP). At least one
enabled arm must produce a real tier-1 proof or the run fails outright.

Usage: `make grading-proof SPEC=specs/apigw-openapi.yaml [CATCH=<fixture>]`

Negative-fixture selection: docs/gates.md#grading-proof
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from spec_model import load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_falsifiability import RunResult, check_arm, observed_tier  # noqa: E402
from aws_stub import running_stub  # noqa: E402


def auto_select_negative(results: list[RunResult], arm: str) -> RunResult | None:
    """Pick the first `{arm}/solution/broken/<name>/solve.sh` row out of
    `check_arm(spec, arm)`'s results whose run was OBSERVED (not merely
    predicted) to be caught at tier "1" -- i.e. genuinely exercised this arm's
    Rego/cfn-guard chain, the thing this gate exists to prove is wired for real.

    Walks `results` in the exact order `check_arm` produces them (declared
    catches in `spec.catches[]` order, then extra non-catch-named fixtures in
    directory order), so a catch-named fixture wins over an escape-hatch fixture
    whenever it reaches tier 1 on this arm, and the escape-hatch fixture is
    picked up automatically otherwise. Returns None when this arm has no
    fixture reaching tier 1 at all -- reported by `main` as a per-arm SKIP, not
    a failure."""
    for r in results:
        if "/solution/broken/" not in r.label:
            continue
        if observed_tier(r.detail) == "1":
            return r
    return None


def _catch_name_from_label(label: str) -> str:
    # "{arm}/solution/broken/{name}/solve.sh" -> "{name}"
    return label.split("/solution/broken/", 1)[1].rsplit("/solve.sh", 1)[0]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    parser.add_argument(
        "--catch",
        default=None,
        help="solution/broken/<name> fixture to use as the negative on every "
        "enabled arm (default: auto-selected per arm -- the first fixture "
        "OBSERVED to be caught at tier \"1\" on that specific arm; see "
        "auto_select_negative()'s docstring)",
    )
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)

    all_ok = True
    any_tier1_proof = False
    rows: list[tuple[str, str, float | None, str]] = []  # (arm, kind, reward, status)

    # ONE stub for the whole gate process; every arm's check_arm run shares it.
    with running_stub() as env:
        for arm in spec.arms.enabled_arms():
            results = check_arm(spec, arm, env)
            good = next((r for r in results if r.label == f"{arm}/solution/solve.sh"), None)

            if good is None or good.reward is None:
                rows.append((arm, "correct solution", None, "FAIL"))
                all_ok = False
            else:
                ok = good.ok and good.reward == 1.0
                rows.append((arm, "correct solution", good.reward, "PASS" if ok else "FAIL"))
                all_ok = all_ok and ok

            if args.catch:
                negative = next(
                    (r for r in results if r.label == f"{arm}/solution/broken/{args.catch}/solve.sh"), None
                )
                if negative is None:
                    rows.append((arm, f"negative ({args.catch})", None, "FAIL"))
                    all_ok = False
                    continue
                any_tier1_proof = True
            else:
                negative = auto_select_negative(results, arm)
                if negative is None:
                    rows.append(
                        (arm, "negative (no fixture reaches tier 1 on this arm)", None, "SKIP")
                    )
                    continue
                any_tier1_proof = True

            catch_name = _catch_name_from_label(negative.label)
            if negative.reward is None:
                rows.append((arm, f"negative ({catch_name})", None, "FAIL"))
                all_ok = False
            else:
                ok = negative.ok and negative.reward == 0.0
                rows.append((arm, f"negative ({catch_name})", negative.reward, "PASS" if ok else "FAIL"))
                all_ok = all_ok and ok

    print(f"grading-proof for {spec.id!r} -- {len(rows)} outcomes:")
    for arm, kind, reward, status in rows:
        print(f"  [{status}] {arm:16s} {kind:44s} reward={reward}")

    if not any_tier1_proof:
        print(
            f"\ngrading-proof: {spec.id!r} -- no enabled arm has ANY "
            "solution/broken/ fixture observed to be caught at tier \"1\" "
            "-- pass --catch explicitly, or this scenario has nothing "
            "tier-1-graded anywhere to prove grading-proof with",
            file=sys.stderr,
        )
        return 1

    if all_ok:
        print(f"\ngrading-proof OK for {spec.id!r} -- every arm is GRADEABLE")
        return 0
    print(f"\ngrading-proof FAILED for {spec.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
