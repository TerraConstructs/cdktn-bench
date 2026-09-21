"""The JSONPath -> Rego compiler (generator/jsonpath_rego.py).

Every construct of the grammar is checked twice: once as the stage list the
path parses to, and once by running the EMITTED Rego through `opa` against a
document, so a stage that parses correctly and compiles to rules that mean
something else cannot pass. `resolve_nodes` -- the Python statement of the same
semantics -- is checked against the same documents, since it is what
oracles/tests/test_op_parity.py uses as the reference column.

Cross-engine agreement with the jq backend is that differential test's job, not
this file's; what is pinned here is that the compiler accepts exactly the
grammar jsonpath_jq accepts and that each construct's emitted rules evaluate.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

import gen
from gen import build_tier0_rego_file
from spec_model import load_spec

from jsonpath_rego import (
    Descend,
    Field,
    Filter,
    FieldCond,
    FromJson,
    Unresolvable,
    ValueCond,
    Wildcard,
    _scan_pattern,
    build_tier0_rego,
    parse_jsonpath,
    resolve_nodes,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

requires_opa = pytest.mark.skipif(
    shutil.which("opa") is None, reason="opa is required to evaluate the emitted rules"
)


def _resolved(tmp_path, jsonpath: str, document: object) -> object:
    """The `resolved` map the emitted file exposes, i.e. the node list the
    compiled rules actually collect for one assert."""
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", [("p", jsonpath, "exists", None)]))
    proc = subprocess.run(
        ["opa", "eval", "-f", "json", "-I", "-d", str(policy),
         "data.cdktn_bench.probe.tier0.resolved"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]["p"]


def _outcomes(tmp_path, asserts, document: object) -> dict[str, str]:
    """Each assert's verdict class, read out of the three sets the emitted file
    exposes. A name in two of them, or in none, is itself a failure: they are
    the disjoint, exhaustive three-valued outcome."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", asserts))
    proc = subprocess.run(
        ["opa", "eval", "-f", "json", "-I", "-d", str(policy),
         "data.cdktn_bench.probe.tier0"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
    out = {}
    for name, *_ in asserts:
        classes = [
            c for c in ("held", "contradicted", "unresolvable") if name in value.get(c, [])
        ]
        assert len(classes) == 1, f"{name!r} landed in {classes}"
        out[name] = classes[0]
    return out


# ---------------------------------------------------------------------------
# the grammar
# ---------------------------------------------------------------------------


def test_root_alone_is_the_document_itself() -> None:
    assert parse_jsonpath("$") == []
    assert resolve_nodes({"a": 1}, "$") == [{"a": 1}]


def test_field_access_is_one_stage_per_hop() -> None:
    assert parse_jsonpath("$.a.b") == [Field("a"), Field("b")]
    assert resolve_nodes({"a": {"b": 1}}, "$.a.b") == [1]


def test_a_wildcard_iterates_arrays_and_object_values() -> None:
    """jq's `.[]` covers both, so the compiled `_elems` helper must too --
    a CFN `Resources` map is iterated exactly this way."""
    assert parse_jsonpath("$.a[*]") == [Field("a"), Wildcard()]
    assert resolve_nodes({"a": [1, 2]}, "$.a[*]") == [1, 2]
    assert sorted(resolve_nodes({"a": {"x": 1, "y": 2}}, "$.a[*]")) == [1, 2]


def test_recursive_descent_finds_the_field_at_every_depth() -> None:
    assert parse_jsonpath("$..Name") == [Descend("Name")]
    doc = {"Name": "top", "child": {"Name": "mid", "deep": [{"Name": "leaf"}]}}
    assert sorted(resolve_nodes(doc, "$..Name")) == ["leaf", "mid", "top"]


def test_a_filter_selects_only_matching_elements() -> None:
    assert parse_jsonpath("$.a[?(@.T=='x')]") == [
        Field("a"),
        Filter((FieldCond(("T",), "x"),)),
    ]
    doc = {"a": [{"T": "x", "n": 1}, {"T": "y", "n": 2}]}
    assert resolve_nodes(doc, "$.a[?(@.T=='x')].n") == [1]


def test_a_filter_condition_may_name_a_nested_field() -> None:
    """Without this, a value keyed off a sibling sub-object can only be read
    for ALL elements, so "every rule that expires by image count keeps 10"
    collapses to "some rule keeps 10" -- which a rule keeping 100 alongside
    satisfies."""
    assert parse_jsonpath("$.rules[?(@.selection.countType=='keep')]") == [
        Field("rules"),
        Filter((FieldCond(("selection", "countType"), "keep"),)),
    ]
    doc = {
        "rules": [
            {"selection": {"countType": "keep", "countNumber": 10}},
            {"selection": {"countType": "days", "countNumber": 14}},
        ]
    }
    path = "$.rules[?(@.selection.countType=='keep')].selection.countNumber"
    assert resolve_nodes(doc, path) == [10]


def test_ord_filter_conditions_are_separate_predicate_bodies() -> None:
    assert parse_jsonpath("$.a[?(@.T=='x' || @.T=='y')]") == [
        Field("a"),
        Filter((FieldCond(("T",), "x"), FieldCond(("T",), "y"))),
    ]
    doc = {"a": [{"T": "x"}, {"T": "y"}, {"T": "z"}]}
    assert len(resolve_nodes(doc, "$.a[?(@.T=='x' || @.T=='y')]")) == 2


def test_a_bare_value_filter_tests_the_element_itself() -> None:
    """A wildcard-Resource check needs each resolved value compared with the
    literal `"*"`, not just "does this path exist at all"."""
    assert parse_jsonpath("$.a[?(@=='*')]") == [Field("a"), Filter((ValueCond("*"),))]
    assert resolve_nodes({"a": ["*", "arn:aws:s3:::b"]}, "$.a[?(@=='*')]") == ["*"]


def test_fromjson_decodes_a_json_string_valued_attribute() -> None:
    assert parse_jsonpath("$.blob|fromjson.n") == [Field("blob"), FromJson(), Field("n")]
    doc = {"blob": json.dumps({"n": 42})}
    assert resolve_nodes(doc, "$.blob|fromjson.n") == [42]


def test_fromjson_may_appear_more_than_once() -> None:
    doc = {"blob": json.dumps({"inner": json.dumps({"n": 42})})}
    assert resolve_nodes(doc, "$.blob|fromjson.inner|fromjson.n") == [42]


# ---------------------------------------------------------------------------
# the unresolvable class -- the property this translation exists to preserve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "jsonpath", "document"),
    [
        ("field-into-a-scalar", "$.a.b", {"a": 5}),
        ("wildcard-over-a-scalar", "$.a[*]", {"a": 5}),
        ("wildcard-over-an-absent-key", "$.a[*]", {}),
        ("filter-over-a-scalar", "$.a[?(@.T=='x')]", {"a": 5}),
        ("filter-condition-into-a-scalar", "$.a[?(@.T=='x')]", {"a": [5]}),
        ("fromjson-over-a-number", "$.a|fromjson", {"a": 7}),
        ("fromjson-over-invalid-json", "$.a|fromjson", {"a": "{oops"}),
        ("fromjson-over-an-unpaired-high-surrogate", "$.a|fromjson", {"a": r'"\ud800"'}),
    ],
)
def test_these_are_unresolvable_not_no_node(label: str, jsonpath: str, document: object) -> None:
    """The signature failure mode: "the question could not be asked" must not
    read as "the path found nothing", which `not_exists` would score as a
    pass."""
    with pytest.raises(Unresolvable):
        resolve_nodes(document, jsonpath)


def test_an_absent_key_resolves_to_no_node_rather_than_null() -> None:
    """jq's field access returns null for a missing key and the collected
    array drops null, so an absent key and an explicit null are the same
    "no node" -- but a null on the way THROUGH is propagated, not dropped."""
    assert resolve_nodes({"a": [{"other": 1}]}, "$.a[*].n") == []
    assert resolve_nodes({"a": [{"n": None}]}, "$.a[*].n") == []
    assert resolve_nodes({"a": [{}]}, "$.a[*].n.deep") == []


@requires_opa
def test_the_emitted_rules_report_the_same_unresolvable_reason(tmp_path) -> None:
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", [("p", "$.a|fromjson", "exists", None)]))
    proc = subprocess.run(
        ["opa", "eval", "-f", "raw", "-I", "-d", str(policy),
         "data.cdktn_bench.probe.tier0.render"],
        input=json.dumps({"a": 7}),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.splitlines()[0] == "TIER0_PASS=0"
    assert "UNRESOLVABLE, not contradicted" in proc.stdout
    assert "only strings can be parsed" in proc.stdout


@requires_opa
def test_an_unpaired_surrogate_escape_is_refused_and_a_pair_is_not(tmp_path) -> None:
    r"""jq's decoder rejects a string carrying a lone `\ud800`, Go's accepts it
    and substitutes U+FFFD, so without this rule the assert would reach a
    verdict under Rego and rc 2 under jq -- a reward flip. The paired case is
    the over-refusal this must not cause: an escaped astral character is two
    surrogate escapes and has to keep grading."""
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", [("p", "$.a|fromjson.n", "eq", 42)]))
    for raw, first, needle in (
        (r'{"n":42,"s":"\ud800"}', "TIER0_PASS=0", "unpaired high-surrogate escape"),
        (r'{"n":42,"s":"\ud83d\ude00"}', "TIER0_PASS=1", "PASS [p]"),
    ):
        proc = subprocess.run(
            ["opa", "eval", "-f", "raw", "-I", "-d", str(policy),
             "data.cdktn_bench.probe.tier0.render"],
            input=json.dumps({"a": raw}),
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.splitlines()[0] == first, (raw, proc.stdout)
        assert needle in proc.stdout, (raw, proc.stdout)


@requires_opa
def test_an_unknown_op_is_unresolvable_without_resolving_anything(tmp_path) -> None:
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", [("p", "$.a", "frobnicate", None)]))
    proc = subprocess.run(
        ["opa", "eval", "-f", "json", "-I", "-d", str(policy),
         "data.cdktn_bench.probe.tier0"],
        input=json.dumps({"a": 1}),
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
    assert value["unresolvable"] == ["p"]
    assert value["held"] == []
    assert value["tier0_pass"] == 0


# ---------------------------------------------------------------------------
# the emitted file
# ---------------------------------------------------------------------------


@requires_opa
@pytest.mark.parametrize(
    ("jsonpath", "document", "expected"),
    [
        ("$.a.b", {"a": {"b": 1}}, [1]),
        ("$.a[*]", {"a": [1, 2]}, [1, 2]),
        ("$..n", {"n": 1, "c": {"n": 2}}, [1, 2]),
        ("$.a[?(@.T=='x')].n", {"a": [{"T": "x", "n": 1}, {"T": "y", "n": 2}]}, [1]),
        ("$.a[?(@=='*')]", {"a": ["*", "b"]}, ["*"]),
        ("$.b|fromjson[*].n", {"b": json.dumps([{"n": 1}])}, [1]),
    ],
)
def test_the_emitted_rules_collect_what_the_python_twin_collects(
    tmp_path, jsonpath: str, document: object, expected: list
) -> None:
    assert sorted(_resolved(tmp_path, jsonpath, document), key=repr) == sorted(
        expected, key=repr
    )
    assert sorted(resolve_nodes(document, jsonpath), key=repr) == sorted(
        expected, key=repr
    )


@requires_opa
def test_an_arm_with_no_tier0_assert_still_compiles_and_passes(tmp_path) -> None:
    """Every verdict set has to exist even with nothing to grade, or the one
    `opa eval` static_tiers.sh runs returns undefined and fails a correct
    solution closed."""
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("probe", []))
    proc = subprocess.run(
        ["opa", "eval", "-f", "raw", "-I", "-d", str(policy),
         "data.cdktn_bench.probe.tier0.render"],
        input="{}",
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "TIER0_PASS=1"


@requires_opa
def test_every_op_emits_rules_opa_accepts(tmp_path) -> None:
    ops = {
        "exists": None, "not_exists": None, "eq": "a", "in": ["a"], "contains": "a",
        "regex": "^a$", "set_eq": ["a"], "absent_or_eq": "a", "not_regex": "^z$",
    }
    policy = tmp_path / "tier0.rego"
    policy.write_text(
        build_tier0_rego("probe", [(op, "$.a[*]", op, exp) for op, exp in ops.items()])
    )
    subprocess.run(["opa", "check", str(policy)], capture_output=True, text=True, check=True)


# ---------------------------------------------------------------------------
# what the grammar refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "jsonpath",
    [
        "Resources[*]",
        "$.a[0]",
        "$.a[?(@.n>10)]",
        "$.a[?(@.T=~'x')]",
        "$.a['b']",
        # A digit-leading field name means the number 0 to jq and the key "0"
        # to every other backend, so the shared grammar refuses it.
        "$.v.0",
        "$.0",
        "$.v.1a",
        "$.v..0",
        "$.v[?(@.0=='x')]",
        "$.v[?(@.a.0=='x')]",
    ],
)
def test_anything_outside_the_subset_is_refused(jsonpath: str) -> None:
    """A scenario author who needs richer JSONPath widens the translator
    deliberately, rather than having it silently mis-translate."""
    with pytest.raises(ValueError):
        parse_jsonpath(jsonpath)


def test_two_assert_names_that_slug_to_one_identifier_are_refused() -> None:
    """The Rego identifier is derived from the assert name, and two rules of
    the same name would silently merge into one verdict."""
    with pytest.raises(ValueError, match="compile to the Rego identifier"):
        build_tier0_rego("probe", [("a-b", "$.x", "exists", None), ("a_b", "$.x", "exists", None)])


# ---------------------------------------------------------------------------
# the SHIPPED specs
# ---------------------------------------------------------------------------

# Discovered, never listed -- a spec added tomorrow is checked today.
SPEC_PATHS = [
    p
    for p in sorted((REPO_ROOT / "specs").glob("*.yaml"))
    if p.name != "split.yaml"  # the train/holdout manifest, not a scenario
] + sorted((REPO_ROOT / "specs" / "_toy").glob("*.yaml"))


@requires_opa
@pytest.mark.parametrize("spec_path", SPEC_PATHS, ids=lambda p: p.stem)
def test_every_shipped_spec_emits_a_policy_opa_accepts(spec_path, tmp_path) -> None:
    """`opa check` the tests/tier0.rego each arm and step of every shipped spec
    compiles to.

    Compiled in memory, not read from tasks/**: no spec selects the Rego engine
    today, so nothing is on disk to check -- and the compiler has to keep
    working for every spec anyway, because `make tier0-parity` cross-checks any
    of them by compiling exactly this. An uncompilable policy would otherwise
    surface only at trial time on a spec that flipped the field, where it fails
    closed (tier0_pass=0, not one assert evaluated). The precedent for checking
    it here is oracles/tests/test_emit.py, which `opa check`s the policy
    skeletons it emits."""
    spec = load_spec(spec_path)
    for arm in spec.arms.enabled_arms():
        for step in spec.steps or [None]:
            policy = tmp_path / f"{arm}-{getattr(step, 'name', 'single')}.rego"
            policy.write_text(build_tier0_rego_file(spec, arm, step))
            proc = subprocess.run(
                ["opa", "check", str(policy)], capture_output=True, text=True, check=False
            )
            assert proc.returncode == 0, f"{spec_path.name} {arm}: {proc.stderr}"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("^prod$", (True, False, False)),
        ("^GET /orders$", (True, False, False)),
        (r"^0\.0\.0\.0/0$", (True, False, False)),
        (r"^\w+$", (True, True, False)),
        (r"\d", (False, True, False)),
        # A `$` inside a character class is a literal, and so is an escaped
        # one -- specs/sfn-jsonata.yaml's own pattern is `"\$\.`.
        ("[$]", (False, False, False)),
        (r'"\$\.', (False, False, False)),
        # `\\` is an escaped backslash, so the `d` after it is a plain letter.
        (r"a\\d", (False, False, False)),
        ("(?P<n>a)", (False, False, True)),
        ("arn:aws:s3:::", (False, False, False)),
        # A POSIX bracket expression is the same ASCII-vs-Unicode split with no
        # backslash to key on; `[:ascii:]` is ASCII-only in both flavours.
        ("^[[:alpha:]]+$", (True, True, False)),
        ("^[[:alnum:]_-]+$", (True, True, False)),
        ("[[:^digit:]]", (False, True, False)),
        ("^[[:ascii:]]*$", (True, False, False)),
        # Outside a character class `[:alpha:]` is a set of six literals.
        ("[:alpha:]", (False, False, False)),
    ],
)
def test_the_pattern_screen_sees_only_the_real_construct(
    pattern: str, expected: tuple[bool, bool, bool]
) -> None:
    """`(dollar_anchor, ascii_class, go_named_group)`. Over-reporting is not
    harmless: every flagged construct makes an assert refuse to grade on some
    resolved value, so a screen that fires on an escaped `$` would make a
    corpus assert ungradeable for a construct it does not contain."""
    assert _scan_pattern(pattern) == expected


@requires_opa
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_a_dollar_anchor_refuses_only_a_newline_terminated_value(
    op: str, tmp_path
) -> None:
    r"""RE2's `$` is end-of-text; jq's Oniguruma also matches just before one
    trailing newline. Both engines compile `^prod$` and both answer, with
    OPPOSITE answers on `"prod\n"` -- so the emitted rule refuses that value
    and grades every other one. Per VALUE, not per pattern: refusing the
    pattern outright would make five corpus asserts ungradeable.
    """
    rego = _outcomes(tmp_path / "plain", [("probe", "$.a", op, "^prod$")], {"a": "prod"})
    assert rego["probe"] in ("held", "contradicted")
    rego = _outcomes(tmp_path / "nl", [("probe", "$.a", op, "^prod$")], {"a": "prod\n"})
    assert rego["probe"] == "unresolvable"


@requires_opa
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_an_ascii_class_refuses_only_a_non_ascii_value(op: str, tmp_path) -> None:
    r"""`\w`/`\d`/`\s`/`\b` are ASCII-only under RE2 and Unicode-aware under
    Oniguruma, so `^\w+$` over `"café"` is held for jq and contradicted for
    Rego. The emitted rule refuses the non-ASCII value and leaves ASCII ones
    graded."""
    rego = _outcomes(tmp_path / "ascii", [("probe", "$.a", op, r"^\w+$")], {"a": "prod"})
    assert rego["probe"] in ("held", "contradicted")
    rego = _outcomes(tmp_path / "wide", [("probe", "$.a", op, r"^\w+$")], {"a": "café"})
    assert rego["probe"] == "unresolvable"


@requires_opa
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_a_posix_class_refuses_only_a_non_ascii_value(op: str, tmp_path) -> None:
    """`[[:alpha:]]` and its siblings carry the shorthands' ASCII-vs-Unicode
    split without a backslash, so the screen has to see the bracket form too:
    ungoverned, `not_regex "^[[:alpha:]]+$"` over `"café"` is jq=contradicted
    and rego=held -- a vacuous pass on an absence proof."""
    rego = _outcomes(
        tmp_path / "posix", [("probe", "$.a", op, "^[[:alpha:]]+$")], {"a": "prod"}
    )
    assert rego["probe"] in ("held", "contradicted")
    rego = _outcomes(
        tmp_path / "posixwide", [("probe", "$.a", op, "^[[:alpha:]]+$")], {"a": "café"}
    )
    assert rego["probe"] == "unresolvable"


@requires_opa
@pytest.mark.parametrize("op", ["regex", "not_regex"])
def test_a_go_style_named_group_is_refused_on_every_subject(op: str, tmp_path) -> None:
    """RE2 accepts `(?P<name>...)` and Oniguruma has no such form, so unlike
    the two screens above there is no subject on which the flavours agree and
    nothing to decide per value."""
    for subject in ("a", "zzz"):
        rego = _outcomes(
            tmp_path / f"{op}{subject}", [("probe", "$.a", op, "(?P<n>a)")], {"a": subject}
        )
        assert rego["probe"] == "unresolvable"


# ---------------------------------------------------------------------------
# WHEN the emitted policy reaches a task dir
# ---------------------------------------------------------------------------


class TestOnlyTheRegoEngineShipsAPolicy:
    """jq is the shipped tier-0 grader, so a task dir carries no compiled Rego.

    The compiler stays available behind `oracle.tier0_engine: rego` and to
    `make tier0-parity`, but a jq spec that shipped a tier0.rego would be
    claiming a grader its static_tiers.sh never runs -- and `make gen-all`
    would put 64 unread files under tasks/**.
    """

    @pytest.fixture
    def spec(self):
        return load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")

    @pytest.fixture
    def spec_rego(self, spec):
        flipped = spec.model_copy(deep=True)
        object.__setattr__(flipped.oracle, "tier0_engine", "rego")
        return flipped

    def test_the_shipped_default_is_jq(self, spec):
        assert spec.oracle.tier0_engine == "jq"

    def test_jq_writes_no_policy(self, tmp_path, spec):
        gen.write_tests_dir(spec, "hcl_raw", tmp_path / "tests")
        assert not (tmp_path / "tests" / "tier0.rego").exists()

    def test_rego_writes_the_policy_its_script_reads(self, tmp_path, spec_rego):
        gen.write_tests_dir(spec_rego, "hcl_raw", tmp_path / "tests")
        policy = tmp_path / "tests" / "tier0.rego"
        assert policy.read_text() == build_tier0_rego_file(spec_rego, "hcl_raw")
        tier0 = gen.build_verify_config(spec_rego, "hcl_raw")["tier0"]
        assert tier0["engine"] == "rego"
        assert tier0["query"].endswith(".tier0.render")
        assert 'DIR / "tier0.rego"' in gen.TIERS_PY

    def test_going_back_to_jq_removes_the_stale_policy(self, tmp_path, spec, spec_rego):
        tests_dir = tmp_path / "tests"
        gen.write_tests_dir(spec_rego, "hcl_raw", tests_dir)
        assert (tests_dir / "tier0.rego").exists()
        gen.write_tests_dir(spec, "hcl_raw", tests_dir)
        assert not (tests_dir / "tier0.rego").exists(), (
            "a task dir must not keep a policy the emitted verifier no longer loads"
        )
