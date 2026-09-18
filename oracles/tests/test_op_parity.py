r"""Differential test over THREE implementations of the tier-0 op table
(`specs/SCHEMA.md` §4.2), compared on the THREE-VALUED outcome -- held,
contradicted, unresolvable -- not on a pass/fail bool:

  bash/jq  generator/gen.py's ASSERT_LIB_SH over jsonpath_jq.py's compiled
           filter -- the grader a trial runs; its exit status IS the outcome.
  Python   oracles/lib/structural.py's `apply_op`, over nodes from
           jsonpath_rego.py::resolve_nodes -- NOT `structural.resolve`, whose
           jsonpath-ng answers "no match" where jq raises.
  Rego     jsonpath_rego.py's compiled tests/tier0.rego under `opa`.

Rego turns most errors into silent undefined, so a `|fromjson` over a number, a
filter applied to a scalar or an unknown op would each read as "the path found
no node" -- a vacuous pass -- unless the compiler emits an explicit rule for
it. Cells the three engines CANNOT agree on (§4.2's three regex flavours, jq's
subsequence `index`) are pinned per column instead, in the direction where an
inapplicable pattern is unresolvable, never a verdict.

Requires `jq`, `bash` and `opa` on PATH.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import ASSERT_LIB_SH  # noqa: E402
from jsonpath_jq import jsonpath_to_jq  # noqa: E402
from jsonpath_rego import (  # noqa: E402
    Unresolvable,
    build_tier0_rego,
    resolve_nodes,
)

from oracles.lib.structural import apply_op  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None
    or shutil.which("bash") is None
    or shutil.which("opa") is None,
    reason="jq, bash and opa are required to exercise all three graders",
)

HELD, CONTRADICTED, UNRESOLVABLE = "held", "contradicted", "unresolvable"
_BY_RC = {0: HELD, 1: CONTRADICTED, 2: UNRESOLVABLE}

# Every op the tier-0 table defines. The matrix runs all nine against every
# document shape, because an op's multiplicity and flatten rules interact with
# the shape (one node vs many, a list-valued node vs a scalar one), and it is
# those interactions, not the ops in isolation, that the matrix exists to
# compare.
OPS = (
    "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
    "absent_or_eq", "not_regex",
)


@dataclass(frozen=True)
class Shape:
    """One (path, document) pair: the resolution situation under test."""

    label: str
    jsonpath: str
    document: object
    # `expected` for the value ops; the regex ops get `pattern` instead.
    probe: object = "a"
    pattern: str = "^a$"
    ops: tuple[str, ...] = field(default=OPS)


def _expected_for(op: str, shape: Shape) -> object:
    if op in ("exists", "not_exists"):
        return None
    if op in ("regex", "not_regex"):
        return shape.pattern
    if op in ("in", "set_eq"):
        return [shape.probe]
    return shape.probe


# ---------------------------------------------------------------------------
# the three columns
# ---------------------------------------------------------------------------


def _bash_outcome(tmp_path: Path, jsonpath: str, op: str, expected: object, document: object) -> str:
    """Run the REAL assert_check() bash function, as generated into every
    task's tests/_assert_lib.sh, and read its three-valued exit status."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    lib_path = tmp_path / "_assert_lib.sh"
    lib_path.write_text(ASSERT_LIB_SH)
    doc_path = tmp_path / "doc.json"
    doc_path.write_text(json.dumps(document))
    script = (
        f"source {shlex.quote(str(lib_path))}\n"
        f"assert_check name {shlex.quote(jsonpath_to_jq(jsonpath))} {shlex.quote(op)} "
        f"{shlex.quote(json.dumps(expected))} {shlex.quote(str(doc_path))}\n"
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert proc.returncode in _BY_RC, (
        f"assert_check returned {proc.returncode}, which is outside the "
        f"three-valued contract: {proc.stdout}{proc.stderr}"
    )
    return _BY_RC[proc.returncode]


def _python_outcome(jsonpath: str, op: str, expected: object, document: object) -> str:
    try:
        nodes = resolve_nodes(document, jsonpath)
    except Unresolvable:
        return UNRESOLVABLE
    try:
        held = apply_op(op, expected, nodes)
    except (ValueError, re.error):
        # An op the table does not define, an `expected` the set/member ops
        # cannot use, or a pattern Python's own engine will not parse: a
        # library defect, never a verdict about the artifact. `re.error` is not
        # a ValueError, so without it an unparsable pattern would surface as a
        # harness ERROR instead of as one of the three outcomes.
        return UNRESOLVABLE
    return HELD if held else CONTRADICTED


def _rego_outcomes(
    tmp_path: Path, asserts: list[tuple[str, str, str, object]], document: object
) -> dict[str, str]:
    """Compile and evaluate one tests/tier0.rego holding every assert of one
    shape, and read each assert's verdict class out of the three sets."""
    policy = tmp_path / "tier0.rego"
    policy.write_text(build_tier0_rego("parity", asserts))
    proc = subprocess.run(
        ["opa", "eval", "-f", "json", "-I", "-d", str(policy), "data.cdktn_bench.parity.tier0"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"opa eval failed: {proc.stderr}\n{policy.read_text()}"
    value = json.loads(proc.stdout)["result"][0]["expressions"][0]["value"]
    outcomes: dict[str, str] = {}
    for name, *_ in asserts:
        classes = [c for c in (HELD, CONTRADICTED, UNRESOLVABLE) if name in value.get(c, [])]
        assert len(classes) == 1, (
            f"{name!r} landed in {classes} -- the three verdict classes must be "
            f"disjoint and exhaustive for every assert"
        )
        outcomes[name] = classes[0]
    return outcomes


def _agree(tmp_path: Path, jsonpath: str, op: str, expected: object, document: object) -> str:
    """Assert all three graders reach the same three-valued outcome, and
    return it so a caller can pin WHICH outcome that is."""
    bash = _bash_outcome(tmp_path, jsonpath, op, expected, document)
    py = _python_outcome(jsonpath, op, expected, document)
    rego = _rego_outcomes(tmp_path, [("probe", jsonpath, op, expected)], document)["probe"]
    assert bash == py == rego, (
        f"op parity violation: op={op!r} expected={expected!r} jsonpath={jsonpath!r} "
        f"bash={bash} python={py} rego={rego}"
    )
    return bash


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

SHAPES = (
    Shape("zero-nodes", "$.Items[*].Name", {"Items": []}),
    Shape("one-node", "$.Items[*].Name", {"Items": [{"Name": "a"}]}),
    Shape("many-nodes-equal", "$.Items[*].Name", {"Items": [{"Name": "a"}, {"Name": "a"}]}),
    Shape("many-nodes-distinct", "$.Items[*].Name", {"Items": [{"Name": "a"}, {"Name": "b"}]}),
    # jq drops JSON null from the collected array, so an explicit null and an
    # absent key are the same "no node": a `[null]` collection of length 1
    # would fail every not_exists assert unconditionally.
    Shape("explicit-null", "$.Items[*].Name", {"Items": [{"Name": None}]}),
    Shape("absent-key", "$.Items[*].Name", {"Items": [{"Other": 1}]}),
    Shape("absent-key-nested", "$.Items[*].Deep.Name", {"Items": [{}]}),
    # An absent PARENT is not "no node": jq cannot iterate null and raises.
    Shape("absent-parent", "$.Items[*].Name", {}),
    Shape("wildcard-on-scalar", "$.Items[*].Name", {"Items": 5}),
    Shape("wildcard-on-string", "$.Items[*].Name", {"Items": "nope"}),
    # jq's `.[]` iterates an OBJECT's values as well as an array's elements.
    Shape("wildcard-on-object", "$.Items[*].Name", {"Items": {"k": {"Name": "a"}}}),
    Shape("field-on-scalar", "$.Items.Name", {"Items": 5}),
    Shape("field-on-array", "$.Items.Name", {"Items": [1]}),
    # `in`/`set_eq` flatten EXACTLY one level; one deeper and the list itself
    # is the member under test.
    Shape("list-valued-node", "$.Items[*].Name", {"Items": [{"Name": ["a", "b"]}]}),
    Shape("list-valued-node-single", "$.Items[*].Name", {"Items": [{"Name": ["a"]}]}),
    # `in` is excluded here and pinned on its own below: it is the one cell
    # where the three columns cannot be reconciled without moving every
    # already-generated tests/_assert_lib.sh.
    Shape(
        "doubly-nested-list",
        "$.Items[*].Name",
        {"Items": [{"Name": [["a"]]}]},
        ops=tuple(op for op in OPS if op != "in"),
    ),
    Shape("object-valued-node", "$.Items[*].Name", {"Items": [{"Name": {"k": "a"}}]}),
    Shape("number-valued-node", "$.Items[*].Name", {"Items": [{"Name": 42}]}, probe=42),
    Shape("bool-valued-node", "$.Items[*].Name", {"Items": [{"Name": True}]}, probe=True),
    Shape(
        "fromjson-ok",
        "$.Blob|fromjson[*].Name",
        {"Blob": json.dumps([{"Name": "a"}])},
    ),
    Shape("fromjson-non-string", "$.Blob|fromjson[*].Name", {"Blob": 7}),
    Shape("fromjson-null", "$.Blob|fromjson[*].Name", {"Blob": None}),
    Shape("fromjson-invalid-json", "$.Blob|fromjson[*].Name", {"Blob": "{oops"}),
    Shape(
        "fromjson-twice",
        "$.Blob|fromjson.Inner|fromjson.Name",
        {"Blob": json.dumps({"Inner": json.dumps({"Name": "a"})})},
    ),
    Shape("filter-match", "$.Items[?(@.T=='x')].Name", {"Items": [{"T": "x", "Name": "a"}]}),
    Shape("filter-no-match", "$.Items[?(@.T=='x')].Name", {"Items": [{"T": "y", "Name": "a"}]}),
    Shape("filter-on-non-object", "$.Items[?(@.T=='x')].Name", {"Items": [5]}),
    Shape("filter-on-null-element", "$.Items[?(@.T=='x')].Name", {"Items": [None]}),
    Shape("filter-on-non-iterable", "$.Items[?(@.T=='x')].Name", {"Items": 5}),
    Shape(
        "filter-nested-field",
        "$.rules[?(@.selection.countType=='keep')].selection.countNumber",
        {"rules": [{"selection": {"countType": "keep", "countNumber": "a"}}]},
    ),
    Shape(
        "filter-nested-field-on-scalar",
        "$.rules[?(@.selection.countType=='keep')].selection.countNumber",
        {"rules": [{"selection": 5}]},
    ),
    Shape(
        "filter-ord",
        "$.Items[?(@.T=='x' || @.T=='y')].Name",
        {"Items": [{"T": "y", "Name": "a"}]},
    ),
    # jq's `or` short-circuits, so the field condition never indexes the scalar
    # element the bare-value condition already matched.
    Shape(
        "filter-ord-short-circuits",
        "$.Items[?(@=='a' || @.T=='x')]",
        {"Items": ["a"]},
    ),
    Shape(
        "filter-ord-second-cond-errors",
        "$.Items[?(@=='zzz' || @.T=='x')]",
        {"Items": ["a"]},
    ),
    Shape("filter-bare-value", "$.Items[?(@=='a')]", {"Items": ["a", "b"]}),
    Shape("filter-bare-value-no-match", "$.Items[?(@=='a')]", {"Items": ["b"]}),
    Shape(
        "descend-several-depths",
        "$..Name",
        {"Name": "a", "child": {"Name": "a", "deep": {"Name": "a"}}},
    ),
    Shape(
        "descend-through-arrays",
        "$..Name",
        {"list": [{"Name": "a"}, {"wrap": {"Name": "a"}}]},
    ),
    Shape("descend-no-hit", "$..Name", {"other": {"x": 1}}),
    Shape("descend-then-field", "$..Deep.Name", {"Deep": {"Name": "a"}, "c": {"Deep": {}}}),
    Shape("root-is-the-node", "$.Name", {"Name": "a"}),
    # Type crossings Python `==` gets wrong and both graders get right: JSON
    # keeps `true` and `1` distinct types, and a plan-JSON boolean attribute
    # compared against a numeric `expected` is the realistic slip.
    Shape("bool-probe-over-number-node", "$.Items[*].Name", {"Items": [{"Name": 1}]}, probe=True),
    Shape("number-probe-over-bool-node", "$.Items[*].Name", {"Items": [{"Name": True}]}, probe=1),
    Shape("zero-probe-over-false-node", "$.Items[*].Name", {"Items": [{"Name": False}]}, probe=0),
    # ...and the crossing that goes the other way: an integral float and the
    # int of the same magnitude are ONE number in JSON, so these must HOLD.
    Shape("float-probe-over-int-node", "$.Items[*].Name", {"Items": [{"Name": 1}]}, probe=1.0),
    Shape("int-probe-over-float-node", "$.Items[*].Name", {"Items": [{"Name": 1.0}]}, probe=1),
)


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.label)
def test_every_op_agrees_on_this_shape(shape: Shape, tmp_path: Path) -> None:
    asserts = [
        (f"op-{op}", shape.jsonpath, op, _expected_for(op, shape)) for op in shape.ops
    ]
    rego = _rego_outcomes(tmp_path, asserts, shape.document)
    divergences = []
    for name, jsonpath, op, expected in asserts:
        bash = _bash_outcome(tmp_path / op, jsonpath, op, expected, shape.document)
        py = _python_outcome(jsonpath, op, expected, shape.document)
        if not bash == py == rego[name]:
            divergences.append(
                f"  op={op} expected={expected!r}: bash={bash} python={py} rego={rego[name]}"
            )
    assert not divergences, (
        f"shape {shape.label!r} ({shape.jsonpath}) diverges:\n" + "\n".join(divergences)
    )


def test_an_unknown_op_is_unresolvable_in_all_three(tmp_path: Path) -> None:
    """Never a verdict: an op the grader does not implement is a library
    defect, and reporting it as "contradicted" points the operator at the
    artifact instead of at the oracle."""
    doc = {"Items": [{"Name": "a"}]}
    assert _agree(tmp_path, "$.Items[*].Name", "frobnicate", "a", doc) == UNRESOLVABLE


def test_a_non_list_expected_is_unresolvable_for_the_set_ops(tmp_path: Path) -> None:
    """`in` and `set_eq` are defined over a list. jq reaches for `index`, which
    on a STRING silently becomes a substring search and returns a verdict; both
    other columns refuse, so this is checked as a two-column agreement and
    documented as the one place the engines cannot be reconciled."""
    doc = {"Items": [{"Name": "a"}]}
    for op in ("in", "set_eq"):
        assert _python_outcome("$.Items[*].Name", op, "a", doc) == UNRESOLVABLE
        rego = _rego_outcomes(tmp_path, [("probe", "$.Items[*].Name", op, "a")], doc)
        assert rego["probe"] == UNRESOLVABLE


def test_jq_in_reads_an_array_member_as_a_subsequence(tmp_path: Path) -> None:
    """THE ONE KNOWN DIVERGENCE, pinned here so it cannot be discovered as a
    grading surprise.

    `in` flattens one level and asks whether each remaining value is a member
    of `expected`. The bash grader asks it as `$e | index($x) != null`, and
    jq's `index` with an ARRAY argument is a SUBSEQUENCE search, not an element
    test: `["a"] | index(["a"])` is 0, so a doubly-nested node passes. The
    Python and Rego columns both ask for element membership, which is what
    SCHEMA.md §4.2 defines.

    Unreachable on the corpus -- every `in` assert resolves to numbers or to
    lists of strings, so one level of flattening always leaves scalars -- and
    fixing the bash side would move every already-generated
    tests/_assert_lib.sh, so it is corrected by the removal of the jq backend
    rather than ahead of it.
    """
    doc = {"Items": [{"Name": [["a"]]}]}
    assert _bash_outcome(tmp_path, "$.Items[*].Name", "in", ["a"], doc) == HELD
    assert _python_outcome("$.Items[*].Name", "in", ["a"], doc) == CONTRADICTED
    rego = _rego_outcomes(tmp_path, [("probe", "$.Items[*].Name", "in", ["a"])], doc)
    assert rego["probe"] == CONTRADICTED


@pytest.mark.parametrize(
    "jsonpath",
    [
        "$.rules[?(@.selection.countNumber>10)]",
        "Items[*].Name",
        "$.Items[0].Name",
        # Digit-leading field names: jq reads `.0` as the number 0 and `.v.0`
        # as a syntax error, where Rego and jsonpath-ng read the key "0", so
        # the same path would hold under one grader and be unresolvable or
        # contradicted under the other. Refused in the grammar instead.
        "$.v.0",
        "$.0",
        "$.v.1a",
        "$.v..0",
        "$.v[?(@.0=='x')]",
    ],
)
def test_both_compilers_refuse_the_same_paths(jsonpath: str) -> None:
    """One grammar, two backends: a path outside the subset must be a
    generation-time ValueError from BOTH, never a silent mis-translation by
    one of them."""
    with pytest.raises(ValueError):
        jsonpath_to_jq(jsonpath)
    with pytest.raises(ValueError):
        from jsonpath_rego import parse_jsonpath

        parse_jsonpath(jsonpath)


# ---------------------------------------------------------------------------
# the op-table clauses every column has to agree on, named one by one
# ---------------------------------------------------------------------------


class TestEqParity:
    def test_single_match_equal_holds(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "a"}]}
        assert _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc) == HELD

    def test_duplicate_matches_are_contradicted(self, tmp_path: Path) -> None:
        # Two identical SSM parameters -- SCHEMA.md §4.2 says "the *(single)*
        # resolved value", so >1 match (even if all equal) must be
        # contradicted, not pass-by-coincidence.
        doc = {"Items": [{"Name": "a"}, {"Name": "a"}]}
        assert _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc) == CONTRADICTED

    def test_mismatch_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "b"}]}
        assert _agree(tmp_path, "$.Items[*].Name", "eq", "a", doc) == CONTRADICTED


class TestContainsParity:
    def test_literal_dot_is_not_a_wildcard(self, tmp_path: Path) -> None:
        # A regex engine treats "." as "any character", so
        # "ec2.amazonaws.com" would match "ec2Xamazonaws.com" -- a
        # security-relevant false PASS on a role-trust check. contains is a
        # literal substring test.
        doc = {"Principal": {"Service": "ec2Xamazonaws.com"}}
        assert (
            _agree(tmp_path, "$.Principal.Service", "contains", "ec2.amazonaws.com", doc)
            == CONTRADICTED
        )

    def test_real_substring_holds(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "ec2.amazonaws.com"}}
        assert (
            _agree(tmp_path, "$.Principal.Service", "contains", "ec2.amazonaws.com", doc)
            == HELD
        )


class TestInParity:
    ALLOWED = ["ssm:GetParameter", "ssm:GetParameters"]

    def test_bare_string_action_holds(self, tmp_path: Path) -> None:
        doc = {"Statement": [{"Action": "ssm:GetParameter"}]}
        assert _agree(tmp_path, "$.Statement[*].Action", "in", self.ALLOWED, doc) == HELD

    def test_list_valued_action_holds(self, tmp_path: Path) -> None:
        # Action resolves to an array on one statement and a bare string on
        # the next: both flatten one level before membership.
        doc = {"Statement": [{"Action": ["ssm:GetParameter"]}]}
        assert _agree(tmp_path, "$.Statement[*].Action", "in", self.ALLOWED, doc) == HELD

    def test_disallowed_action_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Statement": [{"Action": ["ssm:PutParameter"]}]}
        assert (
            _agree(tmp_path, "$.Statement[*].Action", "in", self.ALLOWED, doc)
            == CONTRADICTED
        )


class TestSetEqParity:
    """`contains`/`in` pass as long as the correct value is PRESENT, so an
    extra unintended one is invisible to both. set_eq requires the resolved
    set to equal expected exactly -- the "and nothing else" op the
    "scoped, not broader" catch family needs."""

    def test_exact_match_holds(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "ec2.amazonaws.com"}}
        assert (
            _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)
            == HELD
        )

    def test_extra_unintended_principal_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": ["ec2.amazonaws.com", "lambda.amazonaws.com"]}}
        assert (
            _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)
            == CONTRADICTED
        )

    def test_missing_expected_value_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Principal": {"Service": "lambda.amazonaws.com"}}
        assert (
            _agree(tmp_path, "$.Principal.Service", "set_eq", ["ec2.amazonaws.com"], doc)
            == CONTRADICTED
        )

    def test_object_valued_nodes_do_not_crash_a_column(self, tmp_path: Path) -> None:
        """A resolved node can be an object, and `set()` over one raises
        TypeError in Python -- a crash where jq's `unique` returns a set."""
        doc = {"Statement": [{"Condition": {"StringEquals": {"k": "v"}}}]}
        assert (
            _agree(
                tmp_path,
                "$.Statement[*].Condition",
                "set_eq",
                [{"StringEquals": {"k": "v"}}],
                doc,
            )
            == HELD
        )


class TestFromjsonParity:
    """The `|fromjson` grammar extension: a tier-0 assert reaching inside a
    Terraform plan attribute (or a CFN Fn::Join-flattened string) that is
    itself a JSON-encoded string. Without it the ECS-swappiness
    nested-attribute catch is invisible on the TF arms -- the path resolves
    against the raw undecoded string and finds nothing."""

    PATH = "$.values.container_definitions|fromjson[*].linuxParameters.swappiness"

    def test_correctly_nested_swappiness_holds(self, tmp_path: Path) -> None:
        doc = {
            "values": {
                "container_definitions": json.dumps(
                    [{"name": "app", "linuxParameters": {"swappiness": 60}}]
                )
            }
        }
        assert _agree(tmp_path, self.PATH, "eq", 60, doc) == HELD

    def test_mis_nested_swappiness_is_not_found(self, tmp_path: Path) -> None:
        doc = {
            "values": {
                "container_definitions": json.dumps(
                    [{"name": "app", "swappiness": 60, "linuxParameters": {}}]
                )
            }
        }
        assert _agree(tmp_path, self.PATH, "not_exists", None, doc) == HELD

    def test_an_undecodable_attribute_is_unresolvable_not_absent(self, tmp_path: Path) -> None:
        """The signature failure mode this whole tier guards against: an
        attribute that is not a JSON string at all must not read as "the
        nesting is correct and swappiness is simply absent"."""
        doc = {"values": {"container_definitions": {"name": "app"}}}
        assert _agree(tmp_path, self.PATH, "not_exists", None, doc) == UNRESOLVABLE


class TestFromjsonDecoderDivergence:
    r"""`|fromjson` runs a DIFFERENT DECODER in each column -- jq's, Go's
    (`json.is_valid`/`json.unmarshal`) and Python's `json` -- and the three do
    not accept the same set of strings. Pinned per column, because the whole
    class is invisible to `make tier0-parity`: it depends on a byte no
    fixture produces, and 26 corpus paths use `|fromjson`.

    One direction is closed by an explicit rule rather than left divergent: jq
    REJECTS a string carrying an unpaired `\uD800`-`\uDBFF` escape, while Go
    accepts it and substitutes U+FFFD, so without the rule the assert reaches a
    verdict under Rego where jq is unresolvable -- a reward flip. `cdk synth`
    writes exactly that escape (Node's `JSON.stringify` emits a lone surrogate
    as `\ud800`), so an agent reaches it through the real toolchain.

    The rest are jq-lenient / Go-strict and stay divergent, in the direction
    that refuses to grade rather than mis-grading: `NaN`, `Infinity`, a
    leading-zero or bare-point number and a UTF-8 BOM prefix are values jq
    reads and RFC 8259 does not define. Go also caps nesting at 10000 levels,
    which is left unpinned because jq's own limit is build-dependent.
    """

    PATH = "$.x|fromjson"

    def test_an_unpaired_high_surrogate_escape_is_unresolvable_in_all_three(
        self, tmp_path: Path
    ) -> None:
        doc = {"x": r'{"a":"\ud800","swappiness":42}'}
        assert _agree(tmp_path, self.PATH, "exists", None, doc) == UNRESOLVABLE

    @pytest.mark.parametrize(
        "raw", [r'"\ud800"', r'"\ud800\ud800"', r'"\ud800a"', r'{"a":"x\uDBFFy"}']
    )
    def test_the_refusal_covers_the_whole_unpaired_high_surrogate_class(
        self, raw: str, tmp_path: Path
    ) -> None:
        assert _agree(tmp_path, self.PATH, "exists", None, {"x": raw}) == UNRESOLVABLE

    @pytest.mark.parametrize(
        "raw",
        [
            r'{"emoji":"\ud83d\ude00"}',  # a PAIR: an escaped astral character
            r'{"emoji":"\uD83D\uDE00"}',  # the same, upper-case hex
            r'{"low":"\udc00"}',  # a lone LOW surrogate: both decoders accept
            r'{"plain":"\u00e9"}',
        ],
    )
    def test_an_escape_the_two_decoders_share_still_grades(
        self, raw: str, tmp_path: Path
    ) -> None:
        """The counting rule must not over-refuse: an escaped astral character
        is a surrogate PAIR, and refusing it would make every emoji in a
        container definition unresolvable."""
        assert _agree(tmp_path, self.PATH, "exists", None, {"x": raw}) == HELD

    # (raw string, python reference outcome) -- bash is HELD and rego is
    # UNRESOLVABLE for every one of them.
    JQ_LENIENT = (
        ("NaN", HELD),
        ("{\"a\":Infinity}", HELD),
        ("00", UNRESOLVABLE),
        ("{\"a\":01}", UNRESOLVABLE),
        ("1.", UNRESOLVABLE),
        (".1", UNRESOLVABLE),
        ("+1", UNRESOLVABLE),
        ("﻿{}", UNRESOLVABLE),
    )

    @pytest.mark.parametrize("raw,python", JQ_LENIENT)
    def test_a_string_only_jq_decodes_is_unresolvable_under_rego(
        self, raw: str, python: str, tmp_path: Path
    ) -> None:
        doc = {"x": raw}
        assert _bash_outcome(tmp_path, self.PATH, "exists", None, doc) == HELD
        rego = _rego_outcomes(tmp_path, [("probe", self.PATH, "exists", None)], doc)
        assert rego["probe"] == UNRESOLVABLE
        assert _python_outcome(self.PATH, "exists", None, doc) == python


class TestAbsentOrEqParity:
    """absent_or_eq -- the "left at its implied default" catch shape:
    `not_exists` alone rejects a correct solution that writes the semantically
    identical value explicitly (`tier = "Standard"` vs omitted), and `eq` alone
    rejects the omitted form."""

    def test_absent_holds(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Name": "p"}]}
        assert (
            _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc) == HELD
        )

    def test_explicit_default_holds(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Tier": "Standard"}]}
        assert (
            _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc) == HELD
        )

    def test_wrong_enum_value_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Resources": [{"Tier": "Advanced"}]}
        assert (
            _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)
            == CONTRADICTED
        )

    def test_duplicate_matches_are_contradicted(self, tmp_path: Path) -> None:
        # Same ambiguity rule as bare `eq`: >1 resolved node fails even if
        # every value equals expected.
        doc = {"Resources": [{"Tier": "Standard"}, {"Tier": "Standard"}]}
        assert (
            _agree(tmp_path, "$.Resources[*].Tier", "absent_or_eq", "Standard", doc)
            == CONTRADICTED
        )


class TestNotExistsParity:
    def test_genuinely_absent_field_holds(self, tmp_path: Path) -> None:
        # LinuxParameters has no Swappiness key at all, so this holds (0
        # matches). jq's plain field access returns `null` for an absent key,
        # and a `[null]` collection of length 1 would fail every not_exists
        # assert unconditionally, known-good artifacts included -- which is why
        # null is dropped before the op runs.
        doc = {"ContainerDefinitions": [{"LinuxParameters": {"InitProcessEnabled": True}}]}
        assert (
            _agree(
                tmp_path,
                "$.ContainerDefinitions[*].LinuxParameters.Swappiness",
                "not_exists",
                None,
                doc,
            )
            == HELD
        )

    def test_present_field_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"ContainerDefinitions": [{"Swappiness": 60}]}
        assert (
            _agree(
                tmp_path, "$.ContainerDefinitions[*].Swappiness", "not_exists", None, doc
            )
            == CONTRADICTED
        )


class TestRegexParity:
    """`regex` passes when ANY resolved string matches, which is what
    SCHEMA.md §4.2 says and what the jq grader does. Requiring EVERY node to be
    a matching string would silently strengthen every multi-node regex assert
    in the corpus."""

    def test_one_of_several_nodes_matching_holds(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "other"}, {"Name": "arn:aws:iam::1:role/r"}]}
        assert _agree(tmp_path, "$.Items[*].Name", "regex", "^arn:aws:iam", doc) == HELD

    def test_no_node_matching_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Items": [{"Name": "other"}]}
        assert (
            _agree(tmp_path, "$.Items[*].Name", "regex", "^arn:aws:iam", doc) == CONTRADICTED
        )

    def test_zero_nodes_is_contradicted(self, tmp_path: Path) -> None:
        doc = {"Items": []}
        assert (
            _agree(tmp_path, "$.Items[*].Name", "regex", "^arn:aws:iam", doc) == CONTRADICTED
        )


class TestNotRegexParity:
    """not_regex -- the sfn-jsonata mode-mixing catch's "no raw un-evaluated
    JSONPath string anywhere in this JSONata-mode ASL". Literal negation of
    `regex`'s per-value test, except 0 resolved nodes vacuously HOLDS."""

    def test_pattern_absent_holds(self, tmp_path: Path) -> None:
        doc = {"Definition": '{"Output": "{% $states.input.orders %}"}'}
        assert _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc) == HELD

    def test_pattern_present_is_contradicted(self, tmp_path: Path) -> None:
        # A raw, un-evaluated JSONPath string used as a literal value instead
        # of a proper {% ... %} expression.
        doc = {"Definition": '{"Output": "$.orders"}'}
        assert _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc) == CONTRADICTED

    def test_zero_resolved_nodes_holds(self, tmp_path: Path) -> None:
        doc = {"Other": "irrelevant"}
        assert _agree(tmp_path, "$.Definition", "not_regex", r'"\$\.', doc) == HELD


class TestRegexFlavourDivergence:
    r"""The three regex flavours -- jq's Oniguruma, Rego's RE2, Python's `re`
    -- and what each does with syntax the others lack.

    Pinned per column, not through `_agree`: these are the cells where the
    engines CANNOT agree, and what matters is the DIRECTION of each
    disagreement. A refusal to grade (unresolvable) is safe; a verdict reached
    with a pattern that was never applied is the vacuous pass this whole tier
    exists to prevent.

    No corpus pattern uses any of this syntax -- every one of them is anchors,
    escaped literals, character classes and at most one alternation -- and the
    all-artifacts tier0-parity gate is what keeps the next one safe.
    """

    # (pattern, a subject Oniguruma MATCHES it against). RE2 has no lookaround
    # and no backreferences, and rejects an unbalanced class.
    RE2_REJECTS = (("(?=a)a", "a"), (r"(a)\1", "aa"), ("[", "a"))

    @pytest.mark.parametrize("op", ["regex", "not_regex"])
    @pytest.mark.parametrize(("pattern", "subject"), RE2_REJECTS)
    def test_a_pattern_re2_cannot_compile_is_unresolvable_under_rego(
        self, op: str, pattern: str, subject: str, tmp_path: Path
    ) -> None:
        """`regex.match` ERRORS on a pattern RE2 rejects, and a Rego builtin
        error is silent undefined -- so `not_regex`'s `not _has` would succeed
        and report "this string appears nowhere" for a pattern that was never
        applied to anything, on the one op whose entire purpose is proving an
        absence (the sfn-jsonata no-raw-JSONPath catch, the 0.0.0.0/0 CIDR
        catch). The compiler emits an explicit applicability rule, so both
        pattern ops land in `unresolvable` instead of in a verdict."""
        rego = _rego_outcomes(
            tmp_path, [("probe", "$.a", op, pattern)], {"a": subject}
        )
        assert rego["probe"] == UNRESOLVABLE

    @pytest.mark.parametrize(("pattern", "subject"), RE2_REJECTS[:2])
    def test_the_jq_grader_reaches_the_opposite_verdict_there(
        self, pattern: str, subject: str, tmp_path: Path
    ) -> None:
        """Oniguruma compiles both, so jq grades `not_regex` as contradicted on
        a subject the pattern matches. The rego column's unresolvable is
        therefore a refusal to grade, not a flipped verdict."""
        doc = {"a": subject}
        assert _bash_outcome(tmp_path, "$.a", "not_regex", pattern, doc) == CONTRADICTED
        assert _bash_outcome(tmp_path / "r", "$.a", "regex", pattern, doc) == HELD

    def test_jq_itself_reaches_a_verdict_on_a_pattern_it_cannot_compile(
        self, tmp_path: Path
    ) -> None:
        """The jq backend's own version of the same defect, which is corrected
        by its removal rather than ahead of it: an unbalanced class makes
        `test` fail, and the collect-and-count shape reads that as "no node
        matched" -- a VERDICT on a pattern no engine could apply. Both other
        columns refuse."""
        doc = {"a": "a"}
        assert _bash_outcome(tmp_path, "$.a", "not_regex", "[", doc) == CONTRADICTED
        assert _python_outcome("$.a", "not_regex", "[", doc) == UNRESOLVABLE

    # (pattern, a subject BOTH GRADERS match it against). Python's `re` reads a
    # POSIX class as a nested set, rejects `\p` and `\z` outright, and spells a
    # named group `(?P<` so it reads `(?<x>` as a malformed lookbehind.
    RE_MISREADS = (
        ("[[:alpha:]]", "abc"),
        (r"\p{L}+", "abc"),
        ("(?<x>a)", "abc"),
        (r"c\z", "abc"),
    )

    @pytest.mark.parametrize(("pattern", "subject"), RE_MISREADS)
    def test_the_two_graders_agree_where_the_python_reference_refuses(
        self, pattern: str, subject: str, tmp_path: Path
    ) -> None:
        """The reference REFUSES rather than answering: compiling
        `[[:alpha:]]` under `re` and reporting the result would answer
        "not_regex holds" where both graders contradict -- an authoring-time
        false PASS, the worst of the three directions."""
        doc = {"a": subject}
        assert _bash_outcome(tmp_path, "$.a", "not_regex", pattern, doc) == CONTRADICTED
        rego = _rego_outcomes(tmp_path, [("probe", "$.a", "not_regex", pattern)], doc)
        assert rego["probe"] == CONTRADICTED
        assert _python_outcome("$.a", "not_regex", pattern, doc) == UNRESOLVABLE

    def test_a_pattern_all_three_engines_accept_agrees(self, tmp_path: Path) -> None:
        doc = {"a": "a"}
        assert _agree(tmp_path, "$.a", "not_regex", "^zz$", doc) == HELD
        assert _agree(tmp_path / "r", "$.a", "regex", "^a$", doc) == HELD

    def test_a_go_style_named_group_is_refused_rather_than_graded(
        self, tmp_path: Path
    ) -> None:
        r"""`(?P<name>...)` is RE2's spelling and Oniguruma has no such form at
        all -- it spells a named group `(?<name>...)` and fails to compile the
        `(?P<` one -- so there is NO subject on which the two flavours agree,
        and the rego column refuses the pattern outright instead of screening
        per value. jq's own failure to compile collapses into "no value
        matched", which is a verdict: it contradicts `regex` on a subject the
        pattern would have matched and contradicts `not_regex` on one it would
        not, and that half is corrected by the removal of the jq backend rather
        than ahead of it. No corpus pattern uses the form.
        """
        for op, subject in (("regex", "a"), ("not_regex", "zzz")):
            doc = {"a": subject}
            assert _bash_outcome(tmp_path / op, "$.a", op, "(?P<n>a)", doc) == CONTRADICTED
            rego = _rego_outcomes(tmp_path / op, [("probe", "$.a", op, "(?P<n>a)")], doc)
            assert rego["probe"] == UNRESOLVABLE
            # Python `re` accepts the form too, so the reference would answer
            # "holds" for `regex` -- the false-PASS direction -- unless it
            # screens the construct out the way it screens `[[:` and `\p{`.
            assert _python_outcome("$.a", op, "(?P<n>a)", doc) == UNRESOLVABLE


class TestRegexMeaningDivergence:
    r"""The flavour divergence that no applicability rule over the PATTERN can
    see, because both engines compile the pattern and both reach a verdict --
    and the verdicts are opposite.

      `$`        end of text under RE2; end of text OR just before one trailing
                 newline under Oniguruma and Python `re`.
      `\w` `\d`  ASCII-only under RE2; Unicode-aware under Oniguruma.
      `\s` `\b`  likewise.
      `[[:alpha:]]` and every other POSIX bracket expression except
                 `[[:ascii:]]`: the same ASCII-vs-Unicode split, in the
                 spelling that carries no backslash.

    This is the reachable class: five corpus patterns are `$`-anchored
    (`^prod$`, `^GET /orders$`, `^1$`, `^0\.0\.0\.0/0$`,
    `^(ObjectWriter|BucketOwnerPreferred)$`), and the worst direction lands on
    a `not_regex` absence proof -- `^1$` against a `function_version` of
    `"1
"` is jq=contradicted (it catches the pin) and, ungoverned,
    rego=held: a vacuous pass on the one op whose purpose is proving an
    absence.

    It is also invisible to the all-artifacts tier0-parity gate, which
    grades the artifacts that exist. So the compiler screens the PATTERN for
    the construct at generation time and emits a rule that refuses per VALUE at
    evaluation time: unresolvable exactly when a resolved value is one the two
    flavours read differently. Every cell below is that refusal, pinned per
    column against the verdict jq reaches.
    """

    # (op, pattern, subject, the outcome the jq/Python columns reach).
    CELLS = (
        ("not_regex", "^1$", "1\n", CONTRADICTED),
        ("regex", "^1$", "1\n", HELD),
        ("not_regex", "^prod$", "prod\n", CONTRADICTED),
        ("regex", "^prod$", "prod\n", HELD),
        ("regex", "^GET /orders$", "GET /orders\n", HELD),
        ("regex", r"^\w+$", "caf\u00e9", HELD),
        ("regex", r"^\d+$", "\u0661\u0662", HELD),
        ("not_regex", r"^\w+$", "caf\u00e9", CONTRADICTED),
    )

    @pytest.mark.parametrize(
        ("op", "pattern", "subject", "jq_outcome"), CELLS,
        ids=[f"{c[0]}-{c[1]}-{c[2]}" for c in CELLS],
    )
    def test_the_rego_column_refuses_where_the_flavours_disagree(
        self, op: str, pattern: str, subject: str, jq_outcome: str, tmp_path: Path
    ) -> None:
        doc = {"a": subject}
        assert _bash_outcome(tmp_path, "$.a", op, pattern, doc) == jq_outcome
        assert _python_outcome("$.a", op, pattern, doc) == jq_outcome
        rego = _rego_outcomes(tmp_path, [("probe", "$.a", op, pattern)], doc)
        assert rego["probe"] == UNRESOLVABLE

    # The same split in the POSIX spelling, which carries no backslash for the
    # pattern screen to key on. The Python reference column is absent here: `re`
    # reads `[[:alpha:]]` as a nested set and refuses the spelling outright, so
    # it is pinned in TestRegexFlavourDivergence.RE_MISREADS instead.
    POSIX_CELLS = (
        ("regex", "^[[:alpha:]]+$", "caf\u00e9", HELD),
        ("not_regex", "^[[:alpha:]]+$", "caf\u00e9", CONTRADICTED),
        ("not_regex", "^[[:alnum:]]+$", "caf\u00e9", CONTRADICTED),
        ("not_regex", "^[[:word:]]+$", "caf\u00e9", CONTRADICTED),
        ("not_regex", "^[[:lower:]]+$", "\u00e9", CONTRADICTED),
        ("not_regex", "^[[:upper:]]+$", "\u00c9", CONTRADICTED),
        ("not_regex", "^[[:digit:]]+$", "\u0661\u0662", CONTRADICTED),
        ("not_regex", "^[[:space:]]+$", "\u00a0", CONTRADICTED),
        ("not_regex", "^[[:alnum:]_-]+$", "na\u00efve-1", CONTRADICTED),
    )

    @pytest.mark.parametrize(
        ("op", "pattern", "subject", "jq_outcome"), POSIX_CELLS,
        ids=[f"{c[0]}-{c[1]}-{c[2]}" for c in POSIX_CELLS],
    )
    def test_the_rego_column_refuses_a_posix_class_over_a_non_ascii_value(
        self, op: str, pattern: str, subject: str, jq_outcome: str, tmp_path: Path
    ) -> None:
        doc = {"a": subject}
        assert _bash_outcome(tmp_path, "$.a", op, pattern, doc) == jq_outcome
        rego = _rego_outcomes(tmp_path, [("probe", "$.a", op, pattern)], doc)
        assert rego["probe"] == UNRESOLVABLE

    @pytest.mark.parametrize("op", ["regex", "not_regex"])
    @pytest.mark.parametrize("pattern", ["^[[:alpha:]]+$", "^[[:alnum:]_-]+$"])
    def test_a_posix_class_still_grades_over_an_ascii_value(
        self, op: str, pattern: str, tmp_path: Path
    ) -> None:
        """The screen is per VALUE: an ASCII subject is graded by both graders
        rather than refused, so a POSIX-class assert keeps working. Two
        columns, not three -- Python `re` refuses the spelling itself."""
        doc = {"a": "prod-1"}
        bash = _bash_outcome(tmp_path, "$.a", op, pattern, doc)
        rego = _rego_outcomes(tmp_path, [("probe", "$.a", op, pattern)], doc)["probe"]
        assert bash == rego
        assert bash in (HELD, CONTRADICTED)

    @pytest.mark.parametrize(
        ("pattern", "subject"),
        [("^prod$", "prod"), (r"^\w+$", "prod"), ("^1$", "1"), ("^GET /orders$", "GET /orders")],
    )
    @pytest.mark.parametrize("op", ["regex", "not_regex"])
    def test_the_same_pattern_still_grades_on_a_subject_both_flavours_share(
        self, op: str, pattern: str, subject: str, tmp_path: Path
    ) -> None:
        """The screen is per VALUE, not per pattern: a `$`-anchored corpus
        pattern over an ordinary ASCII value with no trailing newline is graded
        by all three columns exactly as it is today. A per-pattern refusal
        would have made five corpus asserts ungradeable under `rego`."""
        assert _agree(tmp_path, "$.a", op, pattern, {"a": subject}) in (HELD, CONTRADICTED)

    def test_an_escaped_dollar_is_not_an_anchor(self, tmp_path: Path) -> None:
        r"""`specs/sfn-jsonata.yaml`'s pattern is `"\$\.` -- a literal dollar
        sign. Screening on the character rather than on an unescaped,
        outside-a-class occurrence would refuse it on any subject ending in a
        newline, for a construct it does not contain."""
        assert _agree(tmp_path, "$.a", "regex", r'"\$\.', {"a": '"$.foo"\n'}) == HELD


class TestMistypedExpected:
    """`in`/`set_eq` are defined over a list and the pattern ops over a string.
    generator/spec_model.py refuses either mistyping at spec load, which is
    where an author sees it; the emitter still has to produce a COMPILABLE
    policy for a caller that bypasses the spec model, because an uncompilable
    tier0.rego takes every other assert in the arm down with it."""

    @pytest.mark.parametrize(
        ("op", "expected"),
        [("in", "a"), ("set_eq", "a"), ("regex", 5), ("not_regex", 5)],
    )
    def test_a_mistyped_expected_is_unresolvable_not_uncompilable(
        self, op: str, expected: object, tmp_path: Path
    ) -> None:
        doc = {"a": "a"}
        rego = _rego_outcomes(tmp_path, [("probe", "$.a", op, expected)], doc)
        assert rego["probe"] == UNRESOLVABLE
        assert _python_outcome("$.a", op, expected, doc) == UNRESOLVABLE

    @pytest.mark.parametrize("op", ["in", "set_eq"])
    @pytest.mark.parametrize("jsonpath", ["$", "$..Action"])
    def test_a_path_with_no_raising_stage_still_compiles(
        self, op: str, jsonpath: str, tmp_path: Path
    ) -> None:
        """`$` alone and a lone `..Field` emit no error rule of their own, so
        the reason set has to be a PARTIAL set either way -- a complete
        `:= set()` and the op guard's `contains` rule are a compile conflict
        that refuses the whole file, every other assert included."""
        rego = _rego_outcomes(tmp_path, [("probe", jsonpath, op, "s3:*")], {"a": "a"})
        assert rego["probe"] == UNRESOLVABLE


class TestJsonTypeCrossingParity:
    """JSON keeps `true` and `1` distinct types and treats `1` and `1.0` as one
    number. Python `==` gets both backwards (`True == 1`, and `1 == 1.0` only
    by luck of hashing), so the reference needs its own equality: the SHAPES
    matrix above runs every op over both crossings, and these two name the
    crossings explicitly."""

    def test_a_bool_node_is_not_the_number_one(self, tmp_path: Path) -> None:
        """A plan-JSON `enabled`/throttle attribute compared against a numeric
        `expected`. Reading it as equal told a spec author an assert holds that
        every trial contradicts."""
        assert _agree(tmp_path, "$.a", "eq", True, {"a": 1}) == CONTRADICTED
        assert _agree(tmp_path / "f", "$.a", "eq", False, {"a": 0}) == CONTRADICTED

    def test_an_integral_float_is_the_same_number_as_its_int(self, tmp_path: Path) -> None:
        """Terraform plan JSON and CFN templates carry both encodings of the
        same number, and `set_eq` keying on the canonical JSON text made them
        two members of a one-member set."""
        assert _agree(tmp_path, "$.a", "set_eq", [1], {"a": 1.0}) == HELD
        assert _agree(tmp_path / "f", "$.a", "set_eq", [1.0], {"a": 1}) == HELD
