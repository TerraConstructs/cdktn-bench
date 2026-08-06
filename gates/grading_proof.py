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
drifting implementation -- this script's only job is to pick, per arm, the
two results out of check_arm()'s own per-arm list that answer "is this arm
GRADEABLE" (the good solve.sh, and a fixture that genuinely exercises the
tier-1 Rego/cfn-guard chain) and assert on exactly those, printing a
compact per-arm summary.

Usage:
    uv run python gates/grading_proof.py specs/_toy/toy-ssm-parameter.yaml
    uv run python gates/grading_proof.py specs/apigw-openapi.yaml
    uv run python gates/grading_proof.py specs/foo.yaml --catch some-catch-name
    make grading-proof SPEC=specs/_toy/toy-ssm-parameter.yaml
    make grading-proof SPEC=specs/apigw-openapi.yaml CATCH=some-catch-name

Exit 0 iff, for every enabled arm, the good solve.sh scored 1.0 AND (an
explicit `--catch`/`CATCH=` fixture scored 0.0, OR -- with no explicit
override -- either that arm's auto-selected tier-1 fixture scored 0.0, or
this arm genuinely has no fixture that reaches tier 1 at all, reported as
a per-arm SKIP rather than a failure). At least one enabled arm across the
whole spec must produce a real tier-1 proof (see `any_tier1_proof` below)
or the run fails outright -- a spec where the tier-1 chain is proven on
NO arm has proven nothing this gate exists to prove.

Which fixture, scenario-agnostically AND per-arm (generalized 2026-08-06,
residual-findings fix -- see DECISIONS.md Amendment 9 for the full
regression writeup and Amendment 8's now-corrected claims): this script
used to hardcode NEGATIVE_CATCH = "policy-scoped-to-parameter" (fixed
2026-08-06, see the first `generalized` note above), then generalized to
"the first catch with predicted_tier_caught awscdk==hcl=='1'" -- picked
ONCE, spec-wide, and reused unmodified for every enabled arm. That second
generalization was itself unsound: it silently assumed every scenario has
(at least) one catch that is tier-1 on EVERY arm-group simultaneously,
which cannot hold for a scenario whose whole point is that one arm's typed
surface catches a mistake EARLIER than another arm's does --
`sfn-jsonata`'s own `mode-mixing-jsonpath-artifacts` catch is exactly this
shape (corrected 2026-08-06 to `predicted_tier_caught.awscdk == "0"`,
`.hcl == "1"` -- a genuine, intentional, documented per-arm divergence, not
a mistake to route around), and `ecs-swappiness`'s `swappiness-requires-
maxswap` catch was ALWAYS this shape (`.awscdk == "0"`, `.hcl == "1"`,
`.terraconstructs_override == "0"`) -- so the spec-wide selector could
never find a catch for either scenario and `make grading-proof` exited 1
unconditionally for both, regardless of `--catch`.

The fix: select independently PER ARM, and select by what the run actually
OBSERVED (`oracle_falsifiability.observed_tier`, parsed from the same
`tests/static_tiers.sh` stdout `check_arm` already captured), not by
`predicted_tier_caught` alone -- the first `solution/broken/<dir>/`
fixture (in the SAME order `check_arm` itself walks them: every declared
`spec.catches[]` entry first, then any extra, non-catch-named fixture
directory) whose run was actually caught at tier "1" on THIS arm. This
also, for free, discovers a scenario's own hand-authored "escape hatch"
fixture when the catch's own primary fixture doesn't reach tier 1 on a
given arm -- e.g. `sfn-jsonata`'s
`mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch` (awscdk
only) and `ecs-swappiness`'s `swappiness-requires-maxswap-cfn-override`
(awscdk only), both hand-authored specifically to force a typed L2's
normally-tier-0-only mistake past the compiler so their scenario's own
tier-1 cfn-guard rule is genuinely exercised by *something*
`make grading-proof`/`make falsifiability` actually re-runs, per each
fixture's own solve.sh header comment -- without this script needing to
know either name in advance. `--catch`/`CATCH=` still overrides this
per-arm auto-selection with one explicit fixture name, applied uniformly
to every enabled arm (unchanged from before) -- a named fixture missing on
a given arm is still a hard FAIL for that arm, since an explicit request
names one specific thing to prove, not "whatever's available".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from spec_model import load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_falsifiability import RunResult, check_arm, observed_tier  # noqa: E402


def auto_select_negative(results: list[RunResult], arm: str) -> RunResult | None:
    """Pick the first `{arm}/solution/broken/<name>/solve.sh` row out of
    `check_arm(spec, arm)`'s own results whose run was OBSERVED (not merely
    predicted) to be caught at tier "1" -- i.e. genuinely exercised this
    arm's Rego/cfn-guard chain, the thing this gate exists to prove is
    wired for real. Walks `results` in the exact order `check_arm` produces
    them (declared catches in `spec.catches[]` order, then extra
    non-catch-named fixtures in directory order), so a scenario's own
    catch-named fixture wins over an escape-hatch fixture whenever the
    catch-named one itself reaches tier 1 on this arm, and the escape-hatch
    fixture is picked up automatically otherwise. Returns None when this
    arm has no fixture that reaches tier 1 at all -- reported by `main` as
    a per-arm SKIP, not a failure (see module docstring)."""
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

    for arm in spec.arms.enabled_arms():
        results = check_arm(spec, arm)
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
