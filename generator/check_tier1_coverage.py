#!/usr/bin/env python3
"""generator/check_tier1_coverage.py — tier-1 falsifiability coverage floor.

Fixes the mechanism half of benchmark-integrity finding "An asymmetric
tier-1 oracle-strictness break passes `make ci` completely" (2026-08-06):
demonstrated by editing `oracles/rego/apigw-openapi/policy.rego`'s
`route_count_correct` rule from `count(methods) != 3` to `count(methods) <
0` (permanently vacuous) and observing `make gen` + `make check-paths` +
`make falsifiability` + `make grading-proof` all still report PASS/OK.
Root cause: `gates/oracle_falsifiability.py` only falsifies a tier-1
`structural_assert` that SOME `solution/broken/<catch-name>/` fixture
happens to violate -- a scenario can declare N tier-"1" structural_asserts
while fewer than N catches ever predict a tier-1 catch on a given arm,
leaving the excess asserts with ZERO covering negative fixture. Gutting
one of those specific asserts changes no falsifiability/grading-proof
verdict at all, because nothing was ever falsifying it in the first place
-- proven for real: `apigw-openapi` declares 2 tier-"1" asserts
(`route-count-correct`, `deployment-depends-on-all-methods`) behind
exactly 1 catch.

This is a coarse, NUMERIC coverage floor, not a true per-assert mapping --
specs/SCHEMA.md has no catch<->structural_assert linkage field to check
exactly against (a Catch names a taxonomy/description/predicted tier, never
which structural_assert(s) its broken fixture is meant to violate). For
each enabled arm this requires:

    count(catches whose predicted_tier_caught resolves to "1" for this arm)
        >=
    count(structural_asserts with tier "1" that apply_to this arm)

By the pigeonhole principle, failing this proves at least one tier-1
assert has NO covering catch at all (let alone a falsifying one) -- exactly
the shape of gap the demonstrated attack exploited. Passing it does NOT
prove full per-assert coverage (two catches could incidentally both
violate the same assert while a third goes untouched) -- see this
project's DECISIONS.md / ci/README.md for the honest, current state of
which scenarios still have a real (not just numeric) gap.

Usage:
    uv run python generator/check_tier1_coverage.py specs/apigw-openapi.yaml
    make tier1-coverage SPEC=specs/apigw-openapi.yaml

Exit 0 iff every enabled arm's catch count meets the floor for that arm.

Exit 3 (SKIP -- the same "not proven yet, non-gating" convention
generator/check_reference_paths.py uses for NOT_AUTHORED) when the floor is
NOT met for at least one arm, BUT the gap is no worse than the recorded
``_KNOWN_UNCOVERED_GAP`` baseline for that (spec, arm) -- a TRACKED,
pre-existing authoring gap, not new drift.

Exit 1 (FAIL, GATING) when the gap for some (spec, arm) EXCEEDS its
recorded baseline -- either a brand-new spec/arm with no baseline entry at
all, or an existing one whose gap widened (an assert was added with no
covering catch, or a catch was removed/repurposed) -- i.e. regressed past
the state this fix was checked in against.

2026-08-06 round 2 ("An asymmetric tier-1 oracle-strictness break passes
`make ci` completely ... the numeric floor ... is non-gating (exit 3 =
SKIP) precisely for sfn-jsonata ... so it cannot detect the break there"):
running this against every shipped spec as of 2026-08-06 shows the gap is
NOT unique to apigw-openapi (already closed by the original fix, by adding
a covering `route-count-wrong` catch) -- `ecs-swappiness`, `sfn-jsonata`,
and `specs/_toy/toy-ssm-parameter.yaml` itself also fail the floor and have
NOT been fully re-authored with covering catches for every declared tier-1
assert (out of scope for one pass -- closing them needs new, hand-verified
negative fixtures per scenario, the same work `route-count-wrong` and
sfn-jsonata's own `raw-jsonpath-literal-value-only` extra fixture
required). Reporting an UNCHANGED tracked gap as a hard FAIL would make
`ci/run-ci.sh`'s summary table indistinguishable from a real regression on
an already-broken-in-a-known-way scenario; reporting it as SKIP instead
keeps it VISIBLE (never silently PASS) without conflating "this specific
run introduced new drift" with "this scenario has a pre-existing, tracked
authoring gap." The `_KNOWN_UNCOVERED_GAP` baseline is what makes that
distinction MECHANICAL rather than just prose: a NEW uncovered assert (the
exact shape of the demonstrated attack -- gutting one specific tier-1 rule
on a scenario that already has other, unrelated tracked gaps) widens the
gap past its recorded baseline and now fails this gate for real, instead of
disappearing into an unconditional SKIP. See ci/README.md for the current
per-scenario coverage state. Pure spec-model computation -- no toolchain,
no filesystem writes, no network; safe to run everywhere `make
validate-spec` runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spec_model import Arm, Spec, load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gates.oracle_falsifiability import predicted_tier  # noqa: E402


def tier1_assert_count(spec: Spec, arm: Arm) -> int:
    return sum(
        1 for a in spec.oracle.structural_asserts if a.tier == "1" and arm in a.applies_to
    )


def tier1_catch_count(spec: Spec, arm: Arm) -> int:
    return sum(1 for c in spec.catches if predicted_tier(c, arm) == "1")


# Recorded TRACKED gap (n_asserts - n_catches) per (spec_id, arm), as of
# 2026-08-06 round 2 -- see this module's own docstring for the FAIL-vs-
# SKIP distinction this baseline drives. A (spec_id, arm) pair not listed
# here is assumed to have baseline gap 0 -- i.e. it must fully meet the
# floor, or it is by definition NEW drift, not a tracked pre-existing gap.
# Shrink an entry's value (or delete it) as real covering fixtures land for
# that scenario/arm -- never widen one to silence a genuinely new gap;
# widening requires a matching new fixture-authoring commit, the same
# discipline `route-count-wrong` and sfn-jsonata's
# `raw-jsonpath-literal-value-only` extra fixture established.
_KNOWN_UNCOVERED_GAP: dict[tuple[str, str], int] = {
    ("ecs-swappiness", "awscdk"): 1,
    ("ecs-swappiness", "terraconstructs"): 1,
    ("sfn-jsonata", "awscdk"): 7,
    ("sfn-jsonata", "hcl_raw"): 6,
    ("toy-ssm-parameter", "awscdk"): 1,
    ("toy-ssm-parameter", "hcl_raw"): 1,
    ("toy-ssm-parameter", "terraconstructs"): 1,
}


def check_spec(spec: Spec) -> tuple[list[str], list[str]]:
    """Returns ``(tracked_problems, regressions)``. ``tracked_problems`` are
    gaps that do not exceed ``_KNOWN_UNCOVERED_GAP``'s recorded baseline for
    that (spec, arm) -- reported but non-gating (SKIP). ``regressions`` are
    gaps that exceed their baseline (or have no baseline entry at all) --
    gating (FAIL): either a brand-new spec/arm never checked in with a gap,
    or an existing one that got WORSE than the state this fix recorded."""
    tracked_problems: list[str] = []
    regressions: list[str] = []
    for arm in spec.arms.enabled_arms():
        n_asserts = tier1_assert_count(spec, arm)
        n_catches = tier1_catch_count(spec, arm)
        gap = n_asserts - n_catches
        if gap <= 0:
            continue
        baseline = _KNOWN_UNCOVERED_GAP.get((spec.id, arm), 0)
        msg = (
            f"{arm}: {n_asserts} tier-1 structural_assert(s) declared but only "
            f"{n_catches} catch(es) predict a tier-1 catch on this arm -- at "
            f"least {gap} tier-1 assert(s) have NO covering "
            "negative fixture and can be silently gutted without any "
            "falsifiability/grading-proof check ever noticing (pigeonhole)."
        )
        if gap > baseline:
            regressions.append(
                f"{msg} REGRESSION: gap={gap} exceeds the recorded baseline={baseline} "
                f"for ({spec.id!r}, {arm!r}) -- this is NEW drift, not a tracked gap "
                "(generator/check_tier1_coverage.py's own _KNOWN_UNCOVERED_GAP)."
            )
        else:
            tracked_problems.append(msg)
    return tracked_problems, regressions


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    args = parser.parse_args(argv[1:])
    spec = load_spec(args.spec_path)
    tracked_problems, regressions = check_spec(spec)
    for arm in spec.arms.enabled_arms():
        n_asserts = tier1_assert_count(spec, arm)
        n_catches = tier1_catch_count(spec, arm)
        status = "PASS" if n_asserts <= n_catches else "FAIL"
        print(f"[{status}] {arm}: {n_asserts} tier-1 assert(s), {n_catches} covering catch(es)")
    if regressions:
        print(
            f"\ntier1-coverage: FAIL for {spec.id!r} -- NEW, untracked tier-1 coverage "
            "gap(s) (gating -- see this script's own module docstring):",
            file=sys.stderr,
        )
        for p in regressions:
            print(f"  {p}", file=sys.stderr)
        if tracked_problems:
            print("\n  (also has these pre-existing, tracked gaps, unaffected):", file=sys.stderr)
            for p in tracked_problems:
                print(f"  {p}", file=sys.stderr)
        return 1
    if tracked_problems:
        print(
            f"\ntier1-coverage: SKIP for {spec.id!r} -- floor not met but within the "
            "tracked baseline (non-gating; see this script's own module docstring for "
            "why this is SKIP, not FAIL):",
            file=sys.stderr,
        )
        for p in tracked_problems:
            print(f"  {p}", file=sys.stderr)
        return 3
    print(f"\ntier1-coverage OK for {spec.id!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
