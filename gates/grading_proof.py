"""End-to-end grading proof: shows each arm is actually GRADEABLE.

Across every enabled arm in one command: the correct reference solution scores
reward 1.0, AND a negative fixture that genuinely exercises the arm's grading
chain is shown to be discriminated. Deliberately thin -- it reuses
`gates.oracle_falsifiability.check_arm`, the same sandbox-preparation path
`make falsifiability` runs, and only picks the rows per arm that answer that
question.

Two kinds of proof satisfy it, and at least one enabled arm must produce one or
the run fails outright: a TIER-1 proof (a fixture observed caught at tier "1"
scoring 0.0) or a LIVE-TIER proof (a `predicted_tier_caught: "live"` fixture
shown to survive every static tier under a gating, hand-authored live check --
see live_tier_proof()).

Exit 0 iff, for every enabled arm, the good solve.sh scored 1.0 AND the arm's
negative row holds: an explicit `--catch`/`CATCH=` fixture scored 0.0, or --
with no override -- the auto-selected tier-1 fixture scored 0.0, or the arm
carries a live-tier proof, or the arm has neither kind of fixture, reported as
a per-arm SKIP.

Usage: `make grading-proof SPEC=specs/apigw-openapi.yaml [CATCH=<fixture>]`

Negative-fixture selection: docs/gates.md#grading-proof
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from spec_model import Arm, Spec, load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle_falsifiability import (  # noqa: E402
    LIVE_ONLY_CONFIRMED_MARKER,
    RunResult,
    check_arm,
    observed_tier,
    predicted_tier,
)
from aws_stub import running_stub  # noqa: E402

TIER1_PROOF = "tier-1 catch"
LIVE_PROOF = "live-tier catch"
EXPLICIT_PROOF = "explicit --catch fixture"


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
    fixture reaching tier 1 at all -- `main` then looks for a live-tier proof,
    and reports a per-arm SKIP if there is none."""
    for r in results:
        if "/solution/broken/" not in r.label:
            continue
        if observed_tier(r.detail) == "1":
            return r
    return None


def live_tier_proof(results: list[RunResult], spec: Spec, arm: Arm) -> RunResult | None:
    """Pick this arm's LIVE-TIER proof of gradeability, or None.

    A scenario whose discriminating fact only exists at runtime has no tier-1
    fixture to offer and never will: a cross-resource Rego rule would be
    vacuous when both the right and the wrong shape produce the same artifact
    graph. Its grading chain is still proven -- by the tier the spec says
    decides -- so the gate accepts that proof instead of failing the spec for
    owning no static catch. All of the following must hold, and each is read
    off the run, never assumed:

      * the spec's live check is `enabled`, `gating` and `hand_authored`
        (specs/SCHEMA.md §5) -- a non-gating live check costs a trial no
        reward, so it can prove nothing about grading;
      * a catch applying to THIS arm declares `predicted_tier_caught: "live"`
        here (specs/SCHEMA.md §3, resolved per arm by `predicted_tier`);
      * its fixture's host-side run produced a graded artifact (the tier-0
        summary marker is present) and scored 1.0, i.e. every static tier --
        tier 0 and, where present, tier 1 -- PASSED it;
      * `observed_tier` names no static tier at all, so the live tier is the
        one left to decide;
      * the fixture printed `LIVE_ONLY_CONFIRMED_MARKER` after mechanically
        confirming the static-indistinguishability property it claims -- the
        same evidence `make falsifiability` requires of a live catch.

    Fail-closed on every branch: a run whose stdout carries no tier-0 summary
    proves nothing (static_tiers.sh writes 0.0 for a broken toolchain too, and
    a truncated run has no tier to report), and a missing marker means the
    fixture asserted its tier rather than earning it."""
    live = spec.verifier.live_check
    if not (live.enabled and live.gating and live.hand_authored):
        return None
    for catch in spec.catches:
        if arm not in catch.applies_to or predicted_tier(catch, arm) != "live":
            continue
        label = f"{arm}/solution/broken/{catch.name}/solve.sh"
        run = next((r for r in results if r.label == label), None)
        if run is None or run.reward != 1.0:
            continue
        if "tier0_pass=" not in run.detail or observed_tier(run.detail) is not None:
            continue
        if LIVE_ONLY_CONFIRMED_MARKER not in run.detail:
            continue
        return run
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
        "OBSERVED to be caught at tier \"1\" on that specific arm, else that "
        "arm's live-tier proof; see auto_select_negative() and "
        "live_tier_proof())",
    )
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)

    all_ok = True
    proofs: list[tuple[str, str]] = []  # (arm, proof kind)
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
                proofs.append((arm, EXPLICIT_PROOF))
            else:
                negative = auto_select_negative(results, arm)
                if negative is None:
                    live = live_tier_proof(results, spec, arm)
                    if live is None:
                        rows.append(
                            (arm, "negative (no fixture reaches tier 1 or the live tier)", None, "SKIP")
                        )
                        continue
                    # The live tier decides this arm, so the negative's own
                    # required verdict is INVERTED: reward 1.0, because
                    # surviving every static tier is what live_tier_proof has
                    # just established mechanically.
                    proofs.append((arm, LIVE_PROOF))
                    rows.append((
                        arm,
                        f"negative ({_catch_name_from_label(live.label)}, live-tier)",
                        live.reward,
                        "PASS",
                    ))
                    continue
                proofs.append((arm, TIER1_PROOF))

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

    if not proofs:
        print(
            f"\ngrading-proof: {spec.id!r} -- no enabled arm produced EITHER "
            "accepted proof of gradeability: no solution/broken/ fixture was "
            "observed caught at tier \"1\", and none is a live-tier proof (a "
            "`predicted_tier_caught: \"live\"` fixture under an enabled, "
            "gating, hand-authored live check, surviving every static tier "
            f"and printing {LIVE_ONLY_CONFIRMED_MARKER}) -- pass --catch "
            "explicitly, or this scenario has nothing graded anywhere to "
            "prove grading-proof with",
            file=sys.stderr,
        )
        return 1

    if all_ok:
        proof_line = ", ".join(f"{arm} via {kind}" for arm, kind in proofs)
        print(f"\ngrading-proof OK for {spec.id!r} -- every arm is GRADEABLE ({proof_line})")
        return 0
    print(f"\ngrading-proof FAILED for {spec.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
