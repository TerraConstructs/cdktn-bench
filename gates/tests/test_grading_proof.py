"""gates/tests/test_grading_proof.py -- unit coverage for
`gates/grading_proof.py::auto_select_negative()`, added alongside the
benchmark-integrity fix that wired `make check`'s `test-gates` to actually
run `oracles/` + `generator/` (mk/rails.mk finding "the 75 oracles/ +
generator/ tests ... never run in any make target").

`auto_select_negative` itself has NO test coverage anywhere in the repo
before this file -- despite being the piece of `make grading-proof` that
picks, per arm, which `solution/broken/<name>/solve.sh` fixture actually
proves the tier-1 Rego/cfn-guard chain is wired for real (see its own
docstring in gates/grading_proof.py for the full "generalized 2026-08-06"
history this function has: it used to be a spec-wide, then a
predicted-tier-based selector, both of which silently produced zero
results for scenarios like sfn-jsonata/ecs-swappiness whose whole point is
a PER-ARM tier divergence).

These tests build synthetic `RunResult` lists directly (`gates.
oracle_falsifiability.RunResult`) instead of running any real toolchain --
`auto_select_negative` only ever reads `r.label` and `observed_tier(r.detail)`,
both of which are cheap to construct by hand from the exact stdout shapes
`observed_tier()`'s own regexes match (`generator/gen.py`'s
`"== summary: tier0_pass=N tier1_status=X =="` line, and a toolchain-failure
line of the form `"<LABEL> FAILED"`). No toolchain/network dependency, no
skip marker needed -- this is pure unit coverage of one selection function.
"""

from __future__ import annotations

from gates.grading_proof import auto_select_negative
from gates.oracle_falsifiability import RunResult


def _result(label: str, detail: str) -> RunResult:
    # reward/ok are irrelevant to auto_select_negative -- it only reads
    # .label and .detail (via observed_tier()) -- but RunResult requires
    # them, so fill in plausible values matching `detail`'s own shape.
    return RunResult(label=label, reward=0.0, ok=True, detail=detail)


TIER0_TOOLCHAIN_FAIL = "SOME BUILD STEP FAILED\nsee above for the compiler's own error"
TIER0_STRUCTURAL_FAIL = "== summary: tier0_pass=0 tier1_status=SKIP =="
TIER1_CAUGHT = "== summary: tier0_pass=1 tier1_status=FAIL =="
NEVER_CAUGHT = "== summary: tier0_pass=1 tier1_status=PASS =="


class TestAutoSelectNegativeTierSelection:
    """A fixture only counts as a grading-proof negative when it was
    OBSERVED (not merely predicted) to be caught at tier "1" -- a fixture
    caught earlier, at tier "0" (either a toolchain/build failure, or a
    failed tier-0 structural assert), never reaches the Rego/cfn-guard
    chain this gate exists to prove, so it must not be selected."""

    def test_skips_tier0_toolchain_failure_picks_tier1(self):
        results = [
            _result("awscdk/solution/solve.sh", NEVER_CAUGHT),
            _result("awscdk/solution/broken/catch-a/solve.sh", TIER0_TOOLCHAIN_FAIL),
            _result("awscdk/solution/broken/catch-b/solve.sh", TIER1_CAUGHT),
        ]
        picked = auto_select_negative(results, "awscdk")
        assert picked is not None
        assert picked.label == "awscdk/solution/broken/catch-b/solve.sh"

    def test_skips_tier0_structural_failure_picks_tier1(self):
        # tier0_pass=0 (a failed tier-0 structural assert) is a DIFFERENT
        # observed_tier() code path than the toolchain-failure line above
        # (no "<LABEL> FAILED" line at all here) -- both must be treated as
        # tier "0", not selected.
        results = [
            _result("hcl_raw/solution/broken/catch-a/solve.sh", TIER0_STRUCTURAL_FAIL),
            _result("hcl_raw/solution/broken/catch-b/solve.sh", TIER1_CAUGHT),
        ]
        picked = auto_select_negative(results, "hcl_raw")
        assert picked is not None
        assert picked.label == "hcl_raw/solution/broken/catch-b/solve.sh"

    def test_first_tier1_fixture_in_order_wins(self):
        # Two fixtures both reach tier 1 -- the FIRST one in results order
        # (the same order check_arm produces them: declared catches first,
        # then extra fixtures) must win, not the last.
        results = [
            _result("awscdk/solution/broken/catch-a/solve.sh", TIER1_CAUGHT),
            _result("awscdk/solution/broken/catch-b/solve.sh", TIER1_CAUGHT),
        ]
        picked = auto_select_negative(results, "awscdk")
        assert picked is not None
        assert picked.label == "awscdk/solution/broken/catch-a/solve.sh"


class TestAutoSelectNegativeEscapeHatchOrdering:
    """Mirrors sfn-jsonata's own real shape (mode-mixing-jsonpath-artifacts,
    caught at tier "0" on awscdk via the `.jsonata()` factory idiom's `tsc`
    type error, PLUS a non-catch-named
    `mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/` fixture
    that forces the same mistake past the compiler so it genuinely reaches
    tier 1) -- see gates/grading_proof.py's module docstring for the full
    regression history this shape guards against (Amendment 9)."""

    def test_escape_hatch_selected_when_catch_named_fixture_stays_at_tier0(self):
        # The catch-named fixture (declared in spec.catches[], walked
        # first by check_arm) is caught at tier 0 on THIS arm and never
        # reaches tier 1 -- the escape-hatch fixture appearing later in
        # results (not named by any spec.catches[] entry) is what actually
        # exercises tier 1, and must be the one selected.
        results = [
            _result("awscdk/solution/solve.sh", NEVER_CAUGHT),
            _result(
                "awscdk/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh",
                TIER0_TOOLCHAIN_FAIL,
            ),
            _result(
                "awscdk/solution/broken/mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/solve.sh",
                TIER1_CAUGHT,
            ),
        ]
        picked = auto_select_negative(results, "awscdk")
        assert picked is not None
        assert picked.label == (
            "awscdk/solution/broken/mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/solve.sh"
        )

    def test_catch_named_fixture_wins_over_escape_hatch_when_it_itself_reaches_tier1(self):
        # The flip side (hcl_raw's own shape for this same catch): when the
        # catch-named fixture ALREADY reaches tier 1 on this arm, it must
        # win over any later escape-hatch fixture -- walking order (catch
        # first) determines the winner, escape-hatch fixtures are only a
        # fallback for when the primary fixture doesn't reach tier 1.
        results = [
            _result(
                "hcl_raw/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh",
                TIER1_CAUGHT,
            ),
            _result(
                "hcl_raw/solution/broken/mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/solve.sh",
                TIER1_CAUGHT,
            ),
        ]
        picked = auto_select_negative(results, "hcl_raw")
        assert picked is not None
        assert picked.label == "hcl_raw/solution/broken/mode-mixing-jsonpath-artifacts/solve.sh"


class TestAutoSelectNegativeNoTier1Fixture:
    def test_returns_none_when_no_fixture_reaches_tier1(self):
        # Every solution/broken/ fixture on this arm stays at tier 0 (or is
        # never caught at all) -- main() reports this as a per-arm SKIP,
        # not a failure (see gates/grading_proof.py's module docstring:
        # "this arm genuinely has no fixture that reaches tier 1 at all").
        results = [
            _result("terraconstructs/solution/solve.sh", NEVER_CAUGHT),
            _result("terraconstructs/solution/broken/catch-a/solve.sh", TIER0_TOOLCHAIN_FAIL),
            _result("terraconstructs/solution/broken/catch-b/solve.sh", TIER0_STRUCTURAL_FAIL),
            _result("terraconstructs/solution/broken/catch-c/solve.sh", NEVER_CAUGHT),
        ]
        assert auto_select_negative(results, "terraconstructs") is None

    def test_returns_none_on_empty_results(self):
        assert auto_select_negative([], "awscdk") is None

    def test_ignores_non_broken_labels(self):
        # A label that isn't a solution/broken/ fixture at all (e.g. the
        # good solve.sh itself) must never be selected as the negative,
        # even if its own stdout happens to look tier-1-shaped.
        results = [_result("awscdk/solution/solve.sh", TIER1_CAUGHT)]
        assert auto_select_negative(results, "awscdk") is None
