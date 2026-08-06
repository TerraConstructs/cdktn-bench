#!/usr/bin/env python3
"""metrics/tokens_to_green.py — the headline metric aggregator.

Implements docs/iac-abstraction-aws-bench-plan.md Phase 2 item 3 /
iac-abstraction-benchmark-prereg.md §4 (metrics/censoring) + §7 (analysis)
over a **directory of published result rows**
(``metrics/result_schema.json``-conformant JSON/NDJSON files, produced by
``gates/emit_result.py::to_result_row``):

  (a) censored tokens-to-green per cell (arm x model x harness): Kaplan-Meier
      median + IQR over ``tokens_total``, right-censored — a non-green
      trial (``reward < 1.0``) is treated as "event not yet observed by
      this many tokens", never dropped. The HEADLINE convention
      (2026-08-06 censoring-semantics fix) censors every non-green trial
      at the ADMINISTRATIVE budget bound (``--max-tokens``, else the max
      observed ``tokens_total`` in that cell), never at its own stopping
      point — prereg §4: "right-censored WITHIN THE BUDGET CAP", not
      wherever a trial happened to stop on its own. Censoring at a trial's
      own stopping point (the pre-fix behavior) is still computed and
      reported per cell as a diagnostic (``tokens_to_green_km_own_stopping_point``)
      but is NOT the headline: it lets an arm whose failures quit cheaply
      report an artificially low tokens-to-green purely because its
      failures are cheap, independent of its actual success rate;
  (b) success-rate-within-budget per cell with Wilson 95% intervals;
  (c) iterations-to-green distribution (order statistics over
      ``n_llm_calls`` on successful trials; a trial with an
      absent/unreadable trajectory contributes ``None``, counted under
      ``n_iterations_unknown``, never silently treated as zero);
  (d) per-catch tier-attribution table, from ``tier_evidence`` (see
      ``gates/emit_result.py::read_tier_evidence``'s docstring for the
      tier-0-real / tier-1-bundle-only caveat this table inherits) — the
      tier-1 bundle row is joined against the spec's own declared tier-1
      structural_assert names when resolvable, instead of an opaque
      placeholder;
  (e) train/holdout split stratification (prereg §7.1): ``headline_cells``
      (holdout-only — the pre-registered primary result) and
      ``train_cells`` (equipping-tunable scenarios, reported separately),
      never silently pooled into one number; each cell also carries a
      per-scenario breakdown (``by_scenario``/``scenario_coverage``) so a
      paired-by-scenario analysis (prereg §7) doesn't need to re-read raw
      rows;
  (f) ``tier1_not_verifiable`` accounting per cell (``n_tier1_not_verifiable``)
      plus a same-shaped sensitivity summary with those rows excluded, so
      a reader can see whether a headline result survives their removal
      (a tier1_not_verifiable=true row's reward reflects a tier-1 check
      that was never actually evaluated for it);
  (g) ``benchmark.json`` + ``benchmark.md`` output, mean±stddev-style
      tables mirroring aws-bench's own ``aggregate_detailed``
      (docs/aws-bench-guide.md §6).

**Why this is a standalone script, not a ``--metric uv-script:``** — see
metrics/README.md's "Verified upstream contract" section: the runner's
native ``--metric uv-script:`` hook (``harbor/metrics/uv_script.py``)
only ever gets a JSONL stream of bare reward dicts (or ``null``) — no
tokens, no trial id, no censoring flag, no scenario/arm/model label. It
cannot compute tokens-to-green by construction. This script instead reads
the richer rows this repo's own gate pipeline (``gates/emit_result.py``)
already produces.

CLI::

    uv run python metrics/tokens_to_green.py <results-dir> \\
        [--out-dir DIR] [--max-iters N] [--max-tokens N] [--green-threshold F]

Recursively finds every ``*.json``/``*.ndjson``/``*.jsonl`` file under
``<results-dir>``, parses each with the same JSON-object / JSON-array /
NDJSON tolerance ``metrics/validate_result.py`` uses, validates every row
against ``result_schema.json`` (a row failing validation is reported and
excluded, never silently pooled), and writes ``benchmark.json`` +
``benchmark.md`` into ``--out-dir`` (default: ``<results-dir>``).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from metrics.validate_result import _iter_rows, load_schema, validate_result  # noqa: E402

# A trial counts as "reached green" at/above this reward. 1.0 is the only
# value the reward contract (docs/aws-bench-guide.md §3) documents as a
# clean pass ("1.0 = pass, 0.0 = fail; partial credit permitted where a
# task's verifier defines it") — kept as a named constant, not a magic
# number, since a partial-credit verifier could motivate a different
# threshold later without touching every call site.
GREEN_THRESHOLD = 1.0

# norm.ppf(0.975) to full double precision — the two-sided 95% Wilson
# z-score. Hardcoded rather than imported from scipy (not a project
# dependency, pyproject.toml's dev group is pytest/pyyaml/jsonata-python/
# jsonpath-ng only) — this is a well-known constant, not a computed one.
Z_95 = 1.959963984540054


# ---------------------------------------------------------------------------
# Wilson score interval
# ---------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float, float]:
    """Wilson score 95% confidence interval for a binomial proportion.

    Returns ``(phat, lo, hi)``. ``n == 0`` returns ``(0.0, 0.0, 1.0)`` — the
    only honest interval when there is no data at all (maximally wide,
    point estimate undefined but reported as 0.0 rather than raising, so a
    caller building a table doesn't need a special-cased empty-cell branch).

    Formula (Wilson 1927, the standard score-interval form — NOT the naive
    normal-approximation interval, which undercoverages badly at small n or
    p near 0/1):

        center = (phat + z^2/2n) / (1 + z^2/n)
        halfwidth = z * sqrt(phat(1-phat)/n + z^2/4n^2) / (1 + z^2/n)

    Spot-checked in metrics/test_tokens_to_green.py against the closed-form
    n=1 special case (lo=0, hi=z^2/(1+z^2)) and the interval's own
    complementary symmetry (CI_hi(k, n) == 1 - CI_lo(n-k, n)) — see that
    test module for why those are the two independent checks used instead
    of trusting a single memorized "published" digit string.
    """
    if n == 0:
        return 0.0, 0.0, 1.0
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    halfwidth = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n)) / denom
    lo = max(0.0, center - halfwidth)
    hi = min(1.0, center + halfwidth)
    return phat, lo, hi


# ---------------------------------------------------------------------------
# Kaplan-Meier (right-censored product-limit estimator)
# ---------------------------------------------------------------------------


def kaplan_meier(times_events: list[tuple[float, bool]]) -> list[dict[str, float]]:
    """Product-limit (Kaplan-Meier) survival curve over right-censored data.

    ``times_events``: list of ``(time, is_event)``. ``is_event=True`` means
    the event (reaching green) was observed at ``time``; ``False`` means
    the observation was right-censored at ``time`` (event not observed by
    then, no further follow-up available — this repo treats BOTH a
    budget-cap hit and an agent-terminated non-green trial as censoring for
    KM purposes; see this module's own docstring and
    metrics/README.md for why that's the correct framing, not a
    simplification).

    Standard tie convention: an observation censored at exactly time ``t``
    is still counted in the risk set for the event-hazard computed AT
    ``t`` (i.e. "censored at t" is treated as "still under observation
    through t, then lost to follow-up"), and removed from the risk set for
    every time strictly greater than ``t``. Only distinct EVENT times
    produce a survival-curve step; distinct censoring-only times still
    shrink the risk set for later times but contribute no factor of their
    own.

    Returns a list of ``{"time", "at_risk", "events", "survival"}`` dicts,
    one per distinct time in the input (event or censoring), sorted
    ascending, S(t) implicitly 1.0 before the first row. Empty input ->
    empty list.
    """
    if not times_events:
        return []
    distinct_times = sorted({t for t, _ in times_events})
    curve: list[dict[str, float]] = []
    survival = 1.0
    for t in distinct_times:
        at_risk = sum(1 for tt, _ in times_events if tt >= t)
        events_here = sum(1 for tt, is_event in times_events if tt == t and is_event)
        if at_risk > 0 and events_here > 0:
            survival *= 1.0 - events_here / at_risk
        curve.append(
            {"time": t, "at_risk": at_risk, "events": events_here, "survival": survival}
        )
    return curve


def km_quantile(curve: list[dict[str, float]], survival_at_most: float) -> float | None:
    """Smallest ``time`` on the KM curve with ``survival <= survival_at_most``.

    ``None`` ("not reached") if no point on the curve ever drops that low —
    this is the honest, documented representation of "median undefined
    because more than half the sample is (effectively) censored before the
    empirical median would be reached" (docs/iac-abstraction-aws-bench-plan.md
    Phase 2 item 4's required test case).
    """
    for point in curve:
        if point["survival"] <= survival_at_most:
            return point["time"]
    return None


# Pre-registered minimum event count below which a KM median, even when
# "reached" (median_reached=True), should be read with caution -- see
# km_median_iqr's own docstring / the ">50% censored -> NE" finding
# (2026-08-06) this constant is part of fixing. Arbitrary but explicit: 5
# events is the smallest sample size order statistics conventionally treat
# as informative at all.
MIN_EVENTS_FOR_CONFIDENT_MEDIAN = 5


def km_median_iqr(times_events: list[tuple[float, bool]]) -> dict[str, Any]:
    """Censored median + IQR (Kaplan-Meier style) over ``times_events``.

    Returns::

        {
          "n": int, "n_events": int, "n_censored": int,
          "censored_frac": float,
          "median": float | None, "median_reached": bool,
          "low_event_count": bool,
          "q25": float | None, "q75": float | None,
        }

    ``median`` (and ``q25``/``q75``) is ``None`` when the KM curve never
    reaches the corresponding survival threshold — see ``km_quantile``.

    ``censored_frac`` / ``low_event_count`` (2026-08-06 fix, "'>50%
    censored -> median undefined' only holds for late censoring"): the
    claim "``median_reached=False`` (rendered ``NE``) is the honest
    representation of a majority-censored cell" is one-directional --
    ``NE`` implies majority-censored, but majority-censored does NOT imply
    ``NE`` when censoring happens EARLY (before the events, not after).
    Demonstrated: 10 rows, 6 failures censored at 100..600 and 4 greens at
    1000/2000/3000/4000 -> ``n_censored=6`` (60%) yet ``median_reached=True``,
    ``median=2000.0`` -- a fully confident-looking point estimate computed
    from only 4 observations, with nothing in the old return shape
    distinguishing it from a median computed over 400 observations.
    ``censored_frac`` is reported UNCONDITIONALLY (independent of whether
    the median was reached) so a caller/renderer can annotate on the
    censored FRACTION directly rather than inferring it (unreliably) from
    ``median_reached`` alone; ``low_event_count`` flags
    ``n_events < MIN_EVENTS_FOR_CONFIDENT_MEDIAN`` for the same reason.
    """
    n = len(times_events)
    n_events = sum(1 for _, is_event in times_events if is_event)
    n_censored = n - n_events
    curve = kaplan_meier(times_events)
    median = km_quantile(curve, 0.5)
    return {
        "n": n,
        "n_events": n_events,
        "n_censored": n_censored,
        "censored_frac": (n_censored / n) if n else 0.0,
        "median": median,
        "median_reached": median is not None,
        "low_event_count": n_events < MIN_EVENTS_FOR_CONFIDENT_MEDIAN,
        "q25": km_quantile(curve, 0.75),  # 25th percentile of TIME <=> S(t) <= 0.75
        "q75": km_quantile(curve, 0.25),  # 75th percentile of TIME <=> S(t) <= 0.25
    }


# ---------------------------------------------------------------------------
# Loading + validating result rows
# ---------------------------------------------------------------------------

_ROW_FILE_SUFFIXES = (".json", ".ndjson", ".jsonl")


def find_row_files(results_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in results_dir.rglob("*")
        if p.is_file() and p.suffix in _ROW_FILE_SUFFIXES
        # benchmark.json/metric.json are this script's OWN output — never
        # re-ingest a prior run's output as if it were input rows if
        # --out-dir happens to equal --results-dir (the CLI default).
        and p.name not in {"benchmark.json", "metric.json"}
    )


def load_rows(results_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load + schema-validate every result row under ``results_dir``.

    Returns ``(valid_rows, errors)``. A row failing schema validation is
    reported in ``errors`` (with its source label) and excluded from
    ``valid_rows`` — never silently pooled into a headline number, same
    discipline ``metrics/validate_result.py``'s own CLI enforces.
    """
    schema = load_schema()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in find_row_files(results_dir):
        try:
            parsed = list(_iter_rows(path))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for label, row in parsed:
            if not isinstance(row, dict):
                errors.append(f"{label}: top-level value must be a JSON object")
                continue
            row_errors = validate_result(row, schema)
            if row_errors:
                errors.append(f"{label}: " + "; ".join(row_errors))
                continue
            rows.append(row)
    return rows, errors


# ---------------------------------------------------------------------------
# Cell aggregation
# ---------------------------------------------------------------------------


def cell_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["arm"], row["model"], row["harness"]


def _order_stats(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    values = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "min": values[0],
        "max": values[-1],
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank-free linear-interpolation percentile over an
    already-sorted list — plain order statistics, deliberately NOT the KM
    estimator (that's what km_median_iqr is for); used only for the
    non-censoring-aware descriptive stats (iterations-to-green over
    successes only, and the "mean±stddev, uncensored" reference row in
    benchmark.md)."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_values[int(idx)]
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _tokens_km_administrative(
    valid_rows: list[dict[str, Any]], admin_bound: float | None
) -> dict[str, Any] | None:
    """Kaplan-Meier tokens-to-green, censoring every non-green trial at the
    ADMINISTRATIVE budget bound (``admin_bound``) rather than at its own
    stopping point -- the pre-registered convention (prereg §4: "Runs that
    never reach green WITHIN THE BUDGET CAP are right-censored").

    Fixes "censoring semantics / anti-survivorship" (2026-08-06): the
    original (still-computed, see ``tokens_to_green_km_own_stopping_point``
    below) convention censors a non-green trial at ITS OWN ``tokens_total``
    -- identical to a budget-cap hit for a censored=True row, but WRONG for
    a censored=False row that simply stopped on its own before the cap.
    Demonstrated: two cells with identical greens (10000, 20000) and
    identical success rate (2/4); arm X's two failures quit cheap
    (500/600), arm Y's two hit the cap (50000/50000) -- the own-stopping-
    point KM median comes out 10000 for X vs 20000 for Y, a 2x swing
    produced purely by X's failures being cheaper to fail, exactly the
    "the arm that fails more looks artificially cheap" artifact prereg §4
    calls non-negotiable. Censoring every non-green trial at the SAME
    administrative bound removes that artifact by construction (X and Y's
    non-green trials are both censored at the same time regardless of when
    they actually stopped).

    Returns ``None`` when ``admin_bound`` is ``None`` -- no MAX_TOKENS was
    supplied and no valid row exists to fall back to (see this module's own
    ``summarize_cell``, which resolves ``admin_bound`` as
    "explicit --max-tokens, else the max observed tokens_total in this
    cell" before calling this function).
    """
    if admin_bound is None:
        return None
    times_events = [
        (float(r["tokens_total"]), True)
        if r["reward"] >= GREEN_THRESHOLD
        else (float(admin_bound), False)
        for r in valid_rows
    ]
    return km_median_iqr(times_events)


def _iters_km_administrative(
    valid_rows: list[dict[str, Any]], admin_bound: float | None
) -> dict[str, Any] | None:
    """Kaplan-Meier iterations-to-green, censoring every non-green trial
    (with a known ``n_llm_calls``) at the ADMINISTRATIVE budget bound
    (``admin_bound``) rather than at its own stopping point — the
    iterations-to-green counterpart of ``_tokens_km_administrative``.

    Fixes "anti-survivorship blocker fixed for tokens-to-green but NOT for
    iterations-to-green" (2026-08-06 round 2): the pre-fix
    ``iterations_to_green_km`` censored every non-green trial at its OWN
    ``n_llm_calls`` -- identical to a budget-cap hit for a censored=True
    row, but WRONG for a censored=False row that simply stopped on its own
    before the cap, reproducing the exact "the arm that fails more looks
    artificially cheap" artifact prereg §4 calls non-negotiable, just on
    the iterations axis instead of tokens. Demonstrated: two cells with
    IDENTICAL greens (n_llm_calls 2 and 5) and IDENTICAL success rate
    (2/4) -- arm X's two failures quit at 1 iteration, arm Y's two hit
    MAX_ITERS=8 -- the own-stopping-point KM median came out 2.0 (X) vs
    5.0 (Y), a 2.5x swing produced purely by X's failures being cheap to
    fail. Censoring every non-green trial at the SAME administrative bound
    removes that artifact by construction, mirroring
    ``_tokens_km_administrative`` exactly.

    Rows with ``n_llm_calls is None`` (unknown iteration count) are
    excluded entirely, same as the pre-existing ``iters_times_events``
    filter -- an unknown stopping point can't be censored at anything.

    Returns ``None`` when ``admin_bound`` is ``None`` and no row with a
    known ``n_llm_calls`` exists to fall back to (see ``summarize_cell``,
    which resolves ``admin_bound`` as "explicit --max-iters, else the max
    observed n_llm_calls in this cell" before calling this function).
    """
    known_rows = [r for r in valid_rows if r.get("n_llm_calls") is not None]
    if admin_bound is None:
        if not known_rows:
            return None
        admin_bound = max(float(r["n_llm_calls"]) for r in known_rows)
    times_events = [
        (float(r["n_llm_calls"]), True)
        if r["reward"] >= GREEN_THRESHOLD
        else (float(admin_bound), False)
        for r in known_rows
    ]
    return km_median_iqr(times_events)


def summarize_cell(
    rows: list[dict[str, Any]],
    *,
    admin_max_tokens: float | None = None,
    admin_max_iters: float | None = None,
    _sensitivity_pass: bool = False,
) -> dict[str, Any]:
    """One cell's (arm, model, harness[, split_group/scenario if the caller
    pre-filtered]) full stat block, over its *valid* rows only —
    ``validity_class != "valid"`` rows are excluded from every headline
    number here (result_schema.json's own field description: "an invalid
    row must never be pooled into a scored headline number"), counted
    separately under ``n_excluded_invalid`` for transparency.

    ``admin_max_tokens``: the administrative MAX_TOKENS budget bound (see
    ``_tokens_km_administrative``). When ``None`` (the default), falls back
    to the max observed ``tokens_total`` among this cell's own valid rows
    -- the fix's fix_hint own "or max observed tokens in the cell when
    MAX_TOKENS is unset" fallback -- so the administrative convention is
    always computable, never silently skipped, even when the caller has no
    job-level budget.json to hand.

    ``admin_max_iters``: the administrative MAX_ITERS budget bound, the
    iterations-to-green counterpart of ``admin_max_tokens`` (see
    ``_iters_km_administrative``). Same ``None``-falls-back-to-max-observed
    convention, mirrored exactly (2026-08-06 fix round 2: the tokens-axis
    anti-survivorship fix was not mirrored onto iterations-to-green, which
    prereg §4 names as its own metric).

    ``_sensitivity_pass``: internal — sourceset to ``True`` on the
    recursive call inside the ``tier1_not_verifiable``-exclusion
    sensitivity block below, to stop that recursion computing a THIRD
    level of sensitivity summaries.
    """
    valid_rows = [r for r in rows if r["validity_class"] == "valid"]
    n_excluded = len(rows) - len(valid_rows)

    successes = [r for r in valid_rows if r["reward"] >= GREEN_THRESHOLD]
    n_success = len(successes)
    n_valid = len(valid_rows)
    phat, lo, hi = wilson_interval(n_success, n_valid)

    tokens_times_events_own = [
        (float(r["tokens_total"]), r["reward"] >= GREEN_THRESHOLD) for r in valid_rows
    ]
    tokens_km_own = km_median_iqr(tokens_times_events_own)

    effective_admin_bound = admin_max_tokens
    if effective_admin_bound is None and valid_rows:
        effective_admin_bound = max(float(r["tokens_total"]) for r in valid_rows)
    tokens_km_admin = _tokens_km_administrative(valid_rows, effective_admin_bound)

    iters_times_events = [
        (float(r["n_llm_calls"]), r["reward"] >= GREEN_THRESHOLD)
        for r in valid_rows
        if r.get("n_llm_calls") is not None
    ]
    iters_km_own = km_median_iqr(iters_times_events)

    effective_admin_iters_bound = admin_max_iters
    known_iters_rows = [r for r in valid_rows if r.get("n_llm_calls") is not None]
    if effective_admin_iters_bound is None and known_iters_rows:
        effective_admin_iters_bound = max(float(r["n_llm_calls"]) for r in known_iters_rows)
    iters_km_admin = _iters_km_administrative(valid_rows, effective_admin_iters_bound)
    # "iterations-to-green poisoned by n_llm_calls fallback" fix
    # (2026-08-06): gates/emit_result.py::extract_n_llm_calls now returns
    # `None` (not 0) for an absent/unreadable/malformed trajectory, and
    # to_result_row omits `n_llm_calls` from the row entirely when it's
    # `None` -- so "no n_llm_calls key" IS "unknown", never silently
    # counted as zero. Reported here rather than dropped so a cell whose
    # iteration stats rest on a small, filtered subset is visible as such.
    n_iterations_unknown = sum(1 for r in valid_rows if r.get("n_llm_calls") is None)

    iters_success_values = [
        float(r["n_llm_calls"]) for r in successes if r.get("n_llm_calls") is not None
    ]
    iterations_to_green = _order_stats(iters_success_values)

    n_budget_censored = sum(1 for r in valid_rows if r.get("censored") is True)
    n_natural_fail = sum(
        1 for r in valid_rows if r["reward"] < GREEN_THRESHOLD and not r.get("censored")
    )

    tokens_uncensored_all = _order_stats([float(r["tokens_total"]) for r in valid_rows])

    # "tier1_not_verifiable pooled into headline numbers" fix (2026-08-06):
    # a tier1_not_verifiable=true row's reward reflects a tier-1 check that
    # was NEVER actually evaluated for it (result_schema.json's own field
    # description) -- pooling those unconditionally into success-rate/
    # tokens-to-green inflates both on the TF arms specifically (a plan-
    # time-unknown IAM violation scores 1.0 there, 0.0 on awscdk, with
    # nothing distinguishing it). Reported as a count, PLUS a sensitivity
    # summary excluding them, so a reader can see whether the headline
    # result survives their removal.
    n_tier1_not_verifiable = sum(1 for r in valid_rows if r.get("tier1_not_verifiable") is True)
    sensitivity_excluding_tier1_not_verifiable = None
    if n_tier1_not_verifiable and not _sensitivity_pass:
        sensitivity_rows = [r for r in rows if not r.get("tier1_not_verifiable")]
        sensitivity_excluding_tier1_not_verifiable = summarize_cell(
            sensitivity_rows,
            admin_max_tokens=admin_max_tokens,
            admin_max_iters=admin_max_iters,
            _sensitivity_pass=True,
        )

    return {
        "n_valid": n_valid,
        "n_excluded_invalid": n_excluded,
        "n_tier1_not_verifiable": n_tier1_not_verifiable,
        "sensitivity_excluding_tier1_not_verifiable": sensitivity_excluding_tier1_not_verifiable,
        "success_rate": {
            "successes": n_success,
            "n": n_valid,
            "point": phat,
            "wilson_lo": lo,
            "wilson_hi": hi,
        },
        # HEADLINE convention (prereg §4): every non-green trial censored
        # at the administrative budget bound, not its own stopping point.
        # `None` only if this cell has zero valid rows (nothing to derive
        # a bound from and none was supplied).
        "tokens_to_green_km": tokens_km_admin,
        # Diagnostic/secondary convention (kept for backward compat and as
        # a sensitivity check on the headline number above) -- see
        # `_tokens_km_administrative`'s own docstring for exactly how these
        # two can diverge and why the administrative one is the headline.
        "tokens_to_green_km_own_stopping_point": tokens_km_own,
        "tokens_to_green_km_administrative_bound_used": effective_admin_bound,
        # HEADLINE convention (prereg §4), mirroring tokens_to_green_km
        # exactly (2026-08-06 fix round 2): every non-green trial (with a
        # known n_llm_calls) censored at the administrative MAX_ITERS
        # bound, not its own stopping point. `None` only if this cell has
        # no row with a known n_llm_calls to derive/apply a bound to.
        "iterations_to_green_km": iters_km_admin,
        # Diagnostic/secondary convention (kept for backward compat and as
        # a sensitivity check on the headline number above) -- see
        # `_iters_km_administrative`'s own docstring for exactly how these
        # two can diverge and why the administrative one is the headline.
        "iterations_to_green_km_own_stopping_point": iters_km_own,
        "iterations_to_green_km_administrative_bound_used": effective_admin_iters_bound,
        "iterations_to_green": iterations_to_green,
        "n_iterations_unknown": n_iterations_unknown,
        "tokens_total_uncensored": tokens_uncensored_all,
        "censoring_breakdown": {
            "n_success": n_success,
            "n_budget_censored": n_budget_censored,
            "n_natural_fail": n_natural_fail,
        },
    }


# ---------------------------------------------------------------------------
# Per-catch tier-attribution table
# ---------------------------------------------------------------------------


_SPEC_TIER1_NAMES_CACHE: dict[str, dict[str, list[str]]] = {}


def _tier1_assert_names_for_scenario(scenario: str) -> dict[str, list[str]]:
    """Best-effort ``{arm ("awscdk"|"hcl_raw"|"terraconstructs"): [tier-1
    structural_assert names]}`` for one scenario, loaded from
    ``specs/<scenario>.yaml`` if it exists.

    Part of the "per-catch tier attribution cannot express a tier-1 catch
    identity" fix (2026-08-06): every tier-1 catch for a scenario/arm used
    to collapse into one indistinguishable row literally named
    ``"(tier-1 bundle)"`` -- this joins that bundle row against the spec's
    OWN declared tier-1 assert names (fix_hint option (b): "join the
    bundle row against the spec's declared tier-1 assert names so the
    table at least enumerates the candidate catches ... and states the
    ambiguity explicitly in benchmark.json, not only in README prose").
    Does not (cannot, from this data alone) say WHICH of the enumerated
    asserts actually fired for a given failed trial -- that per-assert
    breakdown still does not exist (see ``build_tier_attribution``'s own
    docstring) -- it only replaces an opaque placeholder with the real,
    finite candidate set.

    Returns ``{}`` (never raises) for a scenario with no matching spec
    file on this machine -- fixture/synthetic scenario ids (e.g.
    metrics/emit_fixture_rows.py's ``"fixture-scenario"``), or a real
    scenario id this particular metrics run doesn't have ``specs/`` for
    locally.
    """
    if scenario in _SPEC_TIER1_NAMES_CACHE:
        return _SPEC_TIER1_NAMES_CACHE[scenario]
    result: dict[str, list[str]] = {}
    spec_path = _REPO_ROOT / "specs" / f"{scenario}.yaml"
    if spec_path.is_file():
        try:
            generator_dir = str(_REPO_ROOT / "generator")
            if generator_dir not in sys.path:
                sys.path.insert(0, generator_dir)
            from spec_model import load_spec  # noqa: PLC0415

            spec = load_spec(spec_path)
            for arm in ("awscdk", "hcl_raw", "terraconstructs"):
                names = [
                    a.name
                    for a in spec.oracle.structural_asserts
                    if a.tier == "1" and arm in a.applies_to
                ]
                if names:
                    result[arm] = names
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            # Best-effort/informational only -- a spec that fails to load
            # (schema drift -- spec_model.load_spec raises pydantic
            # ValidationError, a ValueError subclass; a scenario id that
            # collides with an unrelated/malformed YAML file; ...) must
            # never take down report generation over a cosmetic
            # enrichment; falls back to the opaque bundle name.
            print(
                f"WARNING: tokens_to_green: could not load {spec_path} to enrich "
                f"tier-1 bundle names ({exc!r}) -- falling back to '(tier-1 bundle)'",
                file=sys.stderr,
            )
            result = {}
    _SPEC_TIER1_NAMES_CACHE[scenario] = result
    return result


def _scenario_identity(row: dict[str, Any]) -> str:
    """The identity to group/attribute a row by: prefer ``spec_id`` (the
    cdktn-bench BENCHMARK scenario id, e.g. "apigw-openapi"), falling back
    to ``scenario`` only when ``spec_id`` is absent (older rows, or
    hand-built test fixtures that set ``scenario`` directly).

    2026-08-06 fix ("per-catch tier attribution ... INERT or DEGENERATE on
    the rows gates/emit_result.py actually emits"): every row this repo's
    own gates emit has ``scenario == "anchor"`` unconditionally (the single
    aws-bench AWS scenario every task lives under — result_schema.json's
    own field description) and the real per-benchmark-scenario identity
    (sfn-jsonata, apigw-openapi, ...) only ever lives in ``spec_id``.
    Keying attribution/grouping on ``scenario`` alone therefore collapsed
    every real row into one degenerate "anchor" group; ``spec_id`` is what
    actually distinguishes them. Falling back to ``scenario`` (rather than
    requiring ``spec_id``) keeps pre-existing hand-built fixture rows (and
    any older published data with no ``spec_id`` field at all) working
    unchanged.
    """
    return row.get("spec_id") or row.get("scenario") or "(unknown-scenario)"


def build_tier_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per (scenario, arm, tier, name) failure-attribution table.

    "scenario" here is the row's ``spec_id`` (falling back to ``scenario``
    when absent — see ``_scenario_identity``), i.e. the cdktn-bench
    BENCHMARK scenario id (apigw-openapi, sfn-jsonata, ...), NOT
    aws-bench's own AWS ``scenario`` field (always "anchor" in this repo).

    Only ``valid`` rows are considered. tier-0 attribution is real
    per-assert evidence; every tier-"1" catch for a scenario/arm is
    reported as one bundled row named ``"(tier-1 bundle)"`` — see
    ``gates/emit_result.py::read_tier_evidence``'s docstring for why a
    finer breakdown isn't available from the current oracle design.

    Rows whose ``tier_evidence`` is entirely absent (older data, or a
    non-static_tiers.sh verifier) are counted under
    ``no_evidence_by_scenario_arm`` rather than silently excluded.
    """
    valid_rows = [r for r in rows if r["validity_class"] == "valid"]

    # (scenario, arm) -> counters
    totals: dict[tuple[str, str], dict[str, int]] = {}
    # (scenario, arm, tier, name) -> fail_count
    fails: dict[tuple[str, str, str, str], int] = {}
    no_evidence: dict[tuple[str, str], int] = {}

    for r in valid_rows:
        scenario = _scenario_identity(r)
        arm = r["arm"]
        key = (scenario, arm)
        t = totals.setdefault(key, {"n_valid": 0, "n_failed": 0})
        t["n_valid"] += 1
        is_failed = r["reward"] < GREEN_THRESHOLD
        if is_failed:
            t["n_failed"] += 1

        evidence = r.get("tier_evidence")
        if evidence is None:
            if is_failed:
                no_evidence[key] = no_evidence.get(key, 0) + 1
            continue
        if not is_failed:
            continue  # attribution only meaningful for failures

        for name, status in (evidence.get("tier0") or {}).items():
            if status == "FAIL":
                fails[(scenario, arm, "0", name)] = fails.get((scenario, arm, "0", name), 0) + 1
        tier1_status = evidence.get("tier1_status")
        if tier1_status in {"FAIL", "TOOL_MISSING", "SKIPPED_STUB"}:
            # spec_model's Arm literal is "hcl_raw" (underscore); the row's
            # own `arm` field is result_schema.json's "hcl-raw" (hyphen) --
            # translate before looking up candidate tier-1 assert names.
            spec_arm = arm.replace("-", "_")
            candidate_names = _tier1_assert_names_for_scenario(scenario).get(spec_arm, [])
            bundle_name = (
                "(tier-1 bundle: " + ", ".join(candidate_names) + ")"
                if candidate_names
                else "(tier-1 bundle)"
            )
            k = (scenario, arm, "1", bundle_name)
            fails[k] = fails.get(k, 0) + 1

    table = []
    for (scenario, arm, tier, name), fail_count in sorted(fails.items()):
        t = totals[(scenario, arm)]
        table.append(
            {
                "scenario": scenario,
                "arm": arm,
                "tier": tier,
                "name": name,
                "fail_count": fail_count,
                "n_valid": t["n_valid"],
                "n_failed": t["n_failed"],
                "share_of_failures": (fail_count / t["n_failed"]) if t["n_failed"] else None,
            }
        )

    return {
        "table": table,
        "no_evidence_failed_trials": [
            {"scenario": s, "arm": a, "count": c} for (s, a), c in sorted(no_evidence.items())
        ],
    }


# ---------------------------------------------------------------------------
# Top-level report assembly
# ---------------------------------------------------------------------------


def _group_by_scenario(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group rows by ``_scenario_identity`` (``spec_id``, falling back to
    ``scenario`` — see its docstring). NOT keyed on ``scenario`` alone: real
    emitted rows all share ``scenario == "anchor"``, which would collapse
    every benchmark scenario into one degenerate group and make
    ``scenario_coverage``/``by_scenario`` unable to support prereg §7's
    paired-by-scenario analysis (2026-08-06 fix)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_scenario_identity(row), []).append(row)
    return groups


def _cell_report(
    arm: str,
    model: str,
    harness: str,
    cell_rows: list[dict[str, Any]],
    *,
    admin_max_tokens: float | None,
    admin_max_iters: float | None,
) -> dict[str, Any]:
    """One (arm, model, harness) cell's stat block, PLUS a per-scenario
    breakdown -- "prereg §7 analysis outputs not derivable from
    benchmark.json" fix (2026-08-06): cell_key() only ever grouped by
    (arm, model, harness), discarding scenario identity entirely, so
    prereg §7's primary test ("tokens-to-green, tuned-CDK vs empty-HCL,
    per model, PAIRED BY SCENARIO") and its main-effects decomposition
    could not be computed from this script's own output -- a consumer had
    to re-read the raw rows. ``scenario_coverage`` (counts) and
    ``by_scenario`` (a full ``summarize_cell`` block per scenario) unblock
    both without requiring benchmark.md's own pooled table to change.
    """
    summary = summarize_cell(cell_rows, admin_max_tokens=admin_max_tokens, admin_max_iters=admin_max_iters)
    scenario_groups = _group_by_scenario(cell_rows)
    summary["scenario_coverage"] = {s: len(srows) for s, srows in sorted(scenario_groups.items())}
    summary["by_scenario"] = {
        s: summarize_cell(srows, admin_max_tokens=admin_max_tokens, admin_max_iters=admin_max_iters)
        for s, srows in sorted(scenario_groups.items())
    }
    return {"arm": arm, "model": model, "harness": harness, **summary}


def _cells_for(
    rows: list[dict[str, Any]], *, admin_max_tokens: float | None, admin_max_iters: float | None
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(cell_key(row), []).append(row)
    return [
        _cell_report(
            arm,
            model,
            harness,
            cell_rows,
            admin_max_tokens=admin_max_tokens,
            admin_max_iters=admin_max_iters,
        )
        for (arm, model, harness), cell_rows in sorted(grouped.items())
    ]


def build_report(
    rows: list[dict[str, Any]],
    load_errors: list[str],
    *,
    max_iters: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    cell_reports = _cells_for(rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters)

    # split_group stratification (2026-08-06 fix, "the train/holdout split
    # is unenforceable at the layer that matters -- the published number":
    # prereg §7.1 calls this boundary "the methodological safeguard most
    # likely to be skipped and most damaging if it is", but `cells` above
    # pools every split_group into one number). `headline_cells` (holdout
    # only) is the PRE-REGISTERED primary result; `train_cells` (the
    # scenarios equipping is explicitly allowed to be tuned against) is
    # reported separately, never silently merged into the headline.
    # `cells` above is kept as-is (pooled, backward-compatible) for
    # reference/diagnostic use only -- it is NOT the headline.
    holdout_rows = [r for r in rows if r.get("split_group") == "holdout"]
    train_rows = [r for r in rows if r.get("split_group") == "train"]
    unclassified_rows = [r for r in rows if r.get("split_group") not in ("holdout", "train")]

    return {
        "schema_version": "1.0",
        "n_rows_total": len(rows) + len(load_errors),
        "n_rows_loaded": len(rows),
        "n_rows_rejected": len(load_errors),
        "load_errors": load_errors,
        "budget": {"max_iters": max_iters, "max_tokens": max_tokens},
        "cells": cell_reports,
        "headline_cells": _cells_for(holdout_rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters),
        "train_cells": _cells_for(train_rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters),
        "split_composition": {
            "n_holdout_rows": len(holdout_rows),
            "n_train_rows": len(train_rows),
            "n_unclassified_rows": len(unclassified_rows),
        },
        "tier_attribution": build_tier_attribution(rows),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 0) -> str:
    if value is None:
        return "NE"  # "not estimable" -- see km_quantile's docstring
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _render_cell_table(lines: list[str], cells: list[dict[str, Any]]) -> None:
    lines.append(
        "| Arm | Model | Harness | N valid | Excl. invalid | Success rate "
        "(Wilson 95% CI) | Tokens-to-green median [IQR] (KM, admin-censored) | "
        "Iterations-to-green median [IQR] | Tokens mean±stddev (uncensored) | "
        "n tier1_not_verifiable |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        sr = c["success_rate"]
        tkm = c["tokens_to_green_km"]
        ikm = c["iterations_to_green_km"]
        tstats = c["tokens_total_uncensored"]
        success_cell = (
            f"{sr['successes']}/{sr['n']} = {sr['point']*100:.1f}% "
            f"[{sr['wilson_lo']*100:.1f}%, {sr['wilson_hi']*100:.1f}%]"
        )
        tokens_cell = f"{_fmt(tkm['median'])} [{_fmt(tkm['q25'])}, {_fmt(tkm['q75'])}]" if tkm else "n/a"
        if tkm:
            # Annotated on the censored FRACTION directly (2026-08-06 fix,
            # "'>50% censored -> median undefined' only holds for late
            # censoring" -- majority-censored does NOT imply NE when
            # censoring happens before the events, so this must not be
            # gated on median_reached alone).
            if tkm["censored_frac"] >= 0.5:
                tokens_cell += f" ({tkm['censored_frac']*100:.0f}% censored)"
            if tkm["median_reached"] and tkm["low_event_count"]:
                tokens_cell += f" (n_events={tkm['n_events']}, low)"
        iters_cell = f"{_fmt(ikm['median'])} [{_fmt(ikm['q25'])}, {_fmt(ikm['q75'])}]" if ikm else "n/a"
        if ikm:
            # Same censored-fraction annotation as tokens_cell above, now
            # that iterations_to_green_km can also genuinely be None (a
            # cell with zero rows carrying a known n_llm_calls -- 2026-08-06
            # fix round 2, mirroring tokens_to_green_km's own None case).
            if ikm["censored_frac"] >= 0.5:
                iters_cell += f" ({ikm['censored_frac']*100:.0f}% censored)"
            if ikm["median_reached"] and ikm["low_event_count"]:
                iters_cell += f" (n_events={ikm['n_events']}, low)"
        mean_cell = (
            f"{tstats['mean']:.0f}±{tstats['stddev']:.0f}" if tstats else "n/a"
        )
        lines.append(
            f"| {c['arm']} | {c['model']} | {c['harness']} | {c['n_valid']} | "
            f"{c['n_excluded_invalid']} | {success_cell} | {tokens_cell} | "
            f"{iters_cell} | {mean_cell} | {c['n_tier1_not_verifiable']} |"
        )


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# cdktn-bench headline metrics")
    lines.append("")
    lines.append(
        f"Rows loaded: **{report['n_rows_loaded']}** "
        f"(rejected: {report['n_rows_rejected']})."
    )
    budget = report["budget"]
    lines.append(
        f"Budget: MAX_ITERS={_fmt(budget['max_iters'])} "
        f"MAX_TOKENS={_fmt(budget['max_tokens'])}"
    )
    split_comp = report["split_composition"]
    lines.append(
        f"Split composition: {split_comp['n_holdout_rows']} holdout row(s), "
        f"{split_comp['n_train_rows']} train row(s), "
        f"{split_comp['n_unclassified_rows']} unclassified row(s) "
        "(prereg §7.1 -- unclassified rows are pooled into NEITHER table below)."
    )
    lines.append("")

    lines.append("## HEADLINE (holdout scenarios only -- prereg §7.1)")
    lines.append("")
    lines.append(
        "This is the pre-registered primary result. Train-split scenarios "
        "(the ones tuned equipping is explicitly allowed to be developed "
        "against) are reported separately below, never pooled in here."
    )
    lines.append("")
    if report["headline_cells"]:
        _render_cell_table(lines, report["headline_cells"])
    else:
        lines.append("_(no holdout-split rows loaded)_")
    lines.append("")

    lines.append("## Train-split cells (secondary -- equipping-tunable scenarios)")
    lines.append("")
    if report["train_cells"]:
        _render_cell_table(lines, report["train_cells"])
    else:
        lines.append("_(no train-split rows loaded)_")
    lines.append("")

    lines.append("## All rows pooled (train + holdout + unclassified) -- reference only, NOT the headline")
    lines.append("")
    _render_cell_table(lines, report["cells"])
    lines.append("")
    lines.append(
        "Tokens-to-green is the Kaplan-Meier censored median/IQR over "
        "`tokens_total` (event = reward >= 1.0), censored at the "
        "ADMINISTRATIVE budget bound (explicit MAX_TOKENS, else the max "
        "observed tokens_total in that cell) for every non-green trial -- "
        "the pre-registered convention (prereg §4: runs that never reach "
        "green WITHIN THE BUDGET CAP are right-censored AT THAT CAP, not "
        "wherever they happened to stop; see metrics/README.md and each "
        "cell's own `tokens_to_green_km_own_stopping_point` for the "
        "diagnostic own-stopping-point convention this replaces as the "
        "headline). `NE` = not estimable (the KM curve never dropped to "
        "that survival level within this cell's sample); a `(low)` "
        "annotation flags a reached median computed from fewer than "
        f"{MIN_EVENTS_FOR_CONFIDENT_MEDIAN} observed events."
    )
    lines.append("")

    attribution = report["tier_attribution"]
    lines.append("## Per-catch tier-attribution table")
    lines.append("")
    lines.append(
        "Tier \"0\" rows are real per-assert evidence; tier \"1\" rows are a "
        "single bundled verdict covering every tier-1 catch for that "
        "scenario/arm (the oracle itself only ever computes one verdict "
        "per bundle — see gates/emit_result.py::read_tier_evidence)."
    )
    lines.append("")
    lines.append(
        "| Scenario | Arm | Tier | Catch/assert | Fail count | "
        "Share of that cell's failures | Valid trials | Failed trials |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in attribution["table"]:
        share = "n/a" if row["share_of_failures"] is None else f"{row['share_of_failures']*100:.1f}%"
        lines.append(
            f"| {row['scenario']} | {row['arm']} | {row['tier']} | {row['name']} | "
            f"{row['fail_count']} | {share} | {row['n_valid']} | {row['n_failed']} |"
        )
    if attribution["no_evidence_failed_trials"]:
        lines.append("")
        lines.append(
            "Failed trials with **no** `tier_evidence` at all (not attributable — "
            "counted here, never silently dropped):"
        )
        for e in attribution["no_evidence_failed_trials"]:
            lines.append(f"- {e['scenario']} / {e['arm']}: {e['count']}")

    if report["load_errors"]:
        lines.append("")
        lines.append("## Rejected rows")
        lines.append("")
        for err in report["load_errors"]:
            lines.append(f"- {err}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path, help="Directory of result-row files to aggregate (recursive).")
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="Where to write benchmark.json/benchmark.md (default: results_dir)."
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=None,
        help="Budget cap recorded in the report's metadata AND used as the ADMINISTRATIVE censoring bound for every cell's headline iterations_to_green_km (2026-08-06 fix round 2, mirroring --max-tokens's own tokens_to_green_km fix: prereg §4's 'right-censored WITHIN THE BUDGET CAP' convention, applied to the iterations axis) -- every non-green valid trial with a known n_llm_calls in a cell is censored at this value, not its own stopping point. When omitted, each cell falls back to the max observed n_llm_calls within that cell (see summarize_cell's own docstring). Does NOT change which rows are counted as censored=True/False (that's read from each row's own `censored` field, which upstream already set) -- only the KM curve's censoring TIME.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Budget cap recorded in the report's metadata AND used as the ADMINISTRATIVE censoring bound for every cell's headline tokens_to_green_km (2026-08-06 censoring-semantics fix: prereg §4's 'right-censored WITHIN THE BUDGET CAP' convention) -- every non-green valid trial in a cell is censored at this value, not its own stopping point. When omitted, each cell falls back to the max observed tokens_total within that cell (see summarize_cell's own docstring); does not change each row's own `censored` field.",
    )
    args = parser.parse_args(argv)

    out_dir = args.out_dir or args.results_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, errors = load_rows(args.results_dir)
    report = build_report(rows, errors, max_iters=args.max_iters, max_tokens=args.max_tokens)

    (out_dir / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "benchmark.md").write_text(render_markdown(report), encoding="utf-8")

    print(f"loaded {report['n_rows_loaded']} row(s), rejected {report['n_rows_rejected']}")
    print(f"wrote {out_dir / 'benchmark.json'}")
    print(f"wrote {out_dir / 'benchmark.md'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
