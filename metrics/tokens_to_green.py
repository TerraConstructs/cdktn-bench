#!/usr/bin/env python3
"""The headline metric aggregator: published result rows in, benchmark.json
and benchmark.md out.

Input is a DIRECTORY of metrics/result_schema.json-conformant JSON/NDJSON rows
(gates/emit_result.py::to_result_row). Every *.json/*.ndjson/*.jsonl under it
is parsed with metrics/validate_result.py's tolerance and validated against the
schema; a row failing validation is reported and excluded, never silently
pooled. The per-cell measures, the train/holdout stratification and the prereg
section each one implements: docs/generator.md "tokens-to-green aggregator".

THE POOLING BOUNDARY: rows split by `scenario_form` before the train/holdout
split and before the (arm, model, harness) cell; a directory holding two or
more forms gets one section per form and no combined headline, and an
unlabelled row aborts the run (DECISIONS.md Amendment 36, scenario_form as a
required, never-pooled row field).

THE CENSORING CONVENTION: every non-green trial is right-censored at the
ADMINISTRATIVE budget bound (--max-tokens, else the max observed tokens_total
in that cell), never at its own stopping point -- prereg §4's "right-censored
WITHIN THE BUDGET CAP". Own-stopping-point censoring is a per-cell diagnostic
only (`tokens_to_green_km_own_stopping_point`); as the headline it would let an
arm whose failures quit cheaply report a low tokens-to-green regardless of its
actual success rate.
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

# Every scenario form, in report order: each step-shape base followed by its
# seeded (`-brownfield`) variant. Sections render in this order so a report's
# shape does not depend on which forms a results dir happens to hold. Must stay
# a superset of result_schema.json's `scenario_form` enum.
SCENARIO_FORMS = (
    "greenfield",
    "brownfield",
    "multi-step",
    "multi-step-brownfield",
    "pre-configured-account",
    "pre-configured-account-brownfield",
)


# Where load_rows records which file an unlabelled row came from, so the
# refusal below can name it: a published row carries no job or trial id.
SOURCE_LABEL_KEY = "__source_label"


class ScenarioFormMissing(ValueError):
    """A row reached cell aggregation without a `scenario_form`.

    Never backfilled or defaulted: the aggregator's whole no-pooling rule
    rests on the field, so an unlabelled row stops the run instead.
    """

# norm.ppf(0.975) to full double precision — the two-sided 95% Wilson
# z-score. Hardcoded rather than imported from scipy (not a project
# dependency, pyproject.toml's dev group is pytest/pyyaml/jsonpath-ng
# only) — this is a well-known constant, not a computed one.
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
# "reached" (median_reached=True), must be read with caution -- see
# km_median_iqr's own docstring. Arbitrary but explicit: 5 events is the
# smallest sample order statistics conventionally treat as informative at all.
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

    ``censored_frac`` and ``low_event_count`` exist because "'>50% censored ->
    median undefined'" only holds for LATE censoring: ``NE`` implies
    majority-censored, but majority-censored does not imply ``NE`` when the
    censoring happens before the events. 10 rows with 6 failures censored at
    100..600 and 4 greens at 1000/2000/3000/4000 give ``n_censored=6`` (60%)
    yet ``median_reached=True, median=2000.0`` -- a confident-looking point
    estimate resting on 4 observations. So ``censored_frac`` is reported
    UNCONDITIONALLY, independent of whether the median was reached, and a
    renderer must annotate on that fraction rather than infer it from
    ``median_reached``; ``low_event_count`` flags
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
    discipline ``metrics/validate_result.py``'s own CLI enforces. The one
    exception is a row with no ``scenario_form``: it is kept so that
    ``build_report`` can refuse the whole run over it.
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
            # An unlabelled row is kept rather than dropped so build_report,
            # the one refusal point, can abort on it; dropping it here would
            # publish a headline that looks poolable only because the offending
            # rows are gone. The source label rides along under a reserved key
            # because a published row carries no job or trial id to name it by.
            if not row.get("scenario_form"):
                rows.append({**row, SOURCE_LABEL_KEY: label})
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


def cell_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """A cell's full identity, scenario_form first.

    The form leads because it is the coarsest pooling boundary: two rows of
    different forms measure different tasks (and, for multi-step, a different
    metric), so no estimator may see them in one cell. A row without one is
    refused here rather than pooled.
    """
    if not row.get("scenario_form"):
        raise ScenarioFormMissing(
            "cell_key: row carries no scenario_form -- refusing to pool it "
            "into any cell"
        )
    return row["scenario_form"], row["arm"], row["model"], row["harness"]


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

    The alternative convention -- censoring a non-green trial at ITS OWN
    ``tokens_total``, still computed as
    ``tokens_to_green_km_own_stopping_point`` -- is right for a censored=True
    row and WRONG for a censored=False row that stopped on its own before the
    cap. Two cells with identical greens (10000, 20000) and identical success
    rate (2/4), where arm X's two failures quit cheap (500/600) and arm Y's two
    hit the cap (50000/50000), give own-stopping-point medians of 10000 vs
    20000: a 2x swing produced purely by X's failures being cheaper to fail,
    the "the arm that fails more looks artificially cheap" artifact prereg §4
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

    The anti-survivorship argument is the tokens axis's, restated: censoring at
    each trial's OWN ``n_llm_calls`` reproduces "the arm that fails more looks
    artificially cheap". Two cells with identical greens (n_llm_calls 2 and 5)
    and identical success rate (2/4), where arm X's failures quit at 1 iteration
    and arm Y's hit MAX_ITERS=8, give own-stopping-point medians of 2.0 vs 5.0.
    The administrative bound removes that artifact by construction, mirroring
    ``_tokens_km_administrative`` exactly.

    Rows with ``n_llm_calls is None`` (unknown iteration count) are excluded
    entirely -- an unknown stopping point cannot be censored at anything.

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


def summarize_profile(valid_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The profile columns for one cell (ROADMAP "a profile, not a scalar"):
    read-before-write incidence, escape-hatch incidence, blast radius.

    All three are OPTIONAL row fields, so each reports its own known-row
    denominator: a mean over the rows that carry it plus the count that do not.
    Averaging over the whole cell would silently read a missing field as zero,
    which is exactly how a pre-artifact trial would drag a blast-radius mean
    down without anything in the output saying so.

    Blast radius is summarized per SOURCE, never pooled across them: a
    `cloudformation-template` row has no action breakdown at all, so pooling it
    with plan rows would divide replace counts by a denominator that includes
    rows where a replace could not have been observed.
    """
    rbw_pcts = [
        float(r["rbw"]["pct"])
        for r in valid_rows
        if isinstance(r.get("rbw"), dict) and r["rbw"].get("pct") is not None
    ]
    # A transcript that shows the entry file was never mutated is a real
    # observation, counted apart from having no transcript to read at all.
    n_rbw_no_write = sum(
        1
        for r in valid_rows
        if isinstance(r.get("rbw"), dict) and r["rbw"].get("pct") is None
    )
    escapes = [r["escape_hatch"] for r in valid_rows if r.get("escape_hatch") is not None]

    by_source: dict[str, dict[str, Any]] = {}
    for r in valid_rows:
        radius = r.get("blast_radius")
        if not isinstance(radius, dict):
            continue
        block = by_source.setdefault(
            radius["source"], {"n": 0, "totals": [], "replaces": [], "modules": []}
        )
        block["n"] += 1
        block["totals"].append(float(radius.get("total") or 0))
        counts = radius.get("counts")
        if isinstance(counts, dict):
            block["replaces"].append(float(counts.get("replace") or 0))
        if radius.get("module") is not None:
            block["modules"].append(float(radius["module"]))
    blast: dict[str, Any] = {}
    for source, block in sorted(by_source.items()):
        blast[source] = {
            "n": block["n"],
            "resources_total": _order_stats(block["totals"]),
            "replaced": _order_stats(block["replaces"]),
            "module_scoped": _order_stats(block["modules"]),
        }

    return {
        "rbw_pct": _order_stats(rbw_pcts),
        "n_rbw_known": len(rbw_pcts),
        "n_rbw_no_entry_file_write": n_rbw_no_write,
        "n_rbw_unknown": len(valid_rows) - len(rbw_pcts) - n_rbw_no_write,
        "escape_hatch": {
            "yes": escapes.count("yes"),
            "no": escapes.count("no"),
            "not_applicable": escapes.count("n/a"),
            "n_unknown": len(valid_rows) - len(escapes),
        },
        "blast_radius_by_source": blast,
        "n_blast_radius_unknown": len(valid_rows) - sum(b["n"] for b in blast.values()),
    }


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
    ``_tokens_km_administrative``). When ``None`` (the default), falls back to
    the max observed ``tokens_total`` among this cell's own valid rows, so the
    administrative convention is always computable and never silently skipped
    even when the caller has no job-level budget.json to hand.

    ``admin_max_iters``: the administrative MAX_ITERS budget bound, the
    iterations-to-green counterpart of ``admin_max_tokens`` (see
    ``_iters_km_administrative``). Same ``None``-falls-back-to-max-observed
    convention, mirrored exactly, because prereg §4 names iterations-to-green
    as its own metric.

    ``_sensitivity_pass``: internal — set to ``True`` on the recursive call
    inside the ``tier1_not_verifiable``-exclusion sensitivity block below, to
    stop that recursion computing a THIRD level of sensitivity summaries.
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
    # "no n_llm_calls key" IS "unknown", never zero: gates/emit_result.py::
    # extract_n_llm_calls returns `None` for an absent/unreadable/malformed
    # trajectory and to_result_row omits the key. Counted here rather than
    # dropped, so a cell whose iteration stats rest on a small filtered subset
    # is visible as such.
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

    # A tier1_not_verifiable=true row's reward reflects a tier-1 check that was
    # NEVER evaluated for it (result_schema.json's own field description), so
    # pooling those into success-rate/tokens-to-green inflates both on the TF
    # arms specifically -- a plan-time-unknown IAM violation scores 1.0 there
    # and 0.0 on awscdk, with nothing distinguishing it. Reported as a count
    # PLUS a sensitivity summary excluding them, so a reader can see whether
    # the headline result survives their removal.
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
        "profile": summarize_profile(valid_rows),
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
        # exactly: every non-green trial with a known n_llm_calls is censored
        # at the administrative MAX_ITERS bound, not its own stopping point.
        # `None` only if this cell has no row with a known n_llm_calls.
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

    Without this, every tier-1 catch for a scenario/arm collapses into one
    indistinguishable ``"(tier-1 bundle)"`` row. Joining that row against the
    spec's OWN declared tier-1 assert names replaces the opaque placeholder
    with the real, finite candidate set. It does not (cannot, from this data
    alone) say WHICH of the enumerated asserts fired for a given failed trial
    -- see ``build_tier_attribution``'s own docstring -- so the ambiguity is
    stated in benchmark.json rather than hidden.

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

    Attribution and grouping key on ``spec_id``, never on ``scenario``:
    every row this repo's own gates emit carries an aws-bench SCENARIO id
    — "anchor", or one of its shards "anchor-k" (generator/shards.py) —
    which many benchmark scenarios share, so keying on it collapses them
    into a few degenerate groups, while the real per-benchmark-scenario
    identity (sfn-jsonata, apigw-openapi, ...) only ever lives in
    ``spec_id``. Falling back to ``scenario`` (rather than requiring
    ``spec_id``) keeps hand-built fixture rows, and published data with no
    ``spec_id`` field at all, working unchanged.
    """
    return row.get("spec_id") or row.get("scenario") or "(unknown-scenario)"


def build_tier_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per (scenario, arm, tier, name) failure-attribution table.

    "scenario" here is the row's ``spec_id`` (falling back to ``scenario``
    when absent — see ``_scenario_identity``), i.e. the cdktn-bench
    BENCHMARK scenario id (apigw-openapi, sfn-jsonata, ...), NOT
    aws-bench's own AWS ``scenario`` field ("anchor" or an "anchor-k"
    shard, each shared by many benchmark scenarios).

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
    ``scenario`` — see its docstring). NOT keyed on ``scenario`` alone: that
    field names the aws-bench shard ("anchor", "anchor-k"), which many
    benchmark scenarios share, so it would collapse them into a few
    degenerate groups and make
    ``scenario_coverage``/``by_scenario`` unable to support prereg §7's
    paired-by-scenario analysis."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_scenario_identity(row), []).append(row)
    return groups


def _cell_report(
    scenario_form: str,
    arm: str,
    model: str,
    harness: str,
    cell_rows: list[dict[str, Any]],
    *,
    admin_max_tokens: float | None,
    admin_max_iters: float | None,
) -> dict[str, Any]:
    """One (scenario_form, arm, model, harness) cell's stat block, plus a
    per-scenario breakdown.

    cell_key() discards scenario identity, which leaves prereg §7's primary
    test ("tokens-to-green, tuned-CDK vs empty-HCL, per model, paired by
    scenario") and its main-effects decomposition underivable from this
    script's output. ``scenario_coverage`` (counts) and ``by_scenario`` (a full
    ``summarize_cell`` block per scenario) carry that identity without changing
    benchmark.md's pooled table.
    """
    summary = summarize_cell(cell_rows, admin_max_tokens=admin_max_tokens, admin_max_iters=admin_max_iters)
    scenario_groups = _group_by_scenario(cell_rows)
    summary["scenario_coverage"] = {s: len(srows) for s, srows in sorted(scenario_groups.items())}
    summary["by_scenario"] = {
        s: summarize_cell(srows, admin_max_tokens=admin_max_tokens, admin_max_iters=admin_max_iters)
        for s, srows in sorted(scenario_groups.items())
    }
    return {
        "scenario_form": scenario_form,
        "arm": arm,
        "model": model,
        "harness": harness,
        **summary,
    }


def _cells_for(
    rows: list[dict[str, Any]], *, admin_max_tokens: float | None, admin_max_iters: float | None
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(cell_key(row), []).append(row)
    return [
        _cell_report(
            scenario_form,
            arm,
            model,
            harness,
            cell_rows,
            admin_max_tokens=admin_max_tokens,
            admin_max_iters=admin_max_iters,
        )
        for (scenario_form, arm, model, harness), cell_rows in sorted(grouped.items())
    ]


def _stratified_block(
    rows: list[dict[str, Any]], *, max_iters: int | None, max_tokens: int | None
) -> dict[str, Any]:
    """The train/holdout stratification for one scenario form's rows.

    `headline_cells` (holdout only) is the pre-registered primary result;
    `train_cells` are the scenarios tuned equipping may be developed against
    and are never merged into it; `cells` pools all three split groups and is
    diagnostic only (prereg §7.1). Callers pass one form's rows only.
    """
    holdout_rows = [r for r in rows if r.get("split_group") == "holdout"]
    train_rows = [r for r in rows if r.get("split_group") == "train"]
    unclassified_rows = [r for r in rows if r.get("split_group") not in ("holdout", "train")]
    return {
        "cells": _cells_for(rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters),
        "headline_cells": _cells_for(
            holdout_rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters
        ),
        "train_cells": _cells_for(
            train_rows, admin_max_tokens=max_tokens, admin_max_iters=max_iters
        ),
        "split_composition": {
            "n_holdout_rows": len(holdout_rows),
            "n_train_rows": len(train_rows),
            "n_unclassified_rows": len(unclassified_rows),
        },
    }


def _forms_present(rows: list[dict[str, Any]]) -> list[str]:
    """The scenario forms in `rows`, in SCENARIO_FORMS order.

    A form outside SCENARIO_FORMS raises rather than sorting itself onto the
    end: load_rows validates every row against result_schema.json's closed
    enum, so an unknown form means this tuple and that enum have drifted apart
    and the report would silently omit the form's section.
    """
    seen = {r["scenario_form"] for r in rows if r.get("scenario_form")}
    unknown = sorted(seen - set(SCENARIO_FORMS))
    if unknown:
        raise ScenarioFormMissing(
            "_forms_present: row(s) carry a scenario_form outside "
            f"SCENARIO_FORMS: {unknown} -- metrics/tokens_to_green.py and "
            "metrics/result_schema.json's enum have drifted apart"
        )
    return [f for f in SCENARIO_FORMS if f in seen]


def build_report(
    rows: list[dict[str, Any]],
    load_errors: list[str],
    *,
    max_iters: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    missing = [r for r in rows if not r.get("scenario_form")]
    if missing:
        labels = [
            r.get(SOURCE_LABEL_KEY)
            or json.dumps({k: r.get(k) for k in ("arm", "model", "harness")}, sort_keys=True)
            for r in missing
        ]
        raise ScenarioFormMissing(
            f"build_report: {len(missing)} row(s) carry no scenario_form: "
            + "; ".join(labels)
            + " -- re-emit them with gates/emit_result.py; the form is never "
            "backfilled and forms are never pooled"
        )

    forms = _forms_present(rows)
    by_form = {
        form: {
            "n_rows": sum(1 for r in rows if r["scenario_form"] == form),
            **_stratified_block(
                [r for r in rows if r["scenario_form"] == form],
                max_iters=max_iters,
                max_tokens=max_tokens,
            ),
            "tier_attribution": build_tier_attribution(
                [r for r in rows if r["scenario_form"] == form]
            ),
        }
        for form in forms
    }

    report: dict[str, Any] = {
        "schema_version": "1.1",
        "n_rows_total": len(rows) + len(load_errors),
        "n_rows_loaded": len(rows),
        "n_rows_rejected": len(load_errors),
        "load_errors": load_errors,
        "budget": {"max_iters": max_iters, "max_tokens": max_tokens},
        "scenario_forms": forms,
        "by_scenario_form": by_form,
    }

    # The refusal, made structural: top-level `cells`/`headline_cells`/
    # `train_cells`/`split_composition`/`tier_attribution` hold one form's
    # numbers, so with two or more forms they are null, `pooling_refused` is
    # true, and by_scenario_form is the only place a headline can be read.
    report["pooling_refused"] = len(forms) > 1
    if len(forms) > 1:
        report["cells"] = None
        report["headline_cells"] = None
        report["train_cells"] = None
        report["split_composition"] = None
        report["tier_attribution"] = None
    elif forms:
        single = by_form[forms[0]]
        report["cells"] = single["cells"]
        report["headline_cells"] = single["headline_cells"]
        report["train_cells"] = single["train_cells"]
        report["split_composition"] = single["split_composition"]
        report["tier_attribution"] = single["tier_attribution"]
    else:
        report["cells"] = []
        report["headline_cells"] = []
        report["train_cells"] = []
        report["split_composition"] = {
            "n_holdout_rows": 0,
            "n_train_rows": 0,
            "n_unclassified_rows": 0,
        }
        report["tier_attribution"] = build_tier_attribution(rows)
    return report


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 0) -> str:
    if value is None:
        return "NE"  # "not estimable" -- see km_quantile's docstring
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _rbw_cell(profile: dict[str, Any]) -> str:
    stats = profile["rbw_pct"]
    if stats is None:
        return (
            f"n/a ({profile['n_rbw_no_entry_file_write']} no-write, "
            f"{profile['n_rbw_unknown']} unknown)"
        )
    cell = f"{stats['mean']:.1f}% ({profile['n_rbw_known']})"
    if profile["n_rbw_no_entry_file_write"]:
        cell += f" +{profile['n_rbw_no_entry_file_write']} no-write"
    if profile["n_rbw_unknown"]:
        cell += f" +{profile['n_rbw_unknown']} unknown"
    return cell


def _escape_cell(profile: dict[str, Any]) -> str:
    e = profile["escape_hatch"]
    return f"{e['yes']}/{e['no']}/{e['not_applicable']} ({e['n_unknown']})"


def _blast_cell(profile: dict[str, Any]) -> str:
    """One cell per source, never a pooled figure -- `counts` is null on a
    template-sourced row, so a replace mean across sources would divide by rows
    where no replace could have been observed."""
    by_source = profile["blast_radius_by_source"]
    if not by_source:
        return f"n/a ({profile['n_blast_radius_unknown']} unknown)"
    parts = []
    for source, block in by_source.items():
        total = block["resources_total"]
        repl = block["replaced"]
        part = f"{source}: {total['mean']:.1f} res"
        if repl is not None:
            part += f", {repl['mean']:.1f} repl"
        parts.append(part + f" (n={block['n']})")
    if profile["n_blast_radius_unknown"]:
        parts.append(f"{profile['n_blast_radius_unknown']} unknown")
    return "; ".join(parts)


def _render_cell_table(lines: list[str], cells: list[dict[str, Any]]) -> None:
    lines.append(
        "| Arm | Model | Harness | N valid | Excl. invalid | Success rate "
        "(Wilson 95% CI) | Tokens-to-green median [IQR] (KM, admin-censored) | "
        "Iterations-to-green median [IQR] | Tokens mean±stddev (uncensored) | "
        "n tier1_not_verifiable | rbw% mean (n) | Escape hatch y/n/na (unk) | "
        "Blast radius mean per source |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
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
            # Annotated on the censored FRACTION directly, never gated on
            # median_reached: majority-censored does not imply NE when the
            # censoring happens before the events (km_median_iqr's docstring).
            if tkm["censored_frac"] >= 0.5:
                tokens_cell += f" ({tkm['censored_frac']*100:.0f}% censored)"
            if tkm["median_reached"] and tkm["low_event_count"]:
                tokens_cell += f" (n_events={tkm['n_events']}, low)"
        iters_cell = f"{_fmt(ikm['median'])} [{_fmt(ikm['q25'])}, {_fmt(ikm['q75'])}]" if ikm else "n/a"
        if ikm:
            # Same censored-fraction annotation as tokens_cell above.
            # iterations_to_green_km can also be None -- a cell with zero rows
            # carrying a known n_llm_calls -- mirroring tokens_to_green_km.
            if ikm["censored_frac"] >= 0.5:
                iters_cell += f" ({ikm['censored_frac']*100:.0f}% censored)"
            if ikm["median_reached"] and ikm["low_event_count"]:
                iters_cell += f" (n_events={ikm['n_events']}, low)"
        mean_cell = (
            f"{tstats['mean']:.0f}±{tstats['stddev']:.0f}" if tstats else "n/a"
        )
        prof = c["profile"]
        lines.append(
            f"| {c['arm']} | {c['model']} | {c['harness']} | {c['n_valid']} | "
            f"{c['n_excluded_invalid']} | {success_cell} | {tokens_cell} | "
            f"{iters_cell} | {mean_cell} | {c['n_tier1_not_verifiable']} | "
            f"{_rbw_cell(prof)} | {_escape_cell(prof)} | {_blast_cell(prof)} |"
        )


def _render_attribution(lines: list[str], attribution: dict[str, Any], heading: str) -> None:
    lines.append(heading)
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


def _render_form_section(lines: list[str], form: str, block: dict[str, Any]) -> None:
    """One scenario form's whole output: its holdout headline, its train
    cells, its pooled reference table and its tier attribution. Nothing here is
    ever combined with another form's section."""
    split_comp = block["split_composition"]
    lines.append(f"## Scenario form: {form} ({block['n_rows']} row(s))")
    lines.append("")
    lines.append(
        f"Split composition: {split_comp['n_holdout_rows']} holdout row(s), "
        f"{split_comp['n_train_rows']} train row(s), "
        f"{split_comp['n_unclassified_rows']} unclassified row(s) "
        "(prereg §7.1 -- unclassified rows are pooled into NEITHER table below)."
    )
    lines.append("")

    lines.append(f"### HEADLINE ({form}, holdout scenarios only -- prereg §7.1)")
    lines.append("")
    lines.append(
        "This is the pre-registered primary result for this form. Train-split "
        "scenarios (the ones tuned equipping is explicitly allowed to be "
        "developed against) are reported separately below, never pooled in here."
    )
    lines.append("")
    if block["headline_cells"]:
        _render_cell_table(lines, block["headline_cells"])
    else:
        lines.append("_(no holdout-split rows loaded)_")
    lines.append("")

    lines.append(f"### Train-split cells ({form}) (secondary -- equipping-tunable scenarios)")
    lines.append("")
    if block["train_cells"]:
        _render_cell_table(lines, block["train_cells"])
    else:
        lines.append("_(no train-split rows loaded)_")
    lines.append("")

    lines.append(
        f"### All rows pooled within {form} (train + holdout + unclassified) "
        "-- reference only, NOT the headline"
    )
    lines.append("")
    _render_cell_table(lines, block["cells"])
    lines.append("")
    _render_attribution(lines, block["tier_attribution"], f"### Per-catch tier-attribution table ({form})")
    lines.append("")


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
    forms = report["scenario_forms"]
    lines.append(
        "Scenario forms present: "
        + (", ".join(f"`{f}`" for f in forms) if forms else "_(none)_")
        + ". Forms are NEVER pooled -- each gets its own section below "
        "(DECISIONS.md Amendments 26 §4, 27 §2, 28 §6)."
    )
    if report["pooling_refused"]:
        lines.append("")
        lines.append(
            "**No combined headline is reported.** This directory holds more "
            "than one scenario form, which measure different tasks (and, for "
            "multi-step, a different metric), so a single cross-form number "
            "would describe none of them. Read each form's own HEADLINE table."
        )
    lines.append("")

    if not forms:
        lines.append("_(no rows loaded)_")
        lines.append("")

    for form in forms:
        _render_form_section(lines, form, report["by_scenario_form"][form])

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
    parser.add_argument(
        "results_dir",
        type=Path,
        help=(
            "Directory of result-row files to aggregate (recursive). Rows are "
            "split by `scenario_form` FIRST -- before the train/holdout split "
            "and before the (arm, model, harness) cell -- and forms are never "
            "pooled: a directory holding more than one form gets one section "
            "per form in benchmark.md/benchmark.json and NO combined headline "
            "(`pooling_refused: true`, top-level cells/headline_cells null). A "
            "row with no `scenario_form` is never backfilled: it aborts the "
            "whole run with exit code 2 and no output file. Any other "
            "rejected row is named on stderr and exits 1."
        ),
    )
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
    try:
        report = build_report(rows, errors, max_iters=args.max_iters, max_tokens=args.max_tokens)
    except ScenarioFormMissing as exc:
        # No benchmark.json/benchmark.md is written: a report whose top-level
        # headline is missing the unlabelled rows reads as a clean single-form
        # result, which is the failure this refusal exists to prevent.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for err in errors:
        print(f"rejected row: {err}", file=sys.stderr)

    (out_dir / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "benchmark.md").write_text(render_markdown(report), encoding="utf-8")

    print(f"loaded {report['n_rows_loaded']} row(s), rejected {report['n_rows_rejected']}")
    print(f"wrote {out_dir / 'benchmark.json'}")
    print(f"wrote {out_dir / 'benchmark.md'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
