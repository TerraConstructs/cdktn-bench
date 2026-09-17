"""The JSONPath -> jq translator's filter grammar (generator/jsonpath_jq.py).

Only the NESTED filter condition is covered here; the rest of the grammar is
exercised end-to-end by every generated tests/static_tiers.sh and by
oracles/tests/test_op_parity.py. It gets its own cases because it is the one
condition shape whose absence silently narrows what a spec can assert: without
it, a value nested under a sibling sub-object can only be read for ALL elements
of an array, so "every rule that expires by image count keeps 10" collapses to
"some rule keeps 10" -- which a rule keeping 100 alongside satisfies.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from jsonpath_jq import jsonpath_to_jq

POLICY = {
    "rules": [
        {"selection": {"countType": "imageCountMoreThan", "countNumber": 10}},
        {"selection": {"countType": "sinceImagePushed", "countNumber": 14}},
    ]
}


def _jq(filter_body: str, document: object) -> object:
    proc = subprocess.run(
        ["jq", "-c", f"[ {filter_body} ]"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def test_a_nested_condition_compiles_to_a_field_chain() -> None:
    assert jsonpath_to_jq(
        "$.rules[?(@.selection.countType=='imageCountMoreThan')].selection.countNumber"
    ) == '.rules | .[] | select(.selection.countType=="imageCountMoreThan") | .selection.countNumber'


def test_it_selects_only_the_matching_elements() -> None:
    """The days-based rule's countNumber is a number of DAYS, and reading it as
    a retained image count is the mis-scoring this condition shape avoids."""
    body = jsonpath_to_jq(
        "$.rules[?(@.selection.countType=='imageCountMoreThan')].selection.countNumber"
    )
    assert _jq(body, POLICY) == [10]


def test_the_unfiltered_path_still_reads_every_rule() -> None:
    body = jsonpath_to_jq("$.rules[*].selection.countNumber")
    assert _jq(body, POLICY) == [10, 14]


def test_a_condition_that_is_not_an_equality_is_still_refused() -> None:
    """Numeric comparison is NOT in the grammar. A spec that needs "keeps more
    than 10" must express it as a set of allowed counts, not smuggle an
    operator past a translator that would drop it."""
    with pytest.raises(ValueError, match="unsupported filter condition"):
        jsonpath_to_jq("$.rules[?(@.selection.countNumber>10)]")
