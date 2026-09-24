"""Unit coverage for `gates/grading_proof.py`'s two proof selectors.

`auto_select_negative` picks, per arm, the `solution/broken/<name>/solve.sh`
fixture whose run proves the arm's tier-1 Rego chain is wired for
real; `live_tier_proof` picks the live-tier proof a scenario graded at the live
tier offers instead. Both must select on what a run was OBSERVED to do -- a
spec-wide or predicted-tier selector silently yields nothing for a scenario
whose whole point is a PER-ARM tier divergence (sfn-jsonata, ecs-swappiness).

`RunResult` lists are built by hand rather than by running a toolchain: both
selectors read only `.label`, `.reward` and `.detail`, and `.detail` is cheap to
write in the exact shapes `observed_tier()`'s regexes match (gen.py's
`"== summary: tier0_pass=N tier1_status=X =="` line, and a toolchain-failure
line `"<LABEL> FAILED"`). No toolchain or network dependency, so no skip marker.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from gates import grading_proof
from gates.grading_proof import auto_select_negative, live_tier_proof, main
from gates.oracle_falsifiability import LIVE_ONLY_CONFIRMED_MARKER, RunResult


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
    failed tier-0 structural assert), never reaches the Rego
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


# ---------------------------------------------------------------------------
# live_tier_proof(): the SECOND accepted proof of gradeability
# ---------------------------------------------------------------------------
# A scenario graded at the live tier owns no tier-1 fixture and never will, so
# `make grading-proof` accepts a live-tier proof instead of failing the spec
# outright (DECISIONS.md Amendment 39, "grading-proof accepts a live-tier proof
# of gradeability"). Every condition below is one the gate reads off the run;
# dropping any single one must make the proof unavailable, which is what these
# tests pin.

# The stdout a live-predicted fixture's own host-side run produces: every
# static tier PASSED it (reward 1.0, no tier caught it) and it earned the
# marker by mechanically confirming its static-indistinguishability claim.
LIVE_UNCAUGHT = (
    f"{LIVE_ONLY_CONFIRMED_MARKER}: both shapes synthesize byte-identical artifacts\n"
    "== summary: tier0_pass=1 tier1_status=SKIPPED_NO_ASSERTS =="
)
# Same run WITHOUT the tier-0 summary line: static_tiers.sh never graded an
# artifact, so nothing about tiers was observed at all.
LIVE_UNGRADED = f"{LIVE_ONLY_CONFIRMED_MARKER}: claimed, but the toolchain never produced an artifact"


def _catch(
    name="live-catch",
    *,
    awscdk="live",
    hcl="0",
    override=None,
    modules_override=None,
    applies_to=None,
):
    return SimpleNamespace(
        name=name,
        applies_to=list(applies_to or ("awscdk", "hcl_raw", "terraconstructs")),
        predicted_tier_caught=SimpleNamespace(
            awscdk=awscdk,
            hcl=hcl,
            terraconstructs_override=override,
            hcl_modules_override=modules_override,
        ),
    )


def _spec(catches, *, enabled=True, gating=True, hand_authored=True, arms=("awscdk",)):
    # `verifier.teardown` is present and OFF, which is what spec_model gives a
    # spec that declares no teardown block (`Teardown` is a required field with
    # a default). A double that omitted it would let the gate read the
    # attribute defensively and never be told when it stops existing.
    return SimpleNamespace(
        id="fake-spec",
        arms=SimpleNamespace(enabled_arms=lambda: list(arms)),
        catches=list(catches),
        verifier=SimpleNamespace(
            live_check=SimpleNamespace(
                enabled=enabled, gating=gating, hand_authored=hand_authored
            ),
            teardown=SimpleNamespace(enabled=False, gating=False),
        ),
    )


def _good(arm):
    return RunResult(label=f"{arm}/solution/solve.sh", reward=1.0, ok=True, detail=NEVER_CAUGHT)


def _live_results(detail=LIVE_UNCAUGHT, reward=1.0, name="live-catch", arm="awscdk"):
    return [
        _good(arm),
        RunResult(
            label=f"{arm}/solution/broken/{name}/solve.sh",
            reward=reward,
            ok=True,
            detail=detail,
        ),
    ]


class TestLiveTierProofAccepted:
    def test_accepted_when_every_condition_holds(self):
        proof = live_tier_proof(_live_results(), _spec([_catch()]), "awscdk")
        assert proof is not None
        assert proof.label == "awscdk/solution/broken/live-catch/solve.sh"

    def test_per_arm_resolution_uses_predicted_tier(self):
        # The same catch is tier-0 on the hcl-shaped arms (predicted_tier's
        # `.hcl`), so only awscdk can offer the live proof.
        spec = _spec([_catch()], arms=("awscdk", "hcl_raw"))
        assert live_tier_proof(_live_results(arm="hcl_raw"), spec, "hcl_raw") is None

    @pytest.mark.parametrize(
        "arm,kwargs",
        [
            ("terraconstructs", {"override": "live"}),
            ("hcl_modules", {"modules_override": "live"}),
        ],
    )
    def test_a_per_arm_override_moves_the_tier_on_that_arm_only(self, arm, kwargs):
        """Both Terraform overrides are read, and each is read for its own arm.

        The catch is tier-0 on `.hcl`, so without the override hcl_raw offers no
        live proof and neither does the overridden arm; with it, the overridden
        arm does and hcl_raw still does not. An override that the gate ignored
        would grade a mistake at a tier the spec said it is not caught at.
        """
        arms = ("awscdk", "hcl_raw", arm)
        spec = _spec([_catch(applies_to=arms, **kwargs)], arms=arms)
        assert live_tier_proof(_live_results(arm=arm), spec, arm) is not None
        assert live_tier_proof(_live_results(arm="hcl_raw"), spec, "hcl_raw") is None


class TestLiveTierProofConditionsAreEachLoadBearing:
    """Each condition dropped on its own -- the rest still holding -- must
    withdraw the proof. A live-tier proof asserts that the live tier is the one
    left to decide; every one of these is part of showing that."""

    @pytest.mark.parametrize("field", ["enabled", "gating", "hand_authored"])
    def test_live_check_must_be_enabled_gating_and_hand_authored(self, field):
        spec = _spec([_catch()], **{field: False})
        assert live_tier_proof(_live_results(), spec, "awscdk") is None

    def test_no_catch_predicts_the_live_tier_on_this_arm(self):
        spec = _spec([_catch(awscdk="1")])
        assert live_tier_proof(_live_results(), spec, "awscdk") is None

    def test_catch_does_not_apply_to_this_arm(self):
        spec = _spec([_catch(applies_to=("hcl_raw",))])
        assert live_tier_proof(_live_results(), spec, "awscdk") is None

    def test_fixture_missing_from_the_results(self):
        spec = _spec([_catch(name="absent-catch")])
        assert live_tier_proof(_live_results(), spec, "awscdk") is None

    def test_marker_absent(self):
        # The fixture asserted its tier in a comment instead of earning it.
        detail = "== summary: tier0_pass=1 tier1_status=SKIPPED_NO_ASSERTS =="
        assert live_tier_proof(_live_results(detail=detail), _spec([_catch()]), "awscdk") is None

    def test_no_tier0_summary_means_nothing_was_observed(self):
        # Fail-closed: without the summary line no static tier ever ran, so
        # "survived every static tier" is an assumption, not a reading.
        assert live_tier_proof(_live_results(detail=LIVE_UNGRADED), _spec([_catch()]), "awscdk") is None

    def test_caught_by_a_static_tier(self):
        # tier-1 FAIL: a static tier decided it, so the live tier did not.
        detail = f"{LIVE_ONLY_CONFIRMED_MARKER}\n== summary: tier0_pass=1 tier1_status=FAIL =="
        assert live_tier_proof(_live_results(detail=detail, reward=0.0), _spec([_catch()]), "awscdk") is None

    def test_reward_not_one(self):
        assert live_tier_proof(_live_results(reward=0.0), _spec([_catch()]), "awscdk") is None


# ---------------------------------------------------------------------------
# main(): which proof satisfied the gate, and what it says when none did
# ---------------------------------------------------------------------------


@pytest.fixture
def gate(monkeypatch):
    """Drive `main()` with a synthetic spec and synthetic `check_arm` results:
    the selection and reporting logic is what these tests pin, and running the
    real toolchain would prove nothing extra about it."""

    def _install(spec, results_by_arm):
        monkeypatch.setattr(grading_proof, "load_spec", lambda _path: spec)
        monkeypatch.setattr(
            grading_proof, "check_arm", lambda _spec, arm, _env: results_by_arm[arm]
        )
        monkeypatch.setattr(
            grading_proof, "running_stub", contextlib.contextmanager(lambda: iter([{}]))
        )

    return _install


class TestMainProofKinds:
    def test_tier1_proof_still_accepted(self, gate, capsys):
        arm = "hcl_raw"
        results = [
            _good(arm),
            RunResult(f"{arm}/solution/broken/live-catch/solve.sh", 0.0, True, TIER1_CAUGHT),
        ]
        gate(_spec([_catch(hcl="1")], arms=(arm,)), {arm: results})
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 0
        assert "tier-1 catch" in capsys.readouterr().out

    def test_live_tier_proof_accepted(self, gate, capsys):
        gate(_spec([_catch()]), {"awscdk": _live_results()})
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 0
        out = capsys.readouterr().out
        assert "live-tier catch" in out
        assert "every arm is GRADEABLE" in out

    def test_live_predicted_fixture_caught_at_tier0_fails(self, gate, capsys):
        # Falsifiability's own rule is unchanged: a live-predicted fixture that
        # a static tier catches is a mis-tiered catch, not a proof. It reaches
        # neither selector, so this gate reports no proof at all rather than
        # laundering the tier-0 catch into one.
        detail = f"{LIVE_ONLY_CONFIRMED_MARKER}\n== summary: tier0_pass=0 tier1_status=SKIP =="
        gate(_spec([_catch()]), {"awscdk": _live_results(detail=detail, reward=0.0)})
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 1
        assert "no enabled arm produced any" in capsys.readouterr().err

    @pytest.mark.parametrize("field", ["enabled", "gating", "hand_authored"])
    def test_failure_message_names_every_accepted_proof_kind(self, gate, capsys, field):
        gate(_spec([_catch()], **{field: False}), {"awscdk": _live_results()})
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 1
        err = capsys.readouterr().err
        assert 'observed caught at tier "1"' in err
        assert "live-tier or teardown-tier proof" in err
        assert LIVE_ONLY_CONFIRMED_MARKER in err


# ---------------------------------------------------------------------------
# teardown_tier_proof(): the THIRD accepted proof of gradeability
# ---------------------------------------------------------------------------
# A configuration that applies green, passes the live check and then fails its
# own destroy is invisible to every static tier by construction, so the arm owns
# no tier-1 fixture and the generator-injected destroy is what decides it
# (specs/SCHEMA.md §5.2; DECISIONS.md Amendment 41). The conditions are
# live_tier_proof()'s with one substitution: the TEARDOWN tier must be enabled
# and gating.


def _teardown_spec(catches, *, enabled=True, gating=True, live_gating=True):
    spec = _spec(catches, gating=live_gating)
    spec.verifier.teardown = SimpleNamespace(enabled=enabled, gating=gating)
    return spec


def _teardown_catch(**kw):
    kw.setdefault("awscdk", "teardown")
    return _catch(**kw)


class TestTeardownTierProof:
    def test_accepted_when_every_condition_holds(self):
        proof = grading_proof.teardown_tier_proof(
            _live_results(), _teardown_spec([_teardown_catch()]), "awscdk"
        )
        assert proof is not None
        assert proof.label == "awscdk/solution/broken/live-catch/solve.sh"

    @pytest.mark.parametrize("field", ["enabled", "gating"])
    def test_the_tier_must_be_enabled_and_gating(self, field):
        # An observational teardown records its verdict and leaves the reward
        # alone, so it proves nothing about grading.
        spec = _teardown_spec([_teardown_catch()], **{field: False})
        assert grading_proof.teardown_tier_proof(_live_results(), spec, "awscdk") is None

    def test_a_live_predicted_catch_is_not_a_teardown_proof(self):
        spec = _teardown_spec([_catch()])  # predicts "live" on awscdk
        assert grading_proof.teardown_tier_proof(_live_results(), spec, "awscdk") is None

    def test_marker_absent(self):
        detail = "== summary: tier0_pass=1 tier1_status=SKIPPED_NO_ASSERTS =="
        spec = _teardown_spec([_teardown_catch()])
        assert grading_proof.teardown_tier_proof(_live_results(detail=detail), spec, "awscdk") is None

    def test_caught_by_a_static_tier(self):
        detail = f"{LIVE_ONLY_CONFIRMED_MARKER}\n== summary: tier0_pass=0 tier1_status=SKIP =="
        spec = _teardown_spec([_teardown_catch()])
        assert (
            grading_proof.teardown_tier_proof(
                _live_results(detail=detail, reward=0.0), spec, "awscdk"
            )
            is None
        )

    def test_the_live_check_need_not_gate_for_a_teardown_proof(self):
        # The teardown tier's own gating is what makes the destroy cost a
        # reward; `teardown.enabled` already requires an enabled live check.
        spec = _teardown_spec([_teardown_catch()], live_gating=False)
        assert grading_proof.teardown_tier_proof(_live_results(), spec, "awscdk") is not None


class TestMainAcceptsTheTeardownProof:
    def test_teardown_tier_proof_accepted_and_named(self, gate, capsys):
        gate(
            _teardown_spec([_teardown_catch()]),
            {"awscdk": _live_results()},
        )
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 0
        out = capsys.readouterr().out
        assert "teardown-tier catch" in out
        assert "every arm is GRADEABLE" in out

    def test_the_live_proof_still_wins_when_both_would_apply(self, gate, capsys):
        """A catch resolves to ONE tier per arm, so an arm cannot hold both
        proofs for the same fixture -- the live selector running first is what
        keeps a spec from silently changing which chain it claims to prove."""
        spec = _teardown_spec([_catch()])  # predicts "live" on awscdk
        gate(spec, {"awscdk": _live_results()})
        assert main(["grading_proof.py", "specs/fake.yaml"]) == 0
        out = capsys.readouterr().out
        assert "live-tier catch" in out
        assert "teardown-tier catch" not in out
