"""The normaliser-parity gate's comparison rule, which is not the same rule on
a module-free plan and a module-shaped one.

Zero drift is a statement about the corpus as it stands: no module, so nothing
may move. On a plan that does contain a module the normaliser is supposed to
change the grading -- a resource a grader could not see becomes visible -- so
the rule there is a DIRECTION, and the direction that would hide a resource
again is still drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "gates"))

from plan_normaliser_parity import Cell, summarise, tier0_changes  # noqa: E402


class TestAModuleFreePlanMayNotMoveAtAll:
    def test_identical_outcomes_are_no_change(self) -> None:
        outcomes = {"a": "held", "b": "contradicted"}
        assert tier0_changes(outcomes, dict(outcomes), False) == ([], [])

    @pytest.mark.parametrize(
        "raw,normalised",
        [("unresolvable", "held"), ("held", "contradicted"),
         ("contradicted", "unresolvable")],
    )
    def test_any_move_is_drift(self, raw, normalised) -> None:
        moved, drift = tier0_changes({"a": raw}, {"a": normalised}, False)
        assert moved == []
        assert drift == ["tier-0 a: raw=%s normalised=%s" % (raw, normalised)]

    def test_an_assert_the_other_column_never_graded_is_drift(self) -> None:
        moved, drift = tier0_changes({}, {"a": "held"}, False)
        assert moved == []
        assert "raw=<absent>" in drift[0]


class TestAModuleShapedPlanMayOnlyBecomeMoreVisible:
    @pytest.mark.parametrize("normalised", ["held", "contradicted"])
    def test_moving_off_unresolvable_is_the_mechanism_working(self, normalised) -> None:
        moved, drift = tier0_changes({"a": "unresolvable"}, {"a": normalised}, True)
        assert drift == []
        assert moved == ["tier-0 a: raw=unresolvable normalised=%s" % normalised]

    def test_an_assert_falling_back_to_unresolvable_is_still_drift(self) -> None:
        """A grader that could answer and now cannot is the failure this whole
        gate exists for, module or no module."""
        moved, drift = tier0_changes({"a": "held"}, {"a": "unresolvable"}, True)
        assert moved == []
        assert drift == ["tier-0 a: raw=held normalised=unresolvable"]

    def test_a_verdict_flipping_between_the_two_answerable_values_is_reported(
        self,
    ) -> None:
        moved, drift = tier0_changes({"a": "held"}, {"a": "contradicted"}, True)
        assert drift == []
        assert moved == ["tier-0 a: raw=held normalised=contradicted"]


class TestTheExitCode:
    def test_a_cell_that_only_moved_is_a_pass_and_says_what_moved(self, capsys) -> None:
        cell = Cell(label="s/a/f", arm="hcl-raw", fixture="f", asserts=1,
                    modular=True, identical=False,
                    moved=["tier-0 a: raw=unresolvable normalised=held"])
        assert summarise([cell]) == 0
        printed = capsys.readouterr().out
        assert "[PASS]" in printed
        assert "the hoist changed, in the loud direction" in printed

    def test_a_cell_that_could_not_be_graded_is_not_a_quiet_skip(self) -> None:
        """Only "the toolchain produced no plan" is this gate's non-subject.
        Anything else is a cell that should have been graded and was not."""
        assert summarise([Cell(label="s/a/f", arm="hcl-raw", fixture="f",
                               note="NO_ARTIFACT (toolchain produced none)")]) == 3
        assert summarise([Cell(label="s/a/f", arm="hcl-raw", fixture="f",
                               note="could not read the plan")]) == 1
