"""generator/tests/test_split.py -- unit coverage for the train/holdout
scenario split (generator/split.py, DECISIONS.md Amendment 10, prereg
§7.1). Pure unit tests of `compute_split`/`load_split`/`spec_group` --
no toolchain/network dependency, always runs under `make test-gates`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from split import (
    SPLIT_PATH,
    compute_split,
    discover_spec_ids,
    load_split,
    render_split_yaml,
    spec_group,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestComputeSplit:
    def test_deterministic_across_calls(self):
        ids = ["a", "b", "c", "d"]
        first = compute_split(ids)
        second = compute_split(ids)
        assert first == second

    def test_deterministic_regardless_of_input_order(self):
        assert compute_split(["a", "b", "c", "d"]) == compute_split(["d", "c", "b", "a"])

    def test_every_id_assigned_train_or_holdout(self):
        ids = [f"scenario-{i}" for i in range(11)]
        assignments = compute_split(ids)
        assert set(assignments) == set(ids)
        for a in assignments.values():
            assert a["group"] in ("train", "holdout")

    def test_four_scenarios_split_2_2(self):
        # The real seed-scenario set as of Slice D/E -- 60% of 4 rounds
        # (round-half-up) to n_train=2, matching DECISIONS.md Amendment 10.
        ids = ["apigw-openapi", "ecs-swappiness", "s3-lambda-log-retention", "sfn-jsonata"]
        assignments = compute_split(ids)
        n_train = sum(1 for a in assignments.values() if a["group"] == "train")
        n_holdout = sum(1 for a in assignments.values() if a["group"] == "holdout")
        assert n_train == 2
        assert n_holdout == 2

    def test_matches_committed_split_yaml(self):
        """The committed specs/split.yaml must be exactly what
        compute_split() produces from today's real spec ids -- if this
        test goes red, someone hand-edited split.yaml (or added/removed a
        specs/*.yaml without re-running `generator/split.py --write`),
        exactly the drift this file's own header comment warns against."""
        ids = discover_spec_ids()
        expected = compute_split(ids)
        committed = load_split()
        for spec_id, exp in expected.items():
            got = committed["assignments"].get(spec_id)
            assert got is not None, f"specs/split.yaml has no entry for {spec_id!r}"
            assert got["group"] == exp["group"], (
                f"{spec_id!r}: committed group {got['group']!r} != "
                f"recomputed {exp['group']!r} -- re-run "
                f"`uv run python generator/split.py --write`"
            )

    def test_rounding_is_round_half_up(self):
        # 5 ids * 0.6 = 3.0 exactly -> n_train=3 (no rounding ambiguity).
        assignments = compute_split([f"id{i}" for i in range(5)])
        assert sum(1 for a in assignments.values() if a["group"] == "train") == 3
        # 3 ids * 0.6 = 1.8 -> round-half-up -> n_train=2.
        assignments3 = compute_split([f"id{i}" for i in range(3)])
        assert sum(1 for a in assignments3.values() if a["group"] == "train") == 2

    def test_score_is_stable_per_id_independent_of_other_ids(self):
        """An id's own SCORE (not necessarily its group) never changes when
        other ids are added/removed -- only the cutoff RANK does. This is
        the property the re-split procedure (generator/split.py's own
        docstring) leans on: a resplit is a cutoff shift over a fixed
        per-id ranking, not a full reshuffle."""
        small = compute_split(["a", "b"])
        large = compute_split(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])
        assert small["a"]["score"] == large["a"]["score"]
        assert small["b"]["score"] == large["b"]["score"]


class TestRenderAndLoadRoundTrip:
    def test_render_parses_back_to_same_assignments(self, tmp_path):
        ids = ["scenario-a", "scenario-b", "scenario-c"]
        assignments = compute_split(ids)
        rendered = render_split_yaml(assignments, generated_at="2026-01-01")
        parsed = yaml.safe_load(rendered)
        assert parsed["assignments"].keys() == set(ids)
        for spec_id, a in assignments.items():
            assert parsed["assignments"][spec_id]["group"] == a["group"]
            assert parsed["assignments"][spec_id]["score"] == a["score"]
            assert parsed["assignments"][spec_id]["rank"] == a["rank"]


class TestSpecGroup:
    def test_known_train_scenario(self):
        assert spec_group("ecs-swappiness") == "train"

    def test_known_holdout_scenario(self):
        assert spec_group("sfn-jsonata") == "holdout"

    def test_unknown_spec_returns_none(self):
        assert spec_group("some-scenario-not-yet-split") is None

    def test_missing_split_file_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "nope.yaml"
        with pytest.raises(FileNotFoundError):
            load_split(missing)

    def test_uses_passed_split_data_without_reloading(self):
        fake = {"assignments": {"foo": {"group": "holdout", "score": "x", "rank": 0}}}
        assert spec_group("foo", split_data=fake) == "holdout"
        assert spec_group("bar", split_data=fake) is None

    def test_invalid_group_value_raises(self):
        fake = {"assignments": {"foo": {"group": "bogus", "score": "x", "rank": 0}}}
        with pytest.raises(ValueError):
            spec_group("foo", split_data=fake)


class TestDiscoverSpecIds:
    def test_excludes_split_yaml_itself(self):
        ids = discover_spec_ids()
        assert "split" not in ids  # split.yaml's own stem must never appear as a scenario id

    def test_finds_the_real_seed_scenarios(self):
        ids = discover_spec_ids()
        for expected in (
            "apigw-openapi",
            "ecs-swappiness",
            "s3-lambda-log-retention",
            "sfn-jsonata",
        ):
            assert expected in ids

    def test_excludes_toy_specs_subdir(self):
        # specs/_toy/toy-ssm-parameter.yaml lives one directory deeper --
        # the non-recursive specs/*.yaml glob must not reach it.
        ids = discover_spec_ids()
        assert "toy-ssm-parameter" not in ids


def test_split_path_points_at_specs_split_yaml():
    assert SPLIT_PATH == REPO_ROOT / "specs" / "split.yaml"
