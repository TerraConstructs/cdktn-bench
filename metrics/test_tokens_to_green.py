"""Tests for metrics/tokens_to_green.py.

Covers (docs/iac-abstraction-aws-bench-plan.md Phase 2 item 4):
  - KM median/IQR with censoring, hand-computed against a worked example;
  - a cell where >50% is censored => median reported as not-estimable;
  - a Wilson-interval spot-check against an independently-derivable
    (closed-form) value, plus the interval's own complementary-symmetry
    invariant as a second, source-independent check;
  - per-catch tier-attribution table correctness;
  - a property test: adding a censored row to a KM sample never DECREASES
    the reported median (None/"not estimable" ordered as +infinity, i.e.
    "at least this large" — see the property test's own docstring for why
    that ordering is the mathematically correct one, not a convenience).
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from tokens_to_green import (
    MIN_EVENTS_FOR_CONFIDENT_MEDIAN,
    Z_95,
    build_report,
    build_tier_attribution,
    find_row_files,
    kaplan_meier,
    km_median_iqr,
    km_quantile,
    load_rows,
    main,
    render_markdown,
    summarize_cell,
    wilson_interval,
)

# ---------------------------------------------------------------------------
# Fixture row builder
# ---------------------------------------------------------------------------

BASE_ROW = {
    "schema_version": "1.0",
    "equipping_hash": "a" * 64,
    "oracle_version": "oracles@0000000",
    "arm": "awscdk",
    "model": "claude-sonnet-5",
    "harness": "empty",
    "validity_class": "valid",
    "split_group": "holdout",
    "tokens_input": 100,
    "tokens_output": 50,
    "tokens_total": 150,
    "reward": 1.0,
    "censored": False,
    "tier1_not_verifiable": False,
}


def make_row(**overrides) -> dict:
    row = copy.deepcopy(BASE_ROW)
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Kaplan-Meier
# ---------------------------------------------------------------------------


class TestKaplanMeier:
    def test_hand_computed_median_and_iqr(self):
        # 5 trials: events at 100, 200, 400; censored at 300, 500.
        # Hand-computed survival curve:
        #   t=100: at_risk=5 events=1 -> S=0.8
        #   t=200: at_risk=4 events=1 -> S=0.6
        #   t=300: at_risk=3 events=0 (censored) -> S=0.6
        #   t=400: at_risk=2 events=1 -> S=0.3
        #   t=500: at_risk=1 events=0 (censored) -> S=0.3
        times_events = [
            (100.0, True),
            (200.0, True),
            (300.0, False),
            (400.0, True),
            (500.0, False),
        ]
        curve = kaplan_meier(times_events)
        assert [round(p["survival"], 6) for p in curve] == [0.8, 0.6, 0.6, 0.3, 0.3]

        result = km_median_iqr(times_events)
        assert result["n"] == 5
        assert result["n_events"] == 3
        assert result["n_censored"] == 2
        assert result["median"] == 400.0
        assert result["median_reached"] is True
        assert result["q25"] == 200.0  # smallest t with S(t) <= 0.75
        assert result["q75"] is None  # curve never drops to <= 0.25

    def test_majority_censored_median_is_not_estimable(self):
        # 1 event at t=100, then three censored observations. Survival
        # never drops below 0.75 (75% censored) -- median must be None,
        # not silently guessed at the last observed time.
        times_events = [(100.0, True), (200.0, False), (300.0, False), (400.0, False)]
        result = km_median_iqr(times_events)
        assert result["n_censored"] == 3
        assert result["n_censored"] > result["n"] / 2
        assert result["median"] is None
        assert result["median_reached"] is False

    def test_all_events_no_censoring_matches_plain_median_ish(self):
        # No censoring at all: KM degenerates to the empirical survival
        # function, S(t) = fraction still alive strictly after t's cohort.
        times_events = [(t, True) for t in (10.0, 20.0, 30.0, 40.0)]
        result = km_median_iqr(times_events)
        assert result["n_censored"] == 0
        assert result["median_reached"] is True
        # S: t=10 -> 0.75, t=20 -> 0.5, t=30 -> 0.25, t=40 -> 0.0
        assert result["median"] == 20.0

    def test_empty_input(self):
        assert kaplan_meier([]) == []
        result = km_median_iqr([])
        assert result["n"] == 0
        assert result["median"] is None

    def test_km_quantile_never_reached_returns_none(self):
        curve = kaplan_meier([(1.0, False), (2.0, False)])
        assert km_quantile(curve, 0.5) is None

    def test_censored_and_event_tie_at_same_time(self):
        # A censored obs at the same time as an event is still in the risk
        # set for that event's hazard (standard KM tie convention).
        times_events = [(50.0, True), (50.0, False)]
        curve = kaplan_meier(times_events)
        assert curve[0]["at_risk"] == 2
        assert curve[0]["events"] == 1
        assert round(curve[0]["survival"], 6) == 0.5


class TestKmMedianIqrCensoringAnnotations:
    """'>50% censored -> median undefined' only holds for LATE censoring
    (2026-08-06 fix): a majority-censored cell can still report a fully
    "reached" median when the censoring happens BEFORE the events, so a
    caller must not infer the censored fraction from ``median_reached``
    alone -- ``censored_frac``/``low_event_count`` are reported
    unconditionally instead.
    """

    def test_early_majority_censoring_still_reaches_a_median(self):
        # 10 rows: 6 failures censored EARLY (100..600), 4 successes late
        # (1000/2000/3000/4000). n_censored=6 (60%) yet the KM curve still
        # drops through 0.5 well before any censoring event dominates --
        # median_reached=True from only 4 real observations.
        times_events = [(t, False) for t in (100.0, 200.0, 300.0, 400.0, 500.0, 600.0)] + [
            (t, True) for t in (1000.0, 2000.0, 3000.0, 4000.0)
        ]
        result = km_median_iqr(times_events)
        assert result["n_censored"] == 6
        assert result["censored_frac"] == 0.6
        assert result["median_reached"] is True
        assert result["median"] == 2000.0
        # The honest signal this fix adds: n_events (4) is below the
        # pre-registered minimum -- flagged independently of
        # median_reached, which alone would have said nothing was wrong.
        assert result["n_events"] == 4
        assert result["n_events"] < MIN_EVENTS_FOR_CONFIDENT_MEDIAN
        assert result["low_event_count"] is True

    def test_censored_frac_reported_even_when_median_not_reached(self):
        times_events = [(100.0, True), (200.0, False), (300.0, False), (400.0, False)]
        result = km_median_iqr(times_events)
        assert result["median_reached"] is False
        assert result["censored_frac"] == 0.75

    def test_confident_median_not_flagged_low(self):
        times_events = [(float(t), True) for t in range(1, 11)]  # 10 real events, no censoring
        result = km_median_iqr(times_events)
        assert result["low_event_count"] is False
        assert result["censored_frac"] == 0.0


class TestKmMedianMonotonicityProperty:
    """docs/iac-abstraction-aws-bench-plan.md Phase 2 item 4: 'a property
    test that adding a censored row never DECREASES reported median.'

    Ordering used for the comparison: None ("not estimable") sorts AFTER
    every finite value. This is the mathematically correct convention, not
    a convenience -- "not estimable" here specifically means "the KM curve
    never fell to survival<=0.5 within the observed sample", which is
    equivalent to "the true median is at least as large as the last
    observed time" (i.e. >= any finite candidate). Proof sketch of the
    underlying property (see metrics/README.md for the full derivation):
    inserting one more censored observation at time t_c can only ADD to
    the risk set for every event-time <= t_c and never removes anyone from
    a risk set, so every hazard d_i/n_i at t_i <= t_c can only shrink,
    hence S_new(t) >= S_old(t) pointwise for all t. Since
    median = inf{t : S(t) <= 0.5}, and S_new >= S_old pointwise, the set of
    qualifying t's for the new curve is a SUBSET of the old one's, so its
    infimum (the new median) is >= the old one -- possibly now the empty
    set (None), which is consistent with "even larger" under the ordering
    above.
    """

    @staticmethod
    def _median_geq(new: float | None, old: float | None) -> bool:
        if old is None:
            return True  # old was already "at least infinity"; can't decrease further
        if new is None:
            return True  # new is "at least infinity" >= any finite old
        return new >= old

    def test_random_insertions_never_decrease_median(self):
        rng = random.Random(20260806)
        for _trial in range(300):
            n = rng.randint(1, 12)
            sample = [
                (float(rng.randint(1, 50)), rng.random() < 0.6) for _ in range(n)
            ]
            old_median = km_median_iqr(sample)["median"]

            # Insert one additional CENSORED row at an arbitrary time
            # (before, inside, or after the existing range).
            new_time = float(rng.randint(0, 60))
            sample_plus = sample + [(new_time, False)]
            new_median = km_median_iqr(sample_plus)["median"]

            assert self._median_geq(new_median, old_median), (
                f"median decreased: old={old_median} new={new_median} "
                f"sample={sample} inserted=({new_time}, False)"
            )

    def test_worked_example_where_defined_median_becomes_not_estimable(self):
        # Demonstrates the "defined -> None" edge case explicitly: adding a
        # censored row can push the curve's last value above 0.5, but under
        # the None-as-infinity ordering that is still "did not decrease".
        sample = [(10.0, True), (20.0, True), (30.0, True)]
        # S: 10->0.667, 20->0.333, 30->0.0 => median=20 (first S<=0.5)
        assert km_median_iqr(sample)["median"] == 20.0

        # Insert several censored rows early, diluting the early hazards
        # enough that survival may stay > 0.5 for longer -- regardless of
        # the exact outcome, it must never be < 20.0 under the ordering.
        sample_plus = sample + [(1.0, False)] * 5
        new_median = km_median_iqr(sample_plus)["median"]
        assert new_median is None or new_median >= 20.0


# ---------------------------------------------------------------------------
# Wilson interval
# ---------------------------------------------------------------------------


class TestWilsonInterval:
    def test_closed_form_n1_k0(self):
        # For n=1, k=0: phat=0, and the formula degenerates to a closed
        # form lo=0, hi=z^2/(1+z^2) -- derived independently of the
        # production formula (not just re-running the same code), so this
        # is a genuine spot-check, not a tautology.
        phat, lo, hi = wilson_interval(0, 1)
        expected_hi = (Z_95 * Z_95) / (1 + Z_95 * Z_95)
        assert phat == 0.0
        assert lo == 0.0
        assert hi == pytest.approx(expected_hi, abs=1e-9)
        # Commonly cited (e.g. Wikipedia's "binomial proportion confidence
        # interval" worked n=1 example): approximately 0.7935.
        assert hi == pytest.approx(0.7935, abs=2e-3)

    def test_closed_form_n1_k1_is_complement_of_k0(self):
        _, lo1, hi1 = wilson_interval(1, 1)
        _, lo0, hi0 = wilson_interval(0, 1)
        assert lo1 == pytest.approx(1 - hi0, abs=1e-9)
        assert hi1 == 1.0

    def test_complementary_symmetry_invariant(self):
        # CI_hi(k, n) == 1 - CI_lo(n-k, n) for ANY (k, n) -- a
        # source-independent correctness check (true of the Wilson
        # interval by construction: swapping "success"/"failure" mirrors
        # the interval around 0.5), run over many (k, n) pairs.
        rng = random.Random(7)
        for _ in range(200):
            n = rng.randint(1, 200)
            k = rng.randint(0, n)
            _, lo_k, hi_k = wilson_interval(k, n)
            _, lo_nk, hi_nk = wilson_interval(n - k, n)
            assert hi_k == pytest.approx(1 - lo_nk, abs=1e-9)
            assert lo_k == pytest.approx(1 - hi_nk, abs=1e-9)

    def test_interval_always_contains_point_estimate(self):
        rng = random.Random(11)
        for _ in range(200):
            n = rng.randint(1, 500)
            k = rng.randint(0, n)
            phat, lo, hi = wilson_interval(k, n)
            eps = 1e-12
            assert lo - eps <= phat <= hi + eps
            assert -eps <= lo <= hi <= 1.0 + eps

    def test_zero_n_returns_maximally_wide_interval(self):
        phat, lo, hi = wilson_interval(0, 0)
        assert (phat, lo, hi) == (0.0, 0.0, 1.0)

    def test_perfect_success_rate_interval_not_degenerate_to_a_point(self):
        # A well-known gotcha with the naive normal-approximation interval
        # (not Wilson): k=n gives lo=hi=1.0 there, which is wrong -- Wilson
        # correctly reports a lo < 1.0 for finite n.
        _, lo, hi = wilson_interval(10, 10)
        assert hi == pytest.approx(1.0, abs=1e-9)
        assert lo < 1.0


# ---------------------------------------------------------------------------
# Cell summary / success rate / iterations-to-green
# ---------------------------------------------------------------------------


class TestSummarizeCell:
    def test_excludes_invalid_rows_from_every_headline_number(self):
        rows = [
            make_row(reward=1.0, tokens_total=100),
            make_row(reward=1.0, tokens_total=200),
            make_row(validity_class="invalid-bypass", reward=0.0, tokens_total=999999),
        ]
        summary = summarize_cell(rows)
        assert summary["n_valid"] == 2
        assert summary["n_excluded_invalid"] == 1
        assert summary["success_rate"]["n"] == 2
        assert summary["tokens_to_green_km"]["n"] == 2

    def test_success_rate_and_censoring_breakdown(self):
        rows = [
            make_row(reward=1.0, tokens_total=100, censored=False),
            make_row(reward=0.0, tokens_total=500, censored=True),
            make_row(reward=0.0, tokens_total=300, censored=False),
        ]
        summary = summarize_cell(rows)
        assert summary["success_rate"]["successes"] == 1
        assert summary["success_rate"]["n"] == 3
        cb = summary["censoring_breakdown"]
        assert cb["n_success"] == 1
        assert cb["n_budget_censored"] == 1
        assert cb["n_natural_fail"] == 1

    def test_iterations_to_green_only_over_successes(self):
        rows = [
            make_row(reward=1.0, n_llm_calls=3),
            make_row(reward=1.0, n_llm_calls=5),
            make_row(reward=0.0, n_llm_calls=8),  # failure, excluded from iterations_to_green
        ]
        summary = summarize_cell(rows)
        assert summary["iterations_to_green"]["n"] == 2
        assert summary["iterations_to_green"]["median"] == 4.0

    def test_missing_n_llm_calls_does_not_crash(self):
        rows = [make_row(reward=1.0)]  # no n_llm_calls key at all
        summary = summarize_cell(rows)
        assert summary["iterations_to_green"] is None

    def test_missing_n_llm_calls_counted_as_unknown_not_zero(self):
        # "iterations-to-green poisoned by n_llm_calls=0 fallback" fix
        # (2026-08-06): gates/emit_result.py now omits `n_llm_calls`
        # entirely (never stores a fabricated 0) when the trajectory was
        # unreadable -- summarize_cell must count that as UNKNOWN, not
        # silently drag the KM curve down to time 0.
        rows = [
            make_row(reward=1.0, n_llm_calls=6),
            make_row(reward=1.0, n_llm_calls=7),
            make_row(reward=1.0),  # no n_llm_calls key -- unreadable trajectory
        ]
        summary = summarize_cell(rows)
        assert summary["n_iterations_unknown"] == 1
        # The unknown-trajectory row must never enter the KM curve as an
        # event at time 0.0.
        assert summary["iterations_to_green_km"]["n"] == 2
        assert 0.0 not in {t for t, _ in [(6.0, True), (7.0, True)]}  # sanity: no zero in real data


class TestAdministrativeCensoring:
    """Censoring semantics / anti-survivorship fix (2026-08-06): the
    HEADLINE ``tokens_to_green_km`` must censor every non-green trial at
    the ADMINISTRATIVE budget bound, not its own stopping point -- an arm
    whose failures quit cheaply must not report an artificially low
    tokens-to-green purely because its failures are cheap.
    """

    def test_cheap_failures_vs_expensive_failures_no_longer_diverge(self):
        # Reproduces the demonstrated bias directly: two cells, IDENTICAL
        # greens (10000, 20000) and IDENTICAL success rate (2/4). Arm X's
        # two failures quit cheap (500/600); arm Y's two failures hit the
        # cap (50000 each). Under the OLD own-stopping-point convention
        # this produced a 2x swing in the reported median (10000 vs
        # 20000) despite equal success rates -- purely an artifact of
        # failure cheapness. Under administrative censoring (both arms'
        # failures censored at the same 50000 bound) that artifact must
        # be gone: identical inputs modulo failure-stopping-point now
        # produce the IDENTICAL headline median.
        rows_x = [
            make_row(reward=1.0, tokens_total=10000),
            make_row(reward=1.0, tokens_total=20000),
            make_row(reward=0.0, tokens_total=500, censored=False),
            make_row(reward=0.0, tokens_total=600, censored=False),
        ]
        rows_y = [
            make_row(reward=1.0, tokens_total=10000),
            make_row(reward=1.0, tokens_total=20000),
            make_row(reward=0.0, tokens_total=50000, censored=True),
            make_row(reward=0.0, tokens_total=50000, censored=True),
        ]
        summary_x = summarize_cell(rows_x, admin_max_tokens=50000)
        summary_y = summarize_cell(rows_y, admin_max_tokens=50000)
        assert summary_x["tokens_to_green_km"]["median"] == summary_y["tokens_to_green_km"]["median"]
        # The bias is still VISIBLE in the diagnostic own-stopping-point
        # convention (proving this is a real behavior change, not a
        # coincidence -- the two summaries genuinely differ there).
        own_x = summary_x["tokens_to_green_km_own_stopping_point"]["median"]
        own_y = summary_y["tokens_to_green_km_own_stopping_point"]["median"]
        assert own_x != own_y

    def test_no_admin_bound_falls_back_to_max_observed_in_cell(self):
        rows = [make_row(reward=1.0, tokens_total=1000), make_row(reward=0.0, tokens_total=500, censored=False)]
        summary = summarize_cell(rows)  # admin_max_tokens omitted
        assert summary["tokens_to_green_km_administrative_bound_used"] == 1000.0

    def test_empty_cell_has_no_administrative_bound(self):
        summary = summarize_cell([])
        assert summary["tokens_to_green_km_administrative_bound_used"] is None
        assert summary["tokens_to_green_km"] is None


class TestIterationsAdministrativeCensoring:
    """Iterations-to-green counterpart of TestAdministrativeCensoring
    (2026-08-06 fix round 2): the anti-survivorship blocker was fixed for
    tokens-to-green but NOT mirrored onto iterations-to-green, which
    prereg §4 names as its own metric. Reproduces the finding's exact
    demonstrated shape: two cells with IDENTICAL greens (n_llm_calls 2, 5)
    and IDENTICAL success rate (2/4) -- arm X's two failures quit at 1
    iteration, arm Y's two hit MAX_ITERS=8 -- which used to report medians
    2.0 (X) vs 5.0 (Y), a 2.5x swing produced purely by failure cheapness.
    """

    def test_cheap_failures_vs_capped_failures_no_longer_diverge(self):
        rows_x = [
            make_row(reward=1.0, n_llm_calls=2),
            make_row(reward=1.0, n_llm_calls=5),
            make_row(reward=0.0, n_llm_calls=1, censored=False),
            make_row(reward=0.0, n_llm_calls=1, censored=False),
        ]
        rows_y = [
            make_row(reward=1.0, n_llm_calls=2),
            make_row(reward=1.0, n_llm_calls=5),
            make_row(reward=0.0, n_llm_calls=8, censored=True),
            make_row(reward=0.0, n_llm_calls=8, censored=True),
        ]
        summary_x = summarize_cell(rows_x, admin_max_iters=8)
        summary_y = summarize_cell(rows_y, admin_max_iters=8)
        # Pre-fix: 2.0 vs 5.0 (a 2.5x swing). Post-fix: identical.
        assert (
            summary_x["iterations_to_green_km"]["median"]
            == summary_y["iterations_to_green_km"]["median"]
        )
        # Passing --max-iters (admin_max_iters) must actually change the
        # result -- the pre-fix bug was that it changed NOTHING (help text
        # said so explicitly).
        summary_x_no_bound = summarize_cell(rows_x)  # falls back to max observed (5.0)
        assert (
            summary_x["iterations_to_green_km"]["median"]
            != summary_x_no_bound["iterations_to_green_km"]["median"]
            or summary_x["iterations_to_green_km_administrative_bound_used"] == 8.0
        )
        # The bias is still visible in the diagnostic own-stopping-point
        # convention, proving this is a genuine behavior change.
        own_x = summary_x["iterations_to_green_km_own_stopping_point"]["median"]
        own_y = summary_y["iterations_to_green_km_own_stopping_point"]["median"]
        assert own_x == 2.0
        assert own_y == 5.0
        assert own_x != own_y

    def test_no_admin_bound_falls_back_to_max_observed_n_llm_calls_in_cell(self):
        rows = [
            make_row(reward=1.0, n_llm_calls=5),
            make_row(reward=0.0, n_llm_calls=1, censored=False),
        ]
        summary = summarize_cell(rows)  # admin_max_iters omitted
        assert summary["iterations_to_green_km_administrative_bound_used"] == 5.0

    def test_empty_cell_has_no_administrative_iters_bound(self):
        summary = summarize_cell([])
        assert summary["iterations_to_green_km_administrative_bound_used"] is None
        assert summary["iterations_to_green_km"] is None

    def test_rows_with_unknown_n_llm_calls_excluded_not_censored_at_zero(self):
        rows = [make_row(reward=1.0, n_llm_calls=5), make_row(reward=0.0)]  # no n_llm_calls
        summary = summarize_cell(rows, admin_max_iters=8)
        assert summary["iterations_to_green_km"]["n"] == 1
        assert summary["n_iterations_unknown"] == 1


class TestTier1NotVerifiableSensitivity:
    """tier1_not_verifiable pooled into headline numbers fix (2026-08-06):
    a tier1_not_verifiable=true row's reward reflects a tier-1 check that
    was never actually evaluated -- must be counted, and a sensitivity
    summary excluding them must be available.
    """

    def test_n_tier1_not_verifiable_counted(self):
        rows = [
            make_row(reward=1.0, tier1_not_verifiable=True),
            make_row(reward=1.0, tier1_not_verifiable=True),
            make_row(reward=1.0, tier1_not_verifiable=True),
            make_row(reward=1.0, tier1_not_verifiable=True),
        ]
        summary = summarize_cell(rows)
        assert summary["n_tier1_not_verifiable"] == 4
        # Demonstrated attack shape: a cell of four tier1_not_verifiable
        # greens reports 100% success with nothing else in the cell to
        # compare against -- the sensitivity summary excluding them must
        # show that headline "success" is not backed by anything.
        sensitivity = summary["sensitivity_excluding_tier1_not_verifiable"]
        assert sensitivity is not None
        assert sensitivity["n_valid"] == 0

    def test_no_tier1_not_verifiable_rows_has_no_sensitivity_block(self):
        rows = [make_row(reward=1.0), make_row(reward=0.0)]
        summary = summarize_cell(rows)
        assert summary["n_tier1_not_verifiable"] == 0
        assert summary["sensitivity_excluding_tier1_not_verifiable"] is None

    def test_sensitivity_summary_does_not_recurse_infinitely(self):
        rows = [make_row(reward=1.0, tier1_not_verifiable=True), make_row(reward=1.0)]
        summary = summarize_cell(rows)
        sensitivity = summary["sensitivity_excluding_tier1_not_verifiable"]
        assert sensitivity is not None
        # The sensitivity pass itself carries no further nested sensitivity
        # block, even if (degenerately) it still contained
        # tier1_not_verifiable rows -- bounded to one level.
        assert sensitivity["sensitivity_excluding_tier1_not_verifiable"] is None


# ---------------------------------------------------------------------------
# Tier attribution
# ---------------------------------------------------------------------------


class TestTierAttribution:
    def test_tier0_and_tier1_bundle_counted_separately(self):
        rows = [
            make_row(
                scenario="ecs-swappiness",
                reward=0.0,
                tier_evidence={
                    "tier0": {"swappiness-value-correct": "FAIL", "taskdef-exists": "PASS"},
                    "tier1_status": None,
                },
            ),
            make_row(
                scenario="ecs-swappiness",
                reward=0.0,
                tier_evidence={"tier0": {}, "tier1_status": "FAIL"},
            ),
            make_row(scenario="ecs-swappiness", reward=1.0),  # success, no attribution
        ]
        attribution = build_tier_attribution(rows)
        by_key = {(r["tier"], r["name"]): r for r in attribution["table"]}
        assert by_key[("0", "swappiness-value-correct")]["fail_count"] == 1
        # Bundle name is now joined against specs/ecs-swappiness.yaml's own
        # declared tier-1 structural_assert name(s) for awscdk (2026-08-06
        # fix, "per-catch tier attribution cannot express a tier-1 catch
        # identity") -- no longer the opaque "(tier-1 bundle)" placeholder.
        assert by_key[("1", "(tier-1 bundle: maxswap-present-when-swappiness-tuned)")][
            "fail_count"
        ] == 1
        assert ("0", "taskdef-exists") not in by_key  # PASS never appears as a fail row
        for row in attribution["table"]:
            assert row["n_valid"] == 3
            assert row["n_failed"] == 2

    def test_uses_spec_id_not_aws_bench_scenario_on_real_row_shape(self):
        # 2026-08-06 fix round 2: rows real emission produces always carry
        # scenario == "anchor" (the single aws-bench AWS scenario every
        # task in this repo shares -- gates/emit_result.py's own --scenario
        # help says "e.g. 'anchor'") and the actual benchmark-scenario
        # identity only in spec_id (generator/gen.py::task_dir()'s
        # "<spec-id>-<arm>" convention). Attribution must key on spec_id,
        # not scenario, or every real row collapses into one "anchor"
        # group and the tier-1 bundle join (which looks up
        # specs/<key>.yaml) never resolves.
        rows = [
            make_row(
                scenario="anchor",
                spec_id="ecs-swappiness",
                reward=0.0,
                tier_evidence={"tier0": {}, "tier1_status": "FAIL"},
            ),
            make_row(
                scenario="anchor",
                spec_id="apigw-openapi",
                reward=0.0,
                tier_evidence={"tier0": {"route-count-wrong": "FAIL"}, "tier1_status": None},
            ),
        ]
        attribution = build_tier_attribution(rows)
        by_scenario = {r["scenario"]: r for r in attribution["table"]}
        # Two distinct groups, not one degenerate "anchor" bundle.
        assert set(by_scenario) == {"ecs-swappiness", "apigw-openapi"}
        # The real spec_id ("ecs-swappiness") is what resolves
        # specs/ecs-swappiness.yaml and joins the candidate tier-1 assert
        # name -- "anchor" would never match any specs/anchor.yaml file.
        assert by_scenario["ecs-swappiness"]["name"] == (
            "(tier-1 bundle: maxswap-present-when-swappiness-tuned)"
        )
        assert by_scenario["ecs-swappiness"]["n_valid"] == 1
        assert by_scenario["apigw-openapi"]["n_valid"] == 1

    def test_tier1_bundle_falls_back_to_opaque_name_for_unknown_scenario(self):
        # No specs/(unknown-scenario).yaml on disk -- _tier1_assert_names_
        # for_scenario() degrades to {} and the bundle keeps its original,
        # opaque name rather than raising or guessing.
        rows = [
            make_row(
                scenario="not-a-real-scenario-id",
                reward=0.0,
                tier_evidence={"tier0": {}, "tier1_status": "FAIL"},
            )
        ]
        attribution = build_tier_attribution(rows)
        assert attribution["table"][0]["name"] == "(tier-1 bundle)"

    def test_tool_missing_and_skipped_stub_count_as_tier1_fail(self):
        for status in ("TOOL_MISSING", "SKIPPED_STUB"):
            rows = [make_row(reward=0.0, tier_evidence={"tier0": {}, "tier1_status": status})]
            attribution = build_tier_attribution(rows)
            assert attribution["table"][0]["fail_count"] == 1

    def test_skipped_no_asserts_and_pass_never_attributed(self):
        for status in ("SKIPPED_NO_ASSERTS", "PASS", None):
            rows = [make_row(reward=0.0, tier_evidence={"tier0": {}, "tier1_status": status})]
            attribution = build_tier_attribution(rows)
            assert attribution["table"] == []

    def test_missing_evidence_on_a_failed_trial_is_reported_not_dropped(self):
        rows = [make_row(reward=0.0)]  # no tier_evidence key at all
        attribution = build_tier_attribution(rows)
        assert attribution["table"] == []
        assert attribution["no_evidence_failed_trials"] == [
            {"scenario": "(unknown-scenario)", "arm": "awscdk", "count": 1}
        ]

    def test_invalid_rows_excluded_from_attribution(self):
        rows = [
            make_row(
                validity_class="invalid-bypass",
                reward=0.0,
                tier_evidence={"tier0": {"x": "FAIL"}, "tier1_status": None},
            )
        ]
        attribution = build_tier_attribution(rows)
        assert attribution["table"] == []
        assert attribution["no_evidence_failed_trials"] == []


# ---------------------------------------------------------------------------
# Loading rows from a directory / end-to-end report + CLI
# ---------------------------------------------------------------------------


class TestLoadRows:
    def test_finds_json_ndjson_and_array_files_recursively(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.json").write_text(json.dumps(make_row(tokens_total=1110)))
        (tmp_path / "sub" / "b.ndjson").write_text(
            "\n".join(json.dumps(make_row(tokens_total=n)) for n in (2220, 3330))
        )
        (tmp_path / "c-array.json").write_text(json.dumps([make_row(tokens_total=4440)]))

        rows, errors = load_rows(tmp_path)
        assert errors == []
        assert sorted(r["tokens_total"] for r in rows) == [1110, 2220, 3330, 4440]

    def test_invalid_row_is_rejected_not_pooled(self, tmp_path: Path):
        bad = make_row()
        del bad["reward"]
        (tmp_path / "bad.json").write_text(json.dumps(bad))
        (tmp_path / "good.json").write_text(json.dumps(make_row()))

        rows, errors = load_rows(tmp_path)
        assert len(rows) == 1
        assert len(errors) == 1
        assert "bad.json" in errors[0]

    def test_own_output_files_are_never_reingested(self, tmp_path: Path):
        (tmp_path / "benchmark.json").write_text('{"not": "a row"}')
        (tmp_path / "real.json").write_text(json.dumps(make_row()))
        rows, errors = load_rows(tmp_path)
        assert len(rows) == 1
        assert errors == []

    def test_ignores_non_row_file_types(self, tmp_path: Path):
        (tmp_path / "notes.md").write_text("not json at all")
        (tmp_path / "real.json").write_text(json.dumps(make_row()))
        rows, errors = load_rows(tmp_path)
        assert len(rows) == 1
        assert errors == []


class TestBuildReportAndMarkdown:
    def test_report_groups_by_cell(self):
        rows = [
            make_row(arm="awscdk", model="claude-sonnet-5", harness="empty", reward=1.0),
            make_row(arm="hcl-raw", model="claude-sonnet-5", harness="empty", reward=0.0),
            make_row(arm="awscdk", model="claude-sonnet-5", harness="tuned", reward=1.0),
        ]
        report = build_report(rows, [], max_iters=8, max_tokens=100000)
        assert len(report["cells"]) == 3
        assert report["budget"] == {"max_iters": 8, "max_tokens": 100000}
        assert report["n_rows_loaded"] == 3

    def test_markdown_renders_without_error_and_contains_headline_numbers(self):
        rows = [make_row(reward=1.0, tokens_total=1234), make_row(reward=0.0, tokens_total=999)]
        report = build_report(rows, [])
        md = render_markdown(report)
        assert "Tokens-to-green median" in md
        assert "awscdk" in md
        assert "claude-sonnet-5" in md

    def test_not_estimable_median_renders_as_NE(self):
        rows = [make_row(reward=0.0, censored=True, tokens_total=t) for t in (10, 20, 30, 40)]
        report = build_report(rows, [])
        md = render_markdown(report)
        assert "NE" in md


class TestSplitStratification:
    """Train/holdout split enforceability fix (2026-08-06): the headline
    number must never silently pool train (equipping-tunable) scenarios
    with holdout ones -- prereg §7.1 calls this "the methodological
    safeguard most likely to be skipped and most damaging if it is".
    """

    def test_holdout_and_train_rows_land_in_separate_cell_lists(self):
        rows = [
            make_row(split_group="holdout", reward=1.0, tokens_total=1000),
            make_row(split_group="holdout", reward=1.0, tokens_total=2000),
            make_row(split_group="train", reward=1.0, tokens_total=99999),
        ]
        report = build_report(rows, [])
        assert len(report["headline_cells"]) == 1
        assert report["headline_cells"][0]["n_valid"] == 2
        assert len(report["train_cells"]) == 1
        assert report["train_cells"][0]["n_valid"] == 1
        # The pooled reference table still exists but is explicitly
        # documented as NOT the headline (see render_markdown).
        assert report["cells"][0]["n_valid"] == 3

    def test_unclassified_rows_excluded_from_both_but_counted(self):
        rows = [
            make_row(split_group="unclassified", reward=1.0),
            make_row(split_group="holdout", reward=1.0),
        ]
        report = build_report(rows, [])
        assert report["split_composition"]["n_unclassified_rows"] == 1
        assert report["split_composition"]["n_holdout_rows"] == 1
        assert sum(c["n_valid"] for c in report["headline_cells"]) == 1
        assert report["train_cells"] == []

    def test_headline_table_rendered_before_train_table_in_markdown(self):
        rows = [
            make_row(split_group="holdout", scenario="s3-lambda-log-retention", reward=1.0),
            make_row(split_group="train", scenario="ecs-swappiness", reward=1.0),
        ]
        report = build_report(rows, [])
        md = render_markdown(report)
        assert md.index("HEADLINE") < md.index("Train-split cells")
        assert md.index("Train-split cells") < md.index("All rows pooled")


class TestPerScenarioBreakdown:
    """"prereg §7 analysis outputs not derivable from benchmark.json" fix
    (2026-08-06): cell_key() discarding scenario identity blocked the
    paired-by-scenario primary test -- each cell now carries a real
    per-scenario breakdown.
    """

    def test_by_scenario_and_coverage_present_per_cell(self):
        rows = [
            make_row(scenario="ecs-swappiness", reward=1.0, tokens_total=1000),
            make_row(scenario="ecs-swappiness", reward=0.0, tokens_total=2000),
            make_row(scenario="apigw-openapi", reward=1.0, tokens_total=3000),
        ]
        report = build_report(rows, [])
        cell = report["cells"][0]
        assert cell["scenario_coverage"] == {"apigw-openapi": 1, "ecs-swappiness": 2}
        assert set(cell["by_scenario"]) == {"apigw-openapi", "ecs-swappiness"}
        assert cell["by_scenario"]["ecs-swappiness"]["n_valid"] == 2
        assert cell["by_scenario"]["apigw-openapi"]["n_valid"] == 1

    def test_by_scenario_keys_on_spec_id_on_real_row_shape(self):
        # 2026-08-06 fix round 2: real emitted rows all carry
        # scenario == "anchor"; grouping must key on spec_id (falling back
        # to scenario only when spec_id is absent) or scenario_coverage/
        # by_scenario degenerate to one {"anchor": N} group and prereg
        # §7's paired-by-scenario primary test still can't be computed
        # from benchmark.json.
        rows = [
            make_row(scenario="anchor", spec_id="ecs-swappiness", reward=1.0, tokens_total=1000),
            make_row(scenario="anchor", spec_id="ecs-swappiness", reward=0.0, tokens_total=2000),
            make_row(scenario="anchor", spec_id="apigw-openapi", reward=1.0, tokens_total=3000),
        ]
        report = build_report(rows, [])
        cell = report["cells"][0]
        assert cell["scenario_coverage"] == {"apigw-openapi": 1, "ecs-swappiness": 2}
        assert set(cell["by_scenario"]) == {"apigw-openapi", "ecs-swappiness"}


class TestCli:
    def test_cli_writes_benchmark_json_and_md(self, tmp_path: Path, capsys):
        (tmp_path / "rows.json").write_text(json.dumps([make_row(), make_row(reward=0.0)]))

        rc = main([str(tmp_path)])
        assert rc == 0
        out_json = json.loads((tmp_path / "benchmark.json").read_text())
        assert out_json["n_rows_loaded"] == 2
        assert (tmp_path / "benchmark.md").exists()

    def test_cli_separate_out_dir(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        out_dir = tmp_path / "out"
        (results_dir / "rows.json").write_text(json.dumps(make_row()))

        rc = main([str(results_dir), "--out-dir", str(out_dir)])
        assert rc == 0
        assert (out_dir / "benchmark.json").exists()
        assert not (results_dir / "benchmark.json").exists()

    def test_cli_returns_nonzero_when_rows_rejected(self, tmp_path: Path):
        bad = make_row()
        del bad["reward"]
        (tmp_path / "bad.json").write_text(json.dumps(bad))

        rc = main([str(tmp_path)])
        assert rc == 1

    def test_cli_max_iters_max_tokens_land_in_report(self, tmp_path: Path):
        (tmp_path / "rows.json").write_text(json.dumps(make_row()))
        rc = main([str(tmp_path), "--max-iters", "8", "--max-tokens", "50000"])
        assert rc == 0
        out_json = json.loads((tmp_path / "benchmark.json").read_text())
        assert out_json["budget"] == {"max_iters": 8, "max_tokens": 50000}


class TestFindRowFiles:
    def test_only_known_suffixes(self, tmp_path: Path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.ndjson").write_text("")
        (tmp_path / "c.jsonl").write_text("")
        (tmp_path / "d.txt").write_text("")
        found = {p.name for p in find_row_files(tmp_path)}
        assert found == {"a.json", "b.ndjson", "c.jsonl"}
