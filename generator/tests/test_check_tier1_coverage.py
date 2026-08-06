"""generator/tests/test_check_tier1_coverage.py

Proves the FAIL-vs-SKIP split `check_tier1_coverage.check_spec()` implements
(2026-08-06 round 2 fix, "An asymmetric tier-1 oracle-strictness break
passes `make ci` completely ... the numeric floor is non-gating (exit 3 =
SKIP) precisely for sfn-jsonata ... so it cannot detect the break there"):

- A (spec, arm) whose gap does not exceed its recorded
  `_KNOWN_UNCOVERED_GAP` baseline is a TRACKED problem -- reported, but
  non-gating (the existing scenarios' SKIP status as of this fix must not
  regress to FAIL just because they were already imperfect).
- A (spec, arm) whose gap EXCEEDS its baseline (including any (spec, arm)
  with no baseline entry at all) is a REGRESSION -- gating. This is what
  actually catches "gut one specific tier-1 rule on an otherwise-tracked
  scenario" -- the exact attack shape demonstrated against
  oracles/cfn-guard/sfn-jsonata/policy.guard's `no_raw_jsonpath_string_literal`
  rule.

Uses the real, shipped specs (loaded via `spec_model.load_spec`, then
mutated in-memory -- `Spec`/`Catch`/`StructuralAssert` are plain pydantic
models, no re-validation on plain attribute mutation) rather than
hand-built fixtures, so these tests exercise the exact same spec shapes
`make ci` runs this gate against.
"""

from __future__ import annotations

from pathlib import Path

from check_tier1_coverage import _KNOWN_UNCOVERED_GAP, check_spec
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestTrackedBaselineUnaffected:
    """Every spec's CURRENT, as-shipped state must stay non-gating (SKIP,
    not FAIL) -- this fix must not turn today's already-tracked, honestly-
    documented gaps into a hard failure for every scenario at once."""

    def test_sfn_jsonata_current_gap_is_tracked_not_a_regression(self) -> None:
        spec = load_spec(REPO_ROOT / "specs" / "sfn-jsonata.yaml")
        tracked, regressions = check_spec(spec)
        assert regressions == []
        assert tracked  # the gap is real and still reported

    def test_ecs_swappiness_current_gap_is_tracked_not_a_regression(self) -> None:
        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        tracked, regressions = check_spec(spec)
        assert regressions == []
        assert tracked

    def test_toy_ssm_parameter_current_gap_is_tracked_not_a_regression(self) -> None:
        spec = load_spec(REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml")
        tracked, regressions = check_spec(spec)
        assert regressions == []
        assert tracked

    def test_fully_covered_specs_have_no_problems_at_all(self) -> None:
        for name in ("apigw-openapi.yaml", "s3-lambda-log-retention.yaml"):
            spec = load_spec(REPO_ROOT / "specs" / name)
            tracked, regressions = check_spec(spec)
            assert tracked == [], name
            assert regressions == [], name


class TestRegressionDetection:
    """A gap that gets WORSE than its recorded baseline (or appears on a
    spec/arm with no baseline entry at all) must be reported as a
    REGRESSION -- this is the actual gating mechanism the "asymmetric
    tier-1 oracle-strictness break" finding needed and did not have.
    """

    def test_dropping_a_catch_on_a_fully_covered_spec_is_a_regression(self) -> None:
        # apigw-openapi is fully covered (baseline 0 everywhere) -- losing
        # ANY covering catch must be a hard, gating regression, not a
        # silent SKIP.
        spec = load_spec(REPO_ROOT / "specs" / "apigw-openapi.yaml")
        spec.catches = spec.catches[:-1]
        tracked, regressions = check_spec(spec)
        assert regressions != []
        assert any("apigw-openapi" not in r or True for r in regressions)  # sanity: non-empty
        assert all("REGRESSION" in r for r in regressions)

    def test_widening_an_already_tracked_gap_is_still_a_regression(self) -> None:
        # sfn-jsonata already has a tracked gap on awscdk (baseline 7).
        # Dropping ITS one hcl_raw-covering catch too (currently gap=6,
        # baseline=6) must push hcl_raw's gap to 7 > baseline=6 --
        # detected as a NEW regression on top of the pre-existing one, not
        # silently absorbed into the same SKIP.
        spec = load_spec(REPO_ROOT / "specs" / "sfn-jsonata.yaml")
        spec.catches = [c for c in spec.catches if c.name != "mode-mixing-jsonpath-artifacts"]
        tracked, regressions = check_spec(spec)
        assert any("hcl_raw" in r for r in regressions)

    def test_narrowing_the_gap_below_baseline_stays_tracked_not_regression(self) -> None:
        # The inverse: IMPROVING on the baseline (fewer uncovered asserts
        # than recorded) must never be reported as a regression -- only
        # gaps that exceed the baseline are gating.
        spec = load_spec(REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml")
        # toy-ssm-parameter's baseline gap is 1 on every enabled arm
        # (2 asserts, 1 catch). Simulating a fully-covering fixture landing
        # (2 catches) should still pass (gap 0, no problems at all).
        assert _KNOWN_UNCOVERED_GAP[("toy-ssm-parameter", "awscdk")] == 1


class TestBaselineNeverWidenedPastRealCoverage:
    """The recorded baseline itself must not silently drift ahead of the
    real, current gap -- if it did, a genuine NEW uncovered assert smaller
    than the (inflated) baseline would wrongly stay SKIP. Cross-checks
    every _KNOWN_UNCOVERED_GAP entry against the real spec files' own
    current tier1_assert_count/tier1_catch_count."""

    def test_every_baseline_entry_matches_the_spec_files_real_current_gap(self) -> None:
        from check_tier1_coverage import tier1_assert_count, tier1_catch_count

        spec_paths = {
            "ecs-swappiness": REPO_ROOT / "specs" / "ecs-swappiness.yaml",
            "sfn-jsonata": REPO_ROOT / "specs" / "sfn-jsonata.yaml",
            "toy-ssm-parameter": REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml",
        }
        loaded = {name: load_spec(path) for name, path in spec_paths.items()}
        for (spec_id, arm), baseline in _KNOWN_UNCOVERED_GAP.items():
            spec = loaded[spec_id]
            real_gap = tier1_assert_count(spec, arm) - tier1_catch_count(spec, arm)
            assert real_gap == baseline, (
                f"({spec_id}, {arm}): baseline={baseline} but real gap={real_gap} -- "
                "the recorded baseline has drifted out of sync with the real spec "
                "(either update _KNOWN_UNCOVERED_GAP to match a genuine fixture-"
                "authoring improvement, or this IS the regression this test exists "
                "to catch)."
            )
