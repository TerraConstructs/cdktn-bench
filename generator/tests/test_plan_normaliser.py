"""The plan normaliser in the generated tests/tiers.py, executed.

Module resources live under `planned_values.root_module.child_modules[*]`;
every tier-0 JSONPath and every Rego policy addresses
`planned_values.root_module.resources`. The normaliser hoists them so both
graders ask their existing questions of a module-shaped plan
(docs/design/tf-modules-arm.md, "do the oracle tiers survive modules?").

The failure mode this file exists for is WRONG OUTPUT WITH NO ERROR: a hoist
that drops a resource, one that overwrites a root resource sharing an address,
a configuration reference resolved by guesswork, or an added key on a plan with
no module in it -- which would silently re-grade every existing fixture. Each
is a case below, on hand-written plan JSON, run against the real emitted module
rather than a copy of it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import TIERS_PY, build_verify_config  # noqa: E402
from spec_model import load_spec  # noqa: E402


@pytest.fixture(scope="module")
def tiers(tmp_path_factory):
    """tests/tiers.py as a task ships it, imported and called."""
    path = tmp_path_factory.mktemp("tiers") / "tiers.py"
    path.write_text(TIERS_PY)
    spec = importlib.util.spec_from_file_location("normaliser_tiers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(document) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def resource(address, type_, name, **values):
    return {"address": address, "mode": "managed", "type": type_, "name": name,
            "values": dict(values)}


def child(address, resources, children=None):
    module = {"address": address, "resources": resources}
    if children is not None:
        module["child_modules"] = children
    return module


def plan(root_resources, children=None, changes=None, configuration=None):
    root: dict = {"resources": list(root_resources)}
    if children is not None:
        root["child_modules"] = children
    document: dict = {"format_version": "1.2", "terraform_version": "1.15.8",
                      "planned_values": {"root_module": root}}
    if changes is not None:
        document["resource_changes"] = changes
    if configuration is not None:
        document["configuration"] = configuration
    return document


def planned(document):
    return document["planned_values"]["root_module"]["resources"]


def addresses(document):
    return [r["address"] for r in planned(document)]


# --- the invariant ----------------------------------------------------------


MODULE_FREE = [
    pytest.param(plan([]), id="empty"),
    pytest.param(plan([resource("aws_s3_bucket.b", "aws_s3_bucket", "b", bucket="x")]),
                 id="one-resource"),
    pytest.param(
        plan(
            [resource("aws_s3_bucket.b[0]", "aws_s3_bucket", "b", bucket="x")],
            changes=[{"address": "aws_s3_bucket.b[0]", "mode": "managed",
                      "change": {"actions": ["create"], "after": {"bucket": "x"},
                                 "after_unknown": {"arn": True}}}],
            configuration={"root_module": {"resources": [{
                "address": "aws_s3_bucket.b", "type": "aws_s3_bucket",
                "expressions": {"bucket": {"references": ["local.name", "count.index",
                                                          "each.key"]}},
            }]}},
        ),
        id="root-locals-and-iteration",
    ),
]


@pytest.mark.parametrize("document", MODULE_FREE)
def test_a_module_free_plan_normalises_to_itself(tiers, document) -> None:
    """The zero-drift invariant, and the whole reason every existing fixture
    can be re-graded through the normaliser without re-proving its oracle.

    `local.`, `count.` and `each.` in the ROOT module are deliberately NOT
    marked: they are what the existing tiers already own, and a mark on one
    would add a key to a plan that has no module in it.

    KEY ORDER is pinned as well as content. The `_hcl` pre-parser re-dumps the
    document in the order it reads it, and gates/hcl_merge_bytes.py compares
    those bytes against a baseline built over the raw plan, so a normaliser
    that reordered keys would move the merged tier-1 input without changing a
    single value.
    """
    out = tiers.normalise_plan(document)
    assert canonical(out) == canonical(document)
    assert json.dumps(out) == json.dumps(document)


def test_the_invariant_is_enforced_at_runtime_not_only_by_the_gate(tiers) -> None:
    """A normaliser that grew a key on a module-free plan must abort, not
    quietly re-grade the corpus: the gate runs on demand, this runs on every
    trial."""
    document = plan([resource("aws_s3_bucket.b", "aws_s3_bucket", "b")])
    original = tiers.annotate_module
    tiers.annotate_module = lambda *a, **k: None
    try:
        assert canonical(tiers.normalise_plan(document)) == canonical(document)
    finally:
        tiers.annotate_module = original
    # The guard fires on any drift, whatever introduced it.
    document["configuration"] = {"root_module": {"resources": [{
        "address": "aws_s3_bucket.b",
        "expressions": {"bucket": {"references": ["module.x.name", "module.x"]}},
    }]}}
    with pytest.raises(tiers.NormaliseError):
        tiers.normalise_plan(document)


# --- the values hoist -------------------------------------------------------


def test_one_module_is_hoisted_with_its_path(tiers) -> None:
    document = plan([], [child("module.bucket", [
        resource("module.bucket.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])])
    out = tiers.normalise_plan(document)
    assert addresses(out) == ["module.bucket.aws_s3_bucket.this"]
    assert planned(out)[0]["x_module_path"] == ["module.bucket"]
    assert planned(out)[0]["values"] == {"bucket": "b"}
    assert "child_modules" not in out["planned_values"]["root_module"]


def test_nested_modules_are_hoisted_at_every_depth(tiers) -> None:
    document = plan([], [child(
        "module.outer",
        [resource("module.outer.aws_s3_bucket.mid", "aws_s3_bucket", "mid")],
        [child("module.outer.module.inner", [
            resource("module.outer.module.inner.aws_s3_bucket.deep", "aws_s3_bucket",
                     "deep")
        ])],
    )])
    out = tiers.normalise_plan(document)
    assert addresses(out) == ["module.outer.aws_s3_bucket.mid",
                              "module.outer.module.inner.aws_s3_bucket.deep"]
    assert [r["x_module_path"] for r in planned(out)] == [
        ["module.outer"], ["module.outer", "module.inner"]
    ]


def test_two_calls_of_one_module_both_survive(tiers) -> None:
    """The silent-drop case. Both resources carry the same module-LOCAL
    address, so anything keyed on it keeps one and loses the other with no
    error -- a whole half of the solution ungraded."""
    document = plan([], [
        child("module.a", [resource("module.a.aws_s3_bucket.this", "aws_s3_bucket",
                                    "this", bucket="a")]),
        child("module.b", [resource("module.b.aws_s3_bucket.this", "aws_s3_bucket",
                                    "this", bucket="b")]),
    ])
    out = tiers.normalise_plan(document)
    assert addresses(out) == ["module.a.aws_s3_bucket.this",
                              "module.b.aws_s3_bucket.this"]
    assert [r["x_module_path"] for r in planned(out)] == [["module.a"], ["module.b"]]
    assert [r["values"]["bucket"] for r in planned(out)] == ["a", "b"]


@pytest.mark.parametrize("segment", ['module.many[0]', 'module.keyed["a"]'])
def test_a_module_instance_keeps_its_key_in_the_path(tiers, segment) -> None:
    document = plan([], [child(segment, [
        resource(segment + ".aws_s3_bucket.this", "aws_s3_bucket", "this")
    ])])
    out = tiers.normalise_plan(document)
    assert planned(out)[0]["x_module_path"] == [segment]


def test_a_root_resource_sharing_an_address_is_never_clobbered(tiers) -> None:
    """The overwrite case. A root resource and a module resource present the
    same address to anything that strips the module prefix -- the local address
    both the configuration join and Regula key on; the hoist appends and never
    assigns, so both are graded."""
    document = plan(
        [resource("aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="root")],
        [child("module.m", [resource("module.m.aws_s3_bucket.this", "aws_s3_bucket",
                                     "this", bucket="module")])],
    )
    out = tiers.normalise_plan(document)
    assert [r["values"]["bucket"] for r in planned(out)] == ["root", "module"]
    assert "x_module_path" not in planned(out)[0]
    assert planned(out)[1]["x_module_path"] == ["module.m"]


def test_a_root_resource_gains_no_key(tiers) -> None:
    """`x_` keys mark what was hoisted. A root resource that grew one would
    change how every existing fixture's asserts read it."""
    document = plan(
        [resource("aws_s3_bucket.root", "aws_s3_bucket", "root")],
        [child("module.m", [resource("module.m.aws_s3_bucket.this", "aws_s3_bucket",
                                     "this")])],
        changes=[{"address": "aws_s3_bucket.root",
                  "change": {"after_unknown": {"arn": True}}}],
    )
    out = tiers.normalise_plan(document)
    assert not [k for k in planned(out)[0] if k.startswith("x_")]


def test_a_dropped_resource_aborts_rather_than_grading_short(tiers) -> None:
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.a", "aws_s3_bucket", "a"),
        resource("module.m.aws_s3_bucket.b", "aws_s3_bucket", "b"),
    ])])
    original = tiers.hoist_resources

    def losing(module, unknowns, out):
        original(module, unknowns, out)
        out.pop()

    tiers.hoist_resources = losing
    try:
        with pytest.raises(tiers.NormaliseError):
            tiers.normalise_plan(document)
    finally:
        tiers.hoist_resources = original


# --- after_unknown ----------------------------------------------------------


def test_after_unknown_is_carried_onto_a_hoisted_resource(tiers) -> None:
    """`planned_values` cannot express unknown -- an unknown attribute is
    simply absent from `values`, indistinguishable from unset -- so without
    this a policy cannot tell "the agent did not set it" from "Terraform
    cannot know it yet"."""
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])], changes=[{
        "address": "module.m.aws_s3_bucket.this", "module_address": "module.m",
        "change": {"actions": ["create"], "after": {"bucket": "b"},
                   "after_unknown": {"arn": True, "id": True}},
    }])
    out = tiers.normalise_plan(document)
    assert planned(out)[0]["x_after_unknown"] == {"arn": True, "id": True}


def test_resource_changes_are_left_exactly_as_the_toolchain_wrote_them(tiers) -> None:
    """Already flat, `module_address` present: the blast-radius read needs it
    unchanged, so the normaliser only reads it."""
    changes = [{"address": "module.m.aws_s3_bucket.this", "module_address": "module.m",
                "change": {"actions": ["no-op"], "after": {"bucket": "b"},
                           "after_unknown": {}}}]
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])], changes=changes)
    out = tiers.normalise_plan(document)
    assert out["resource_changes"] == changes


def test_a_deposed_object_does_not_take_the_live_resources_unknowns(tiers) -> None:
    """`address` is not unique across a deposed object; the doc's key is
    `address` + `deposed`. Joined on address alone, the deposed entry's
    `after_unknown` lands on the live resource."""
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])], changes=[
        {"address": "module.m.aws_s3_bucket.this", "module_address": "module.m",
         "change": {"actions": ["create"], "after_unknown": {"arn": True}}},
        {"address": "module.m.aws_s3_bucket.this", "module_address": "module.m",
         "deposed": "abc12345",
         "change": {"actions": ["delete"], "after": None, "after_unknown": False}},
    ])
    out = tiers.normalise_plan(document)
    assert len(planned(out)) == 1
    assert planned(out)[0]["x_after_unknown"] == {"arn": True}


def test_a_no_op_resource_is_hoisted_like_any_other(tiers) -> None:
    """`resource_changes` is not a changed-only list: after an apply every
    resource reappears with `actions: ["no-op"]`, and an idempotence or
    brownfield fixture grades exactly that plan."""
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])], changes=[{
        "address": "module.m.aws_s3_bucket.this", "module_address": "module.m",
        "change": {"actions": ["no-op"], "after": {"bucket": "b"},
                   "after_unknown": {}},
    }])
    out = tiers.normalise_plan(document)
    assert addresses(out) == ["module.m.aws_s3_bucket.this"]
    assert planned(out)[0]["x_after_unknown"] == {}


# --- the configuration side -------------------------------------------------


def configured(call, body_resources=None, root_resources=None, **call_fields):
    """A configuration with one `module.m` call, for the marker cases."""
    module = {"resources": list(body_resources or [])}
    node = {"source": "./m", "module": module}
    node.update(call)
    node.update(call_fields)
    return {"root_module": {"resources": list(root_resources or []),
                            "module_calls": {"m": node}}}


def body_resource(**expressions):
    return {"address": "aws_s3_bucket.this", "mode": "managed",
            "type": "aws_s3_bucket", "name": "this", "expressions": expressions}


def marks(document, tiers_module):
    out = tiers_module.normalise_plan(document)
    call = out["configuration"]["root_module"]["module_calls"]["m"]
    body = call["module"]["resources"]
    return (
        [m["reason"] for m in call.get("x_unresolved", [])],
        [m["reason"] for m in (body[0].get("x_unresolved", []) if body else [])],
    )


def test_module_calls_are_left_in_place(tiers) -> None:
    """The call node is where a policy reads what the root passed in; hoisting
    the configuration side is not part of this phase."""
    document = plan([], configuration=configured(
        {"expressions": {"name": {"constant_value": "b"}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    out = tiers.normalise_plan(document)
    call = out["configuration"]["root_module"]["module_calls"]["m"]
    assert call["expressions"] == {"name": {"constant_value": "b"}}
    assert "x_unresolved" not in call


def test_an_input_the_caller_passes_as_a_constant_is_resolvable(tiers) -> None:
    document = plan([], configuration=configured(
        {"expressions": {"name": {"constant_value": "b"}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    assert marks(document, tiers) == ([], [])


def test_an_input_the_caller_passes_by_reference_is_resolvable(tiers) -> None:
    """A root-frame reference IS the resolution; the normaliser does not
    rewrite it into the slot, which is the mistake that destroys the
    unknown/absent distinction."""
    document = plan([], configuration=configured(
        {"expressions": {"name": {"references": ["aws_s3_bucket.other.id",
                                                 "aws_s3_bucket.other"]}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    assert marks(document, tiers) == ([], [])


def test_an_input_the_caller_never_passes_falls_back_to_a_default(tiers) -> None:
    """The arm doc's "the module hides the trapped attribute behind a default"
    case: the value comes from the module's own `variables.<x>.default`, which
    this document does not carry, so the catch's tier changes rather than the
    value being guessed."""
    assert marks(plan([], configuration=configured(
        {"expressions": {}},
        [body_resource(bucket={"references": ["var.name"]})],
    )), tiers) == ([], ["module_input_default"])


def test_a_var_chain_through_an_unresolvable_outer_value_is_refused(tiers) -> None:
    document = plan([], configuration=configured(
        {"expressions": {"name": {"references": ["module.other.out", "module.other"]}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    assert marks(document, tiers) == ([], ["module_input_chain"])


@pytest.mark.parametrize(
    "reference,reason",
    [
        ("module.inner.out", "module_output"),
        ("each.key", "iteration"),
        ("count.index", "iteration"),
        ("local.computed", "local_symbol"),
        ("path.module", "context_symbol"),
        ("terraform.workspace", "context_symbol"),
        ("self.arn", "context_symbol"),
    ],
)
def test_each_honestly_unresolvable_reference_is_marked(tiers, reference, reason) -> None:
    document = plan([], configuration=configured(
        {"expressions": {}}, [body_resource(bucket={"references": [reference]})],
    ))
    _call, body = marks(document, tiers)
    assert body == [reason]


def test_a_bare_module_reference_does_not_double_the_mark(tiers) -> None:
    """Terraform duplicates a module output read as `module.a.out` AND the
    bare `module.a`; the bare half carries no information."""
    document = plan([], configuration=configured(
        {"expressions": {}},
        [body_resource(bucket={"references": ["module.inner.out", "module.inner"]})],
    ))
    assert marks(document, tiers) == ([], ["module_output"])


def test_a_root_resource_reading_a_module_output_is_marked(tiers) -> None:
    """The one class that crosses the boundary in the root frame too. It can
    only appear where `module_calls` exists, so the module-free invariant is
    untouched."""
    document = plan([], configuration=configured(
        {"expressions": {}}, [],
        root_resources=[{"address": "aws_s3_bucket.sink", "expressions": {
            "bucket": {"references": ["module.m.name", "module.m"]}}}],
    ))
    out = tiers.normalise_plan(document)
    root = out["configuration"]["root_module"]["resources"][0]
    assert [m["reason"] for m in root["x_unresolved"]] == ["module_output"]
    assert root["x_unresolved"][0]["attribute"] == "bucket"
    assert root["x_unresolved"][0]["reference"] == "module.m.name"


@pytest.mark.parametrize(
    "call_fields,reason",
    [
        ({"count_expression": {"constant_value": 2}}, "module_count"),
        ({"for_each_expression": {"constant_value": {"a": "x"}}}, "module_for_each"),
    ],
)
def test_a_repeated_module_call_is_marked_at_the_call(tiers, call_fields, reason) -> None:
    document = plan([], configuration=configured({"expressions": {}}, [], **call_fields))
    call, _body = marks(document, tiers)
    assert call == [reason]


def test_a_toset_for_each_is_caught_from_the_values_side(tiers) -> None:
    """`for_each = toset([...])` emits NO `for_each_expression` at all, so the
    instance keys on the values side are the only signal that one
    configuration node governs several planned resources."""
    document = plan(
        [],
        [child('module.m["a"]', [resource('module.m["a"].aws_s3_bucket.this',
                                          "aws_s3_bucket", "this")]),
         child('module.m["b"]', [resource('module.m["b"].aws_s3_bucket.this',
                                          "aws_s3_bucket", "this")])],
        configuration=configured({"expressions": {"name": {"constant_value": "b"}}},
                                 [body_resource(bucket={"references": ["var.name"]})]),
    )
    call, body = marks(document, tiers)
    assert call == ["module_repeated_unrepresented"]
    # The input is a constant and still refused: one node, two instances.
    assert body == ["module_input_repeated"]


def test_a_block_the_configuration_does_not_represent_is_marked(tiers) -> None:
    """`dynamic` block expressions are absent from the configuration
    representation entirely -- Terraform's own documented gap -- so a rule that
    reads `expressions` sees nothing and would report a configured block as
    unset. The plan's own block is the only trace."""
    document = plan(
        [],
        [child("module.m", [resource(
            "module.m.aws_s3_bucket.this", "aws_s3_bucket", "this",
            bucket="b", lifecycle_rule=[{"id": "expire", "enabled": True}],
        )])],
        configuration=configured({"expressions": {"name": {"constant_value": "b"}}},
                                 [body_resource(bucket={"references": ["var.name"]})]),
    )
    out = tiers.normalise_plan(document)
    body = out["configuration"]["root_module"]["module_calls"]["m"]["module"]["resources"]
    entries = [m for m in body[0]["x_unresolved"]
               if m["reason"] == "expression_not_represented"]
    assert [m["attribute"] for m in entries] == ["lifecycle_rule"]


def test_the_normaliser_never_writes_a_value_into_a_slot(tiers) -> None:
    """Regula's shape mistake, refused: resolved references mounted into the
    value slots destroy the held/contradicted/unresolvable distinction the
    whole three-valued contract rests on."""
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this", bucket="b")
    ])], configuration=configured(
        {"expressions": {"name": {"constant_value": "b"}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    out = tiers.normalise_plan(document)
    assert planned(out)[0]["values"] == {"bucket": "b"}
    body = out["configuration"]["root_module"]["module_calls"]["m"]["module"]["resources"]
    assert body[0]["expressions"] == {"bucket": {"references": ["var.name"]}}


# --- purity and the arms ----------------------------------------------------


def test_the_normaliser_does_not_mutate_its_argument(tiers) -> None:
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this")
    ])])
    before = canonical(document)
    tiers.normalise_plan(document)
    assert canonical(document) == before


def test_a_non_object_plan_is_an_error_not_an_empty_document(tiers) -> None:
    for document in ([], "plan", None, 7):
        with pytest.raises(tiers.NormaliseError):
            tiers.normalise_plan(document)


@pytest.mark.parametrize("arm,expected", [("hcl_raw", True), ("terraconstructs", True),
                                          ("awscdk", False)])
def test_only_the_terraform_arms_normalise(arm, expected) -> None:
    """A nested stack on awscdk is DENIED by its own rule, not normalised, so
    that arm's config declares nothing about a mechanism it does not run."""
    spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
    config = build_verify_config(spec, arm)
    assert config.get("normalise_plan", False) is expected
    # A normaliser fault is "the oracle did not run", which must never score as
    # a pass -- the same rule TOOL_MISSING gets. Listed on every arm, reachable
    # only where the normaliser runs: the list is the equal-strictness contract
    # between the arms, not an inventory of the mechanisms one arm has.
    assert "ENGINE_ERROR" in config["tier1"]["bad_statuses"]


def test_the_normalised_document_is_written_beside_the_plan(tiers, tmp_path) -> None:
    """Once per run, and the RAW artifact is left exactly as the toolchain
    wrote it: the falsifiability collector and the blast-radius read it."""
    artifact = tmp_path / "plan.json"
    document = plan([], [child("module.m", [
        resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this")
    ])])
    raw = json.dumps(document)
    artifact.write_text(raw)
    first = tiers.normalised_plan_path(artifact)
    assert first == tmp_path / "plan.normalised.json"
    assert artifact.read_text() == raw
    assert addresses(json.loads(first.read_text())) == ["module.m.aws_s3_bucket.this"]
    stamp = first.stat().st_mtime_ns
    first.write_text("{}")
    assert tiers.normalised_plan_path(artifact) == first
    assert first.read_text() == "{}", "the document is built once per verifier run"
    assert stamp  # the helper returns a real file, not a path it never wrote


def test_a_normaliser_fault_is_an_engine_error_on_both_tiers(tiers, tmp_path) -> None:
    """Never a silent pass: tier 0 reports the unresolvable outcome it already
    has for "the proof did not run", tier 1 reports ENGINE_ERROR."""
    logs = tmp_path / "logs"
    logs.mkdir()
    tiers.LOGS = logs
    artifact = tmp_path / "plan.json"
    artifact.write_text("{ not json")
    status, graded = tiers.normalise_artifact({"normalise_plan": True}, artifact)
    assert status == "ENGINE_ERROR"
    assert graded == artifact
    assert "not JSON" in (logs / "plan-normaliser.log").read_text()
    assert tiers.tier_0({"engine": "jq"}, artifact, status) == 0
    assert "tier0-engine-error" in [p.name for p in logs.iterdir()]
    # A hand-authored policy, because the un-authored one is a louder defect
    # and reports SKIPPED_STUB ahead of any question about the input document.
    tiers.DIR = tmp_path
    (tmp_path / "policy.rego").write_text("package cdktn_bench.x\n")
    assert tiers.tier_1(
        {"header": "OPA/Rego", "policy": "policy.rego", "has_asserts": True,
         "hcl": None, "query": "q", "not_verifiable_query": "nv", "hardened": False,
         "bad_statuses": ["FAIL", "ENGINE_ERROR"]},
        artifact, status,
    ) == "ENGINE_ERROR"


# --- the cases where a silent wrong answer was reachable ---------------------


def test_an_instance_key_containing_a_quote_does_not_collapse_the_address(
    tiers,
) -> None:
    """`for_each` keys are agent-controlled strings. An address parser that
    reads the `\\"` as the end of the key leaves every later dot inside a quote
    that never closes, so the whole address becomes one segment and the module
    path, the hoist depth and the configuration join are all wrong with no
    error anywhere."""
    segment = 'module.fe["a\\"b"]'
    assert tiers.split_address(segment + ".aws_s3_bucket.this") == [
        "module", 'fe["a\\"b"]', "aws_s3_bucket", "this",
    ]
    document = plan([], [child(segment, [
        resource(segment + ".aws_s3_bucket.this", "aws_s3_bucket", "this")
    ])])
    out = tiers.normalise_plan(document)
    assert planned(out)[0]["x_module_path"] == [segment]


def test_two_resources_at_one_address_abort_rather_than_grading_two_nodes(
    tiers,
) -> None:
    """The hoist appends, so nothing is overwritten -- but an `eq` assert
    demands exactly one node, and two resources at one address would turn a
    held assert into a contradicted one with no error. Terraform never writes
    such a plan, so refusing costs a real solution nothing."""
    document = plan(
        [resource("module.m.aws_s3_bucket.this", "aws_s3_bucket", "this",
                  bucket="root")],
        [child("module.m", [resource("module.m.aws_s3_bucket.this", "aws_s3_bucket",
                                     "this", bucket="module")])],
    )
    with pytest.raises(tiers.NormaliseError, match="more than one resource"):
        tiers.normalise_plan(document)


@pytest.mark.parametrize(
    "reference,reason",
    [
        ("local.computed", "local_symbol"),
        ("each.key", "iteration"),
        ("count.index", "iteration"),
        ("path.module", "context_symbol"),
        ("terraform.workspace", "context_symbol"),
    ],
)
def test_a_module_input_chained_to_an_unresolvable_root_symbol_is_refused(
    tiers, reference, reason
) -> None:
    """The root frame's own resources are not marked for these -- the existing
    tiers own them there -- but a module input that CHAINS out to one has
    arrived somewhere this document cannot follow, and the module resource's
    slot is the only place a policy would ever see that."""
    document = plan([], configuration=configured(
        {"expressions": {"name": {"references": [reference]}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    call_marks, body_marks = marks(document, tiers)
    assert call_marks == []
    assert body_marks == ["module_input_chain"]
    out = tiers.normalise_plan(document)
    detail = out["configuration"]["root_module"]["module_calls"]["m"][
        "module"]["resources"][0]["x_unresolved"][0]["detail"]
    assert reason in detail


def test_a_module_input_chained_to_a_root_variable_resolves(tiers) -> None:
    """A root `var.x` is not a dead end: the plan's own top-level `variables`
    block carries the run's value for it, so marking it would refuse a chain
    this document can answer."""
    document = plan([], configuration=configured(
        {"expressions": {"name": {"references": ["var.stack_name"]}}},
        [body_resource(bucket={"references": ["var.name"]})],
    ))
    assert marks(document, tiers) == ([], [])


def test_a_constant_value_shaped_like_a_reference_is_not_read_as_one(tiers) -> None:
    """`constant_value` holds the agent's literal data. A map with a
    `references` key in it is a tag set, not a Terraform reference, and reading
    it as one invents an unresolvable the configuration never declared."""
    document = plan([], configuration=configured(
        {"expressions": {"name": {"constant_value": "b"}}},
        [body_resource(
            bucket={"references": ["var.name"]},
            tags={"constant_value": {"references": ["local.sneaky"]}},
        )],
    ))
    assert marks(document, tiers) == ([], [])
