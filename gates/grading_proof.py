"""gates/grading_proof.py -- end-to-end grading proof (benchmark-integrity
review finding F2, 2026-08-06):

    "end-to-end reward is constant 0.0 on all arms: oracles/rego/.../
    policy.rego and oracles/cfn-guard/.../policy.guard are still scaffolds,
    and the (correct) SKIPPED_STUB fail-closed behavior zeroes everything.
    Nothing demonstrates any arm is GRADEABLE."

Proves the opposite, for real, across all three arms in one command: a
correct reference solution scores reward 1.0 AND a negative fixture that
violates the policy-scoped-to-parameter catch (the tier-1
Rego/cfn-guard-graded family -- "the prior verifier proved a wildcard IAM
inline_policy... terraconstructs case is decidable from plan JSON today")
scores reward 0.0. Six outcomes total (3 arms x {correct, negative}).

Deliberately thin: reuses `gates.oracle_falsifiability.check_arm` (the
SAME sandbox-preparation code path `make falsifiability` runs, itself
covered by gates/tests/test_oracle_falsifiability.py) rather than a second,
drifting implementation -- this script's only job is to pick the two
results out of check_arm()'s per-arm list that answer "is this arm
GRADEABLE" (the good solve.sh, and the policy-family negative) and assert
on exactly those, printing a compact six-row summary.

Usage:
    uv run python gates/grading_proof.py specs/_toy/toy-ssm-parameter.yaml
    make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml

Exit 0 iff, for every enabled arm, the good solve.sh scored 1.0 AND the
policy-scoped-to-parameter broken/ fixture scored 0.0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from spec_model import load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_falsifiability import check_arm  # noqa: E402

NEGATIVE_CATCH = "policy-scoped-to-parameter"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)
    all_ok = True
    rows: list[tuple[str, str, float | None, bool]] = []

    for arm in spec.arms.enabled_arms():
        results = check_arm(spec, arm)
        good = next((r for r in results if r.label == f"{arm}/solution/solve.sh"), None)
        negative = next((r for r in results if r.label == f"{arm}/solution/broken/{NEGATIVE_CATCH}/solve.sh"), None)

        if good is None or good.reward is None:
            rows.append((arm, "correct solution", None, False))
            all_ok = False
        else:
            ok = good.ok and good.reward == 1.0
            rows.append((arm, "correct solution", good.reward, ok))
            all_ok = all_ok and ok

        if negative is None:
            rows.append((arm, f"negative ({NEGATIVE_CATCH})", None, False))
            all_ok = False
        elif negative.reward is None:
            rows.append((arm, f"negative ({NEGATIVE_CATCH})", None, False))
            all_ok = False
        else:
            ok = negative.ok and negative.reward == 0.0
            rows.append((arm, f"negative ({NEGATIVE_CATCH})", negative.reward, ok))
            all_ok = all_ok and ok

    print(f"grading-proof for {spec.id!r} -- {len(rows)} outcomes:")
    for arm, kind, reward, ok in rows:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {arm:16s} {kind:28s} reward={reward}")

    if all_ok:
        print(f"\ngrading-proof OK for {spec.id!r} -- every arm is GRADEABLE")
        return 0
    print(f"\ngrading-proof FAILED for {spec.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
