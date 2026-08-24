"""Regression + totality suite for oracles/rego/lib/hcl_traversal.rego.

WHY THIS FILE EXISTS AND WHY IT IS SHAPED THE WAY IT IS.

The spike that produced that library
(docs/design/conftest-hcl-traversal-spike.md) failed its own safety
contract three times under adversarial verification, and the third failure
is the reason for this suite's central design rule:

    A TOTALITY ASSERTION MUST RUN ONE PROCESS PER SHAPE AND CHECK THE
    EXIT CODE.

The prototype's own totality probe evaluated every shape inside ONE `opa
eval` query. A `eval_conflict_error` on shape k aborts that query, so the
probe emitted nothing at all -- and "nothing" read as "no missing
verdicts". The probe was inside the blast radius of the bug it was meant to
detect. Both earlier probes (15 shapes, then 25) missed the defect for
exactly this reason; the one-process-per-shape probe found it immediately,
and would have found the other two as well.

So: every check below spawns its own `opa eval`, asserts `returncode == 0`,
and only then looks at the output. A crash is a test failure that names the
shape, never a silently empty result.

WHAT IS ASSERTED
  1. `resolve()` is TOTAL and THREE-VALUED -- one process per shape, over
     the tokenizer's adversarial corpus (dotted keys, quotes, backslashes,
     brackets, spaces, non-ASCII, splats, numeric indices, cycles, a 12-hop
     chain, the empty string, a bare `local`).
  2. The DOTTED-KEY COLLISION FAMILY specifically -- the executed
     `eval_conflict_error` shape -- resolves to the right referents rather
     than crashing, in all four of its variants.
  3. A RANDOMISED HUNT over generated `locals` tables whose keys are drawn
     from a dot-heavy alphabet, one process per table, seeded so a failure
     is reproducible.
  4. The FULL SCENARIO POLICY end to end on synthetic plan+`_hcl`
     documents: the dotted-key shape on a CORRECT solution denies NOTHING
     (the false-FAIL half of the regression -- it cannot live under
     solution/broken/, which has no positive slot), and the same shape on a
     laundered wrong-type ARN denies.
  5. That the hand-written `_hcl` documents used here really are what
     `hcl2json` emits (skipped when hcl2json is not installed), so these
     fixtures cannot drift away from the parser the harness actually runs.
  6. (round 14) THE TWO `locals` SPELLINGS resolve identically -- hcl2json's
     list-of-blocks and terraform's own JSON-syntax bare object -- because
     reading only the first silently dropped every local in a `.tf.json`
     and scored a CORRECT solution 0.0 with a message the artifact
     contradicted.
  7. (round 14) THE NOTIFICATION ANCHOR IS GATING. When the scenario policy
     cannot identify which bucket/topic the artifact's own notification
     wires, it must DENY -- not widen to a resource-TYPE test. The widening
     it replaces was an executed reward-1.0 on a genuinely broken artifact.

`opa` and `hcl2json` are developer-machine conveniences, not declared
dependencies (oracles/tests/toolcheck.py's own note), so a missing tool
SKIPS rather than fails -- the same convention test_emit.py already uses.
"""

from __future__ import annotations

import json
import random
import subprocess
import tempfile
from pathlib import Path

import pytest

from oracles.tests.toolcheck import find_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "oracles" / "rego" / "lib" / "hcl_traversal.rego"
SCENARIO_POLICY = (
    REPO_ROOT / "oracles" / "rego" / "s3-notification-authoritative-singleton" / "policy.rego"
)
KINDS = {"resolved", "ambiguous", "unresolvable"}

OPA = find_tool("opa")
HCL2JSON = find_tool("hcl2json")
requires_opa = pytest.mark.skipif(OPA is None, reason="opa not installed locally")
requires_hcl2json = pytest.mark.skipif(
    HCL2JSON is None, reason="hcl2json not installed locally"
)


# ---------------------------------------------------------------------------
# the one-process-per-shape runner
# ---------------------------------------------------------------------------


def _eval(query: str, document: dict, *policies: Path) -> tuple[int, str, str]:
    """ONE `opa eval` process. Returns (returncode, stdout, stderr).

    Deliberately returns the exit code rather than raising or parsing
    eagerly: a runtime error inside OPA writes NOTHING to stdout and exits
    non-zero, and the whole point of this harness is that the caller sees
    that as a distinct, named outcome instead of as an empty result set.
    """
    args = [OPA, "eval", "-f", "json", "-I"]
    for p in policies:
        args += ["-d", str(p)]
    args.append(query)
    proc = subprocess.run(
        args, input=json.dumps(document), capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def _resolve_one(sym: str, hcl_docs: dict) -> dict:
    """Resolve ONE symbol in ONE process, asserting the process survived."""
    query = f'data.cdktn_bench.hcl.resolve({json.dumps(sym)})'
    rc, out, err = _eval(query, {"_hcl": hcl_docs}, LIB)
    assert rc == 0, f"opa ABORTED on symbol {sym!r} (exit {rc}): {err.strip()}"
    parsed = json.loads(out)
    result = parsed.get("result")
    assert result, f"no verdict at all for {sym!r} -- resolve() is not total"
    return result[0]["expressions"][0]["value"]


def _topic_policy_doc(rname: str, source_arn_expr: str | None) -> dict:
    """The `resource` + `#jsonencode` half of an `_hcl` document, for a
    `aws_sns_topic_policy "<rname>"` whose `policy = jsonencode({...})`.

    ROUND 16: these plan fixtures used to carry `_hcl` documents holding
    `locals` and NOTHING ELSE, and the topic-policy rule was satisfied by a
    bare MENTION of the bucket anywhere in the flat reference list the plan
    reports for a `jsonencode(...)` argument. That mention test was an
    executed REWARD-1.0 launder (one interpolated `Sid`), so the rule now
    reads the document POSITIONALLY, out of the `#jsonencode` bodies the
    harness re-parses with hcl2json. A fixture that carries no readable
    document is now DENIED naming the shape -- correctly, and these builders
    have to carry one, exactly as the real merge step produces.

    `source_arn_expr=None` builds the UNSCOPED document (no Condition at
    all), which is what the launder fixtures under solution/broken/ hold.
    """
    statement = {
        "Sid": "AllowS3Publish",
        "Effect": "Allow",
        "Principal": {"Service": "s3.amazonaws.com"},
        "Action": "SNS:Publish",
    }
    if source_arn_expr is not None:
        statement["Condition"] = {"ArnLike": {"aws:SourceArn": source_arn_expr}}
    return {
        "resource": {
            "aws_sns_topic_policy": {rname: [{"policy": "${jsonencode({...})}"}]}
        },
        "#jsonencode": [
            {
                "path": ["resource", "aws_sns_topic_policy", rname, 0, "policy"],
                "doc": {"Version": "2012-10-17", "Statement": [statement]},
            }
        ],
    }


def _tf(*blocks: str) -> dict:
    """A single-file `_hcl` document: {"main.tf": {"locals": [ ... ]}}."""
    return {"main.tf": {"locals": list(blocks)}}


# ---------------------------------------------------------------------------
# 1. totality + three-valuedness over the adversarial corpus
# ---------------------------------------------------------------------------

CORPUS_LOCALS = {
    "simple": "${aws_s3_bucket.media.arn}",
    "nested": {"media_bucket": "${aws_s3_bucket.media.arn}"},
    "chain": "${local.nested.media_bucket}",
    "cond": "${var.condition ? aws_s3_bucket.a.arn : aws_s3_bucket.b.arn}",
    "fmt": '${format("%s/*", aws_s3_bucket.media.arn)}',
    "merged": "${merge(local.nested, local.nested)}",
    "compr": "${{ for k, v in var.buckets : k => v.arn }}",
    "literal": "arn:aws:s3:::someone-elses-bucket",
    "interp": "${aws_s3_bucket.media.arn}/*",
    "escaped": "a literal $${not_an_expr} here",
    "splat": "${aws_s3_bucket.media[*].arn}",
    "idx": "${aws_s3_bucket.media[0].arn}",
    "num": 7,
    "bool": True,
    "list": ["${aws_s3_bucket.media.arn}"],
    "empty_obj": {},
    "weird": {
        "a.b": "${aws_s3_bucket.dotted.arn}",
        "a": {"b": "${aws_sns_topic.audit.arn}"},
        "with space": "${aws_s3_bucket.spacey.arn}",
        'with"quote': "${aws_s3_bucket.quoted.arn}",
        "with\\backslash": "${aws_s3_bucket.slashed.arn}",
        "with]bracket": "${aws_s3_bucket.bracketed.arn}",
        "héllo": "${aws_s3_bucket.uni.arn}",
        "": "${aws_s3_bucket.empty.arn}",
    },
    "cyc1": "${local.cyc2}",
    "cyc2": "${local.cyc3}",
    "cyc3": "${local.cyc1}",
    "self": "${local.self}",
    **{f"h{i}": f"${{local.h{i + 1}}}" for i in range(1, 12)},
    "h12": "${aws_s3_bucket.deep.arn}",
}

CORPUS_SHAPES = [
    "local.simple",
    "local.nested",
    "local.nested.media_bucket",
    "local.chain",
    "local.cond",
    "local.fmt",
    "local.merged",
    "local.compr",
    "local.literal",
    "local.interp",
    "local.escaped",
    "local.splat",
    "local.idx",
    "local.num",
    "local.bool",
    "local.list",
    "local.empty_obj",
    'local.weird["a.b"]',
    "local.weird.a.b",
    'local.weird["with space"]',
    'local.weird["with\\"quote"]',
    'local.weird["with]bracket"]',
    'local.weird["héllo"]',
    'local.weird[""]',
    "local.cyc1",
    "local.self",
    "local.h1",
    "local.h12",
    "local.does_not_exist",
    "local.nested.does_not_exist",
    "local",
    "local.",
    "",
    "var.x",
    "var.x[0]",
    "module.x.out",
    "aws_s3_bucket.media.arn",
    "data.aws_partition.current.partition",
    "!!!",
    "a b c",
    "local.weird.a.b.c.d",
    "${not_even_a_traversal}",
]


@requires_opa
@pytest.mark.parametrize("sym", CORPUS_SHAPES)
def test_resolve_is_total_and_three_valued(sym: str) -> None:
    """ONE OPA PROCESS PER SHAPE, exit code checked.

    pytest's own parametrization gives the one-process-per-shape property
    for free AND names the offending shape in the failure, which is exactly
    what the in-query probe could not do.
    """
    verdict = _resolve_one(sym, _tf(CORPUS_LOCALS))
    assert verdict["kind"] in KINDS, f"{sym!r} produced a fourth bucket: {verdict}"
    if verdict["kind"] == "resolved":
        assert isinstance(verdict["referent_path"], list) and verdict["referent_path"]
    else:
        # Ambiguous and unresolvable must both NAME what could not be
        # resolved -- a deny with no explanation is the failure mode this
        # whole design exists to prevent.
        assert verdict.get("reason"), f"{sym!r}: {verdict['kind']} with no reason"


@requires_opa
@pytest.mark.parametrize(
    "sym,expected",
    [
        ("local.simple", ["aws_s3_bucket", "media", "arn"]),
        ("local.nested.media_bucket", ["aws_s3_bucket", "media", "arn"]),
        ("local.chain", ["aws_s3_bucket", "media", "arn"]),
        ("local.h1", ["aws_s3_bucket", "deep", "arn"]),  # 12 hops, no ceiling
        ("local.h12", ["aws_s3_bucket", "deep", "arn"]),
        ('local.weird["with space"]', ["aws_s3_bucket", "spacey", "arn"]),
        ('local.weird["héllo"]', ["aws_s3_bucket", "uni", "arn"]),
        ('local.weird[""]', ["aws_s3_bucket", "empty", "arn"]),
        ('local.weird["with]bracket"]', ["aws_s3_bucket", "bracketed", "arn"]),
        ("aws_s3_bucket.media.arn", ["aws_s3_bucket", "media", "arn"]),
    ],
)
def test_resolved_referents(sym: str, expected: list[str]) -> None:
    verdict = _resolve_one(sym, _tf(CORPUS_LOCALS))
    assert verdict["kind"] == "resolved", verdict
    assert verdict["referent_path"] == expected


@requires_opa
@pytest.mark.parametrize(
    "sym",
    [
        "local.cond",  # a conditional -- does not tile, refused
        "local.fmt",  # opaque function call
        "local.merged",
        "local.compr",
        "local.literal",  # laundered literal: names no resource at all
        "local.interp",  # "${x}/*" is not the reference, it derives from it
        "local.splat",
        "local.idx",  # KNOWN false-fail direction, recorded not hidden
        "local.nested",  # a container, not a value
        "local.cyc1",  # cycle: no terminal, no hang
        "local.self",
        "local.does_not_exist",
        "var.x",  # a resolver has no business knowing a variable's value
        "module.x.out",  # module boundaries are out of scope
        'local.weird["with\\"quote"]',  # escapes are refused, not interpreted
    ],
)
def test_refused_shapes_are_unresolvable(sym: str) -> None:
    verdict = _resolve_one(sym, _tf(CORPUS_LOCALS))
    assert verdict["kind"] == "unresolvable", verdict


@requires_opa
def test_no_tf_supplied_is_unresolvable_not_a_pass() -> None:
    """A missing `.tf` must never fail OPEN.

    A Rego builtin that cannot find a file is UNDEFINED, not an error, so a
    policy that merely looks and moves on grades every symbol as fine. Here
    the absence is an explicit verdict with an explicit reason.
    """
    rc, out, _ = _eval("data.cdktn_bench.hcl.resolve(\"local.x\")", {}, LIB)
    assert rc == 0
    verdict = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert verdict["kind"] == "unresolvable"
    assert "no .tf source" in verdict["reason"]

    rc, out, _ = _eval("data.cdktn_bench.hcl.no_source_supplied", {"_hcl": {}}, LIB)
    assert rc == 0
    assert json.loads(out)["result"][0]["expressions"][0]["value"] is True


# ---------------------------------------------------------------------------
# 2. the dotted-key collision family (the executed eval_conflict_error)
# ---------------------------------------------------------------------------


@requires_opa
def test_dotted_key_collision_family() -> None:
    """The shape that ABORTED the prototype's evaluation entirely.

    `["t","a.b"]` and `["t","a","b"]` dot-join to the same string. The
    library keys its locals table by the path ARRAY (a SET of [path, value]
    pairs), so the two are two distinct entries and no key can conflict on
    any input at all -- conflict-freedom is a property of the KEY
    CONSTRUCTION, not of anyone having enumerated the right shapes.
    """
    # (a) differing values on the two colliding paths -- the actual trigger.
    docs = _tf({"t": {"a.b": "${aws_s3_bucket.dotted.arn}", "a": {"b": "${aws_sns_topic.audit.arn}"}}})
    assert _resolve_one('local.t["a.b"]', docs)["referent_path"] == ["aws_s3_bucket", "dotted", "arn"]
    assert _resolve_one("local.t.a.b", docs)["referent_path"] == ["aws_sns_topic", "audit", "arn"]

    # (b) identical values on both paths -- the control; the prototype
    #     survived this one, which is why the family needs both.
    same = _tf({"t": {"a.b": "${aws_s3_bucket.media.arn}", "a": {"b": "${aws_s3_bucket.media.arn}"}}})
    assert _resolve_one('local.t["a.b"]', same)["kind"] == "resolved"
    assert _resolve_one("local.t.a.b", same)["kind"] == "resolved"

    # (c) the 3-way collision: "a.b.c" / "a.b".c / a.b.c, three different
    #     buckets, all three distinguished.
    three = _tf(
        {
            "w1": {"a.b.c": "${aws_s3_bucket.d1.arn}"},
            "w2": {"a.b": {"c": "${aws_s3_bucket.d2.arn}"}},
            "w3": {"a": {"b": {"c": "${aws_s3_bucket.d3.arn}"}}},
        }
    )
    assert _resolve_one('local.w1["a.b.c"]', three)["referent_path"][1] == "d1"
    assert _resolve_one('local.w2["a.b"].c', three)["referent_path"][1] == "d2"
    assert _resolve_one("local.w3.a.b.c", three)["referent_path"][1] == "d3"

    # (d) a dotted key at the TOP level of `locals`, and a chain hop THROUGH
    #     one.
    top = _tf({"a.b": "${aws_s3_bucket.top.arn}", "a": {"b": "${aws_sns_topic.t.arn}"}, "hop": '${local["a.b"]}'})
    assert _resolve_one('local["a.b"]', top)["referent_path"][1] == "top"
    assert _resolve_one("local.hop", top)["referent_path"][1] == "top"


@requires_opa
def test_same_path_defined_twice_is_ambiguous_not_a_conflict() -> None:
    """Two `locals` blocks binding the SAME path to DIFFERENT referents.

    An object rule would raise eval_conflict_error here. The set-of-pairs
    keying turns it into N>1 candidates, i.e. AMBIGUOUS -- which DENIES,
    and names both candidates, instead of aborting evaluation.
    """
    docs = _tf({"x": "${aws_s3_bucket.one.arn}"}, {"x": "${aws_s3_bucket.two.arn}"})
    verdict = _resolve_one("local.x", docs)
    assert verdict["kind"] == "ambiguous", verdict
    assert sorted(verdict["candidates"]) == ["aws_s3_bucket.one.arn", "aws_s3_bucket.two.arn"]


# ---------------------------------------------------------------------------
# 3. randomised hunt, one process per table
# ---------------------------------------------------------------------------

_ALPHABET = ["a", "b", "a.b", "a.b.c", "b.c", "", '"', "\\", "]", "[", " ", "héllo", "."]


def _random_table(rng: random.Random) -> dict:
    """A `locals` table whose keys are drawn from a dot-heavy alphabet.

    Dots are over-represented on purpose: the collision the prototype died
    on needs two paths that dot-join to the same string, which random
    identifier-shaped keys would essentially never produce.
    """

    def node(depth: int) -> object:
        if depth == 0 or rng.random() < 0.4:
            return rng.choice(
                [
                    f"${{aws_s3_bucket.{rng.choice(['a', 'b', 'c'])}.arn}}",
                    f"${{local.{rng.choice(_ALPHABET[:2])}}}",
                    "a literal",
                    rng.randint(0, 9),
                ]
            )
        return {rng.choice(_ALPHABET): node(depth - 1) for _ in range(rng.randint(1, 4))}

    return {rng.choice(_ALPHABET): node(3) for _ in range(rng.randint(1, 6))}


@requires_opa
@pytest.mark.parametrize("seed", range(40))
def test_randomised_dotted_key_tables_never_abort(seed: int) -> None:
    """Seeded, one OPA PROCESS PER TABLE, exit code checked.

    40 tables here rather than the spike's 400: the property being hunted
    (a key collision aborting evaluation) is now structurally impossible
    rather than statistically unlikely, so this is a tripwire against a
    future refactor reintroducing an object rule, not a search. The seed is
    the parameter, so any failure is reproducible by name.
    """
    rng = random.Random(seed)
    docs = _tf(_random_table(rng))
    rc, out, err = _eval("data.cdktn_bench.hcl.node", docs, LIB)
    assert rc == 0, f"seed {seed}: opa ABORTED ({rc}): {err.strip()}\n{json.dumps(docs)[:2000]}"
    assert json.loads(out).get("result") is not None

    # ...and the classifier stays total over the same table.
    for sym in ("local.a", 'local["a.b"]', "local.a.b", "local", 'local["."]'):
        verdict = _resolve_one(sym, docs)
        assert verdict["kind"] in KINDS, f"seed {seed}, {sym!r}: {verdict}"


# ---------------------------------------------------------------------------
# 4. the full scenario policy, end to end, on synthetic documents
# ---------------------------------------------------------------------------

_ARNS_LOCALS = {
    "arns": {"media_bucket": "${aws_s3_bucket.media.arn}", "audit_topic": "${aws_sns_topic.audit.arn}"},
    # The dotted key that used to abort evaluation, carried alongside the
    # equivalent nested path with a DIFFERENT value.
    "t": {"a.b": "${aws_s3_bucket.media.arn}", "a": {"b": "${aws_sns_topic.audit.arn}"}},
}


def _plan(source_arn_refs: list[str], hcl_locals: dict) -> dict:
    """A minimal `terraform show -json`-shaped document for this scenario.

    Small on purpose: this is a regression harness for ONE property (the
    dotted key is a non-event), not a substitute for
    `make falsifiability`, which runs the real toolchain over the real
    fixtures.

    ROUND 15: every planned/configured resource carries `name`, because the
    policy's config<->plan join for `aws_lambda_permission` is on
    `[type, name]` and no longer on `.address` (a `count` meta-argument makes
    those two strings differ, which used to disable the scoping rule
    silently). Real `terraform show -json` output always has `name`; these
    fixtures did not, and that was fixture drift, not a policy limitation.
    """
    return {
        "planned_values": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.media", "type": "aws_s3_bucket", "name": "media", "values": {}},
                    {"address": "aws_sns_topic.audit", "type": "aws_sns_topic", "name": "audit", "values": {}},
                    {
                        "address": "aws_lambda_permission.allow_s3_invoke",
                        "type": "aws_lambda_permission",
                        "name": "allow_s3_invoke",
                        "values": {"principal": "s3.amazonaws.com"},
                    },
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "values": {"topic": [{"events": ["s3:ObjectRemoved:*"]}]},
                    },
                ]
            }
        },
        "configuration": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.media", "type": "aws_s3_bucket", "name": "media", "mode": "managed", "expressions": {}},
                    {"address": "aws_sns_topic.audit", "type": "aws_sns_topic", "name": "audit", "mode": "managed", "expressions": {}},
                    {
                        "address": "aws_lambda_permission.allow_s3_invoke",
                        "type": "aws_lambda_permission",
                        "name": "allow_s3_invoke",
                        "mode": "managed",
                        "expressions": {"source_arn": {"references": source_arn_refs}},
                    },
                    {
                        "address": "aws_sns_topic_policy.audit",
                        "type": "aws_sns_topic_policy",
                        "name": "audit",
                        "mode": "managed",
                        "expressions": {
                            "arn": {"references": ["local.arns.audit_topic", "local.arns"]},
                            "policy": {
                                "references": [
                                    "local.arns.audit_topic",
                                    "local.arns",
                                    "local.arns.media_bucket",
                                    "local.arns",
                                ]
                            },
                        },
                    },
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "mode": "managed",
                        "expressions": {
                            "bucket": {"references": ["aws_s3_bucket.media.id", "aws_s3_bucket.media"]},
                            "topic": [
                                {"topic_arn": {"references": ["local.arns.audit_topic", "local.arns"]}}
                            ],
                        },
                    },
                ]
            }
        },
        "_hcl": {"main.tf": _tf(hcl_locals)["main.tf"] | _topic_policy_doc("audit", "${local.arns.media_bucket}")},
    }


@requires_opa
def test_correct_solution_with_a_dotted_key_is_not_a_crash_and_not_a_deny() -> None:
    """THE FALSE-FAIL HALF of the eval_conflict_error regression.

    This artifact is FULLY CORRECT and additionally carries the dotted key.
    Under the prototype it produced an aborted evaluation, empty stdout, a
    `jq -e` exit of 4, `tier1_status=FAIL` and reward 0.0 -- with no deny
    message naming anything. It must now evaluate cleanly and deny nothing.

    It cannot be a solution/broken/ fixture: the falsifiability gate has
    exactly one positive slot (the reference solution itself), so a
    "correct, and must stay correct" variant has nowhere else to live.
    """
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
        doc,
        SCENARIO_POLICY,
        LIB,
    )
    assert rc == 0, f"opa ABORTED on a CORRECT solution (exit {rc}): {err.strip()}"
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert denies == [], denies


@requires_opa
def test_laundered_wrong_type_arn_with_a_dotted_key_denies() -> None:
    """The attack half: the same dotted key on a genuinely broken artifact.

    The point is not merely that reward is 0.0 -- the crashing prototype
    also produced 0.0 here. It is that the defect is DENIED, with a message
    naming what the symbol actually resolves to, instead of going UNGRADED.
    """
    launder = dict(_ARNS_LOCALS)
    launder["arns"] = dict(launder["arns"], media_bucket="${aws_lambda_function.ingest.arn}")
    doc = _plan(["local.arns.media_bucket", "local.arns"], launder)
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
        doc,
        SCENARIO_POLICY,
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert denies, "a laundered wrong-type ARN must DENY"
    assert any("aws_lambda_function.ingest.arn" in d for d in denies), denies


# ---------------------------------------------------------------------------
# 2b. THE TWO `locals` SPELLINGS -- the executed .tf.json false-FAIL
# ---------------------------------------------------------------------------
#
# hcl2json, over a native-HCL `.tf`, emits `"locals": [ {...}, {...} ]` (one
# object per block). Terraform's OWN JSON SYNTAX (`main.tf.json`, which the
# harness loads raw because there is nothing for hcl2json to do to it)
# writes `"locals": { "<name>": <value> }` -- a bare OBJECT -- and also
# accepts the list spelling.
#
# Reading only the list spelling silently dropped EVERY local in an
# object-spelled `main.tf.json`: a fully correct solution scored 0.0, denied
# with "no `locals` block in any supplied .tf file defines
# local.arns.media_bucket" about a supplied file that plainly defined it.
# That is a deny message the artifact contradicts (Amendment 29 RULING 3),
# and it made acceptance silently depend on which valid spelling was used.
# Both spellings must now resolve IDENTICALLY.


@requires_opa
@pytest.mark.parametrize(
    "doc",
    [
        pytest.param({"main.tf": {"locals": [_ARNS_LOCALS]}}, id="hcl2json-list-of-blocks"),
        pytest.param({"main.tf.json": {"locals": _ARNS_LOCALS}}, id="tf-json-bare-object"),
        pytest.param({"main.tf.json": {"locals": [_ARNS_LOCALS]}}, id="tf-json-list"),
    ],
)
def test_both_locals_spellings_resolve_identically(doc: dict) -> None:
    v = _resolve_one("local.arns.media_bucket", doc)
    assert v["kind"] == "resolved", v
    assert v["referent"] == "aws_s3_bucket.media.arn", v


@requires_opa
def test_a_correct_tf_json_solution_denies_nothing() -> None:
    """End to end, through the SCENARIO policy: the object-spelled
    `main.tf.json` that used to score 0.0 with a false message."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    doc["_hcl"] = {
        "main.tf.json": {"locals": _ARNS_LOCALS}
        | _topic_policy_doc("audit", "${local.arns.media_bucket}")
    }
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
        doc,
        SCENARIO_POLICY,
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert denies == [], denies


# ---------------------------------------------------------------------------
# 2c. THE ANCHOR IS GATING -- no type-only fallback (round 14)
# ---------------------------------------------------------------------------


def _two_bucket_plan(notification_bucket_refs: list[str], source_arn_refs: list[str]) -> dict:
    """Two buckets; the notification's own `bucket` argument is whatever the
    caller passes; `source_arn` points at the DECOY. If the notification's
    bucket cannot be resolved to one instance, round 13 accepted this on
    resource TYPE alone and scored it 1.0."""
    doc = _plan(source_arn_refs, _ARNS_LOCALS)
    doc["planned_values"]["root_module"]["resources"].append(
        {"address": "aws_s3_bucket.decoy", "type": "aws_s3_bucket", "name": "decoy", "values": {}}
    )
    for r in doc["configuration"]["root_module"]["resources"]:
        if r["type"] == "aws_s3_bucket_notification":
            r["expressions"]["bucket"] = {"references": notification_bucket_refs}
    doc["configuration"]["root_module"]["resources"].append(
        {"address": "aws_s3_bucket.decoy", "type": "aws_s3_bucket", "name": "decoy", "mode": "managed", "expressions": {}}
    )
    return doc


@requires_opa
@pytest.mark.parametrize(
    "notification_bucket_refs",
    [
        pytest.param([], id="literal-bucket-name-zero-references"),
        pytest.param(["local.opaque"], id="opaque-local"),
        pytest.param(["var.bucket_name"], id="input-variable"),
    ],
)
def test_an_unresolvable_notification_bucket_denies_rather_than_widening(
    notification_bucket_refs: list[str],
) -> None:
    doc = _two_bucket_plan(notification_bucket_refs, ["aws_s3_bucket.decoy.arn"])
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
        doc,
        SCENARIO_POLICY,
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert denies, (
        "an unresolvable notification `bucket` must DENY -- round 13 widened to a "
        "resource-TYPE test here and scored a decoy-scoped permission 1.0"
    )
    assert any("does not identify exactly one" in d for d in denies), denies


def _literal_bucket_plan(source_arn_refs: list[str]) -> dict:
    """The notification's `bucket` is a literal NAME (zero references), which
    is what that argument actually takes -- so the anchor can only come from
    the PLAN-VALUE route."""
    doc = _two_bucket_plan([], source_arn_refs)
    for r in doc["planned_values"]["root_module"]["resources"]:
        if r["type"] == "aws_s3_bucket":
            r["name"] = r["address"].split(".")[1]
            r["values"]["bucket"] = "cdktn-bench-media-ingest-" + r["name"]
        if r["type"] == "aws_s3_bucket_notification":
            r["values"]["bucket"] = "cdktn-bench-media-ingest-media"
    return doc


@requires_opa
def test_a_literal_notification_bucket_name_anchors_via_the_plan_value() -> None:
    """THE FALSE-FAIL CONTROL for round 14's fail-closed anchor.

    Making an unresolvable anchor DENY would be a false FAIL on the ordinary,
    valid spelling `bucket = "<name>"` if there were no second route. There
    is: the notification's planned `bucket` string must be the planned
    `bucket` name of exactly one bucket this configuration creates. Correct
    solution -> no deny; decoy-scoped permission -> denied BY NAME.
    """
    good = _literal_bucket_plan(["local.arns.media_bucket", "local.arns"])
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny", good, SCENARIO_POLICY, LIB
    )
    assert rc == 0, err
    assert json.loads(out)["result"][0]["expressions"][0]["value"] == []

    bad = _literal_bucket_plan(["aws_s3_bucket.decoy.arn"])
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny", bad, SCENARIO_POLICY, LIB
    )
    assert rc == 0, err
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert any(
        "aws_s3_bucket.decoy.arn" in d and "is not among the" in d for d in denies
    ), denies


@requires_opa
def test_a_resolvable_notification_bucket_still_discriminates_instances() -> None:
    """The control: with the anchor resolving, the decoy still denies and the
    right bucket still passes -- so the deny above is the escape hatch
    closing, not the rule breaking."""
    bad = _two_bucket_plan(
        ["aws_s3_bucket.media.id", "aws_s3_bucket.media"], ["aws_s3_bucket.decoy.arn"]
    )
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny", bad, SCENARIO_POLICY, LIB
    )
    assert rc == 0, err
    denies = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert any("aws_s3_bucket.decoy.arn" in d for d in denies), denies

    good = _two_bucket_plan(
        ["aws_s3_bucket.media.id", "aws_s3_bucket.media"],
        ["local.arns.media_bucket", "local.arns"],
    )
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny", good, SCENARIO_POLICY, LIB
    )
    assert rc == 0, err
    assert json.loads(out)["result"][0]["expressions"][0]["value"] == []


@requires_opa
def test_zero_and_multi_reference_slots_both_deny() -> None:
    """The arity gate, on the slot the prototype shipped without one.

    0 references (an omitted argument or a pasted literal ARN) and N>1
    references (a conditional written in the open) are BOTH refused. The
    memo's §5.7 finding is that the second of these was silently accepted
    by round 12 AND by the prototype; the gate now lives in the library and
    is `== 1`, in one place, for every slot.
    """
    for refs in ([], ["aws_s3_bucket.media.arn", "aws_s3_bucket.decoy.arn", "var.flip"]):
        doc = _plan(refs, _ARNS_LOCALS)
        rc, out, err = _eval(
            "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
            doc,
            SCENARIO_POLICY,
            LIB,
        )
        assert rc == 0, err
        denies = json.loads(out)["result"][0]["expressions"][0]["value"]
        assert denies, f"slot with refs={refs!r} was silently accepted"


# ---------------------------------------------------------------------------
# 5. the fixtures really are hcl2json's output
# ---------------------------------------------------------------------------


@pytest.mark.skipif(HCL2JSON is None, reason="hcl2json not installed locally")
def test_hand_written_hcl_fixtures_match_the_real_parser() -> None:
    """Guard against fixture drift.

    Every `_hcl` document above is hand-written in what this suite BELIEVES
    hcl2json emits. If that belief is wrong, the whole suite tests a parser
    that does not exist. This pins the belief to the real, pinned binary --
    including the two properties the resolver actually depends on: an
    unreduced expression arrives wrapped as exactly "${...}", and a literal
    arrives unwrapped.
    """
    hcl = (
        'locals {\n'
        '  simple = aws_s3_bucket.media.arn\n'
        '  nested = { media_bucket = aws_s3_bucket.media.arn }\n'
        '  literal = "arn:aws:s3:::x"\n'
        '  interp = "${aws_s3_bucket.media.arn}/*"\n'
        '  t = { "a.b" = aws_s3_bucket.dotted.arn, a = { b = aws_sns_topic.audit.arn } }\n'
        '}\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "main.tf"
        f.write_text(hcl)
        out = subprocess.run(
            [HCL2JSON, str(f)], capture_output=True, text=True, check=True
        ).stdout
    doc = json.loads(out)
    assert doc["locals"] == [
        {
            "simple": "${aws_s3_bucket.media.arn}",
            "nested": {"media_bucket": "${aws_s3_bucket.media.arn}"},
            "literal": "arn:aws:s3:::x",
            "interp": "${aws_s3_bucket.media.arn}/*",
            "t": {"a.b": "${aws_s3_bucket.dotted.arn}", "a": {"b": "${aws_sns_topic.audit.arn}"}},
        }
    ]


@requires_opa
@requires_hcl2json
def test_the_shipped_merge_program_produces_the_hcl_shape_this_suite_assumes() -> None:
    """ROUND 16. Pins `_topic_policy_doc` to the REAL merge step.

    The positional topic-policy rule reads `#jsonencode`, which does not come
    from hcl2json -- it is written by the merge program
    `generator/gen.py::build_hcl_merge_block()` emits into the hcl_raw arm's
    generated `tests/static_tiers.sh`. If this suite's hand-written belief
    about that key drifts from what the shipped program writes, every
    end-to-end assertion below tests a document the harness never produces.

    So this extracts the merge program FROM THE GENERATED SCRIPT ITSELF (the
    bytes a real trial runs) and executes it over a real `main.tf`,
    asserting both halves of the contract: `resource.<type>.<name>` is a
    LIST of blocks, and the `jsonencode(...)` body comes back re-parsed at
    the exact path `_topic_policy_doc` claims, with its leaves still raw
    `"${...}"` source.
    """
    generated = (
        REPO_ROOT
        / "tasks"
        / "anchor"
        / "s3-notification-authoritative-singleton-hcl-raw"
        / "tests"
        / "static_tiers.sh"
    )
    if not generated.exists():  # pragma: no cover - generated tree not built
        pytest.skip(f"{generated} not generated yet")
    text = generated.read_text()
    start = text.index("<<'CDKTN_HCL_MERGE_PY'\n") + len("<<'CDKTN_HCL_MERGE_PY'\n")
    merge_py = text[start : text.index("\nCDKTN_HCL_MERGE_PY", start)]

    tf = (
        'resource "aws_sns_topic_policy" "audit" {\n'
        "  arn = aws_sns_topic.audit.arn\n"
        "  policy = jsonencode({\n"
        '    Version = "2012-10-17"\n'
        "    Statement = [{\n"
        '      Sid       = "AllowS3Publish"\n'
        '      Effect    = "Allow"\n'
        '      Principal = { Service = "s3.amazonaws.com" }\n'
        '      Action    = "SNS:Publish"\n'
        "      Condition = {\n"
        '        ArnLike = { "aws:SourceArn" = local.arns.media_bucket }\n'
        "      }\n"
        "    }]\n"
        "  })\n"
        "}\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "main.tf").write_text(tf)
        (d / "merge.py").write_text(merge_py)
        (d / "plan.json").write_text("{}")
        proc = subprocess.run(
            ["python3", "merge.py", "plan.json", "merged.json"],
            cwd=d,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"the shipped merge program failed: {proc.stderr}"
        merged = json.loads((d / "merged.json").read_text())

    main = merged["_hcl"]["main.tf"]
    assert isinstance(main["resource"]["aws_sns_topic_policy"]["audit"], list), (
        "hcl2json must emit resource.<type>.<name> as a LIST of blocks -- "
        "hcl.resource_blocks' array clause depends on it"
    )
    assert main["#jsonencode"] == [
        {
            "path": ["resource", "aws_sns_topic_policy", "audit", 0, "policy"],
            "doc": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowS3Publish",
                        "Effect": "Allow",
                        "Principal": {"Service": "s3.amazonaws.com"},
                        "Action": "SNS:Publish",
                        "Condition": {
                            "ArnLike": {"aws:SourceArn": "${local.arns.media_bucket}"}
                        },
                    }
                ],
            },
        }
    ], main["#jsonencode"]
    # ...and that is exactly the shape this suite hand-writes.
    expected = _topic_policy_doc("audit", "${local.arns.media_bucket}")
    assert main["#jsonencode"] == expected["#jsonencode"]


# ---------------------------------------------------------------------------
# 6. (ROUND 15) SAME-TYPE / WRONG-INSTANCE THROUGH A `for_each` KEY
# ---------------------------------------------------------------------------
#
# The round-14 suite tested instance discrimination between two SEPARATE
# resource blocks and stopped there. It used `for_each` and `count` nowhere
# at all (grep: zero hits), and that gap was the whole of the round-15
# blocker: `instance_of` sliced the first TWO segments of a referent path, so
# every key of one `for_each` block collapsed to a single "instance" and a
# Lambda permission scoped to the DECOY bucket scored REWARD 1.0 in the real
# image. The collapse was SILENT rather than loud precisely because the
# tokenizer PARSES the `["key"]` form -- only the numeric `[0]` spelling ever
# refused, which is how three operator-facing texts came to claim the whole
# family was refused.


@requires_opa
@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        # plain instance -- type + label, unchanged from round 14
        ("aws_s3_bucket.media.arn", ["aws_s3_bucket", "media"]),
        # THE REGRESSION: two keys of ONE block are two DIFFERENT instances
        ('aws_s3_bucket.b["media"].arn', ["aws_s3_bucket", "b", "media"]),
        ('aws_s3_bucket.b["decoy"].arn', ["aws_s3_bucket", "b", "decoy"]),
        # a key containing a dot -- the shape that crashed the prototype --
        # still round-trips through the instance identity
        ('aws_s3_bucket.b["a.b"].arn', ["aws_s3_bucket", "b", "a.b"]),
        # a bracketed segment that is LAST is an ATTRIBUTE, not a key: HCL
        # lets `.arn` be spelled `["arn"]`, and reading that as an instance
        # key would false-FAIL an ordinary solution.
        ('aws_s3_bucket.media["arn"]', ["aws_s3_bucket", "media"]),
        # deeper attribute paths do not move the instance boundary
        ("aws_instance.web.tags.Name", ["aws_instance", "web"]),
    ],
)
def test_instance_of_carries_the_for_each_key(ref: str, expected: list[str]) -> None:
    rc, out, err = _eval(f"data.cdktn_bench.hcl.instance_of({json.dumps(ref)})", {}, LIB)
    assert rc == 0, f"opa ABORTED on {ref!r} (exit {rc}): {err.strip()}"
    result = json.loads(out).get("result")
    assert result, f"instance_of({ref!r}) is UNDEFINED -- it must never be"
    assert result[0]["expressions"][0]["value"] == expected


@requires_opa
def test_a_numeric_index_on_the_referent_is_still_refused_out_loud() -> None:
    """The half of the family that is genuinely still open, pinned as such.

    `aws_s3_bucket.b[0].arn` does not tokenize, so it is UNRESOLVABLE ->
    DENY. That is a known FALSE-FAIL on a `count`-expanded referent and it
    is recorded as a residual in three places. What this test guards is that
    it stays LOUD: a future "let's parse numeric indices too" change that
    forgets to carry the index into `instance_of` would silently reopen the
    round-15 hole, and this assertion is what would go red.
    """
    v = _resolve_one("aws_s3_bucket.b[0].arn", {})
    assert v["kind"] == "unresolvable", v
    assert "aws_s3_bucket.b[0].arn" in v["symbol"]


# ---------------------------------------------------------------------------
# ROUND 16: the tokenizer's REFUSAL PATH, pinned on the SHIPPED entry point
# ---------------------------------------------------------------------------
#
# *** EXECUTED DEFECT THESE THREE TESTS EXIST FOR. `parse_traversal` was
# written as a bare comprehension:
#
#     parse_traversal(t) := [seg | some m in _parse_ms(t); seg := _segment(m)]
#
# A Rego comprehension whose body is undefined evaluates to the EMPTY
# COLLECTION, not to undefined. So for an UNTOKENIZABLE string the function
# returned `[]` -- DEFINED -- and every `not parse_traversal(x)` guard in
# the library was DEAD CODE. Consequences, all executed on opa 1.19.0:
#
#   * `_unparseable` was ALWAYS the empty set, so `slot()`'s "the slot holds
#     reference(s) this resolver cannot tokenize" clause never fired and
#     unparseable references were SILENTLY DROPPED by `_deepest` (`[]` is a
#     prefix of every parse) -- precisely what that clause's own comment
#     says must never happen.
#   * `resolve()`'s "is not a traversal this resolver can tokenize" clause
#     was unreachable, so an opaque expression got a factually FALSE reason.
#   * End to end on a real `count = 1` plan whose `source_arn` was
#     `aws_s3_bucket.media[0].arn`, the deny read "it resolves to
#     `aws_s3_bucket.media`, which names the instance but no attribute of it
#     -- an ARN slot needs `.arn`", about an artifact that plainly writes
#     `.arn`, and never quoted the reference it could not read.
#
# WHY THE OLD PINNING TEST DID NOT CATCH IT, which is the lesson here: it
# called `hcl.resolve` on a BARE SYMBOL with `_hcl={}` and asserted nothing
# about the reason. `resolve` on `aws_s3_bucket.b[0].arn` lands in the
# "defined, but reaches no concrete reference" catch-all and reports
# `unresolvable` for the WRONG reason, so the assertion passed while the
# path it was supposed to pin was dead. These tests exercise the SHIPPED
# entry point (`slot`), the guard predicate itself, and the REASON TEXT.


# ---------------------------------------------------------------------------
# ROUND 16: the topic-policy document is graded POSITIONALLY
# ---------------------------------------------------------------------------


@requires_opa
def test_a_bucket_named_only_in_the_sid_does_not_scope_anything() -> None:
    """THE ROUND-16 LAUNDER, pinned at the policy level.

    Same artifact twice. In the first, the wired bucket is named in the
    statement's `aws:SourceArn` condition -- that is scoping, and it must
    deny nothing. In the second, the SAME reference is moved into the `Sid`
    and the Condition is dropped entirely -- that scopes nothing, and it
    must DENY. Until round 16 both passed, because the rule asked only
    whether the document MENTIONED the bucket anywhere. One cosmetic line
    took a checked-in 0.0 fixture to REWARD 1.0 in the real image.
    """
    scoped = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    assert _deny(scoped) == [], _deny(scoped)

    laundered = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    doc = laundered["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]
    st = doc["Statement"][0]
    del st["Condition"]
    st["Sid"] = "AllowS3Publish${local.arns.media_bucket}"
    bad = _deny(laundered)
    assert bad, (
        "a bucket reference in a `Sid` is not a scoping condition -- this is "
        "the executed reward-1.0 launder and it must DENY"
    )
    assert any("aws:SourceArn" in d for d in bad), bad


@requires_opa
def test_a_scoped_statement_does_not_launder_an_unscoped_one() -> None:
    """"Every granting statement", not "some statement anywhere"."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    statements = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"]
    statements.append(
        {
            "Sid": "AllowEveryBucket",
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "SNS:Publish",
        }
    )
    bad = _deny(doc)
    assert bad, (
        "an unconditioned grant sitting beside a correctly-scoped one is "
        "still an unconditioned grant"
    )


@requires_opa
def test_a_statement_missing_its_principal_or_action_still_counts_as_granting()  -> None:
    """The `== null` spelling, pinned.

    `not object.get(st, "Principal", null)` is FALSE whether the key is
    absent or present -- `object.get` returns its DEFAULT when the key is
    missing and `null` is TRUTHY in Rego -- so the "absent counts as
    granting" clause written that way is dead code, and a statement that
    omits `Principal` or `Action` would silently escape the scoping
    requirement. Same defect class as the dead `not parse_traversal(x)`
    guards this round fixes in the shared library.
    """
    for drop in ("Principal", "Action"):
        doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
        st = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
        del st["Condition"]
        del st[drop]
        bad = _deny(doc)
        assert bad, (
            f"a statement with no `{drop}` and no aws:SourceArn condition must "
            "still be treated as granting and DENY"
        )


@requires_opa
def test_an_unreadable_effect_counts_as_granting() -> None:
    """`!= "deny"`, not `== "allow"`. An Effect this rule cannot read must
    not exempt the statement from scoping."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    st = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
    del st["Condition"]
    st["Effect"] = {"unreadable": "expression"}
    assert _deny(doc), "an unreadable Effect must count as granting"


@requires_opa
def test_an_explicit_deny_statement_needs_no_source_arn_condition() -> None:
    """...and the other side of the same rule: an Effect:Deny statement is
    not a grant, so requiring it to carry a scoping condition would be a
    false FAIL."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"].append(
        {
            "Sid": "DenyInsecureTransport",
            "Effect": "Deny",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "SNS:Publish",
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }
    )
    assert _deny(doc) == [], _deny(doc)


@requires_opa
def test_a_negating_condition_operator_is_not_scoping_evidence() -> None:
    """`ArnNotLike aws:SourceArn = <this bucket>` scopes the grant to every
    bucket EXCEPT this one."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    st = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
    st["Condition"] = {"ArnNotLike": {"aws:SourceArn": "${local.arns.media_bucket}"}}
    assert _deny(doc), "a negating operator must not read as scoping"


@requires_opa
def test_a_policy_document_this_resolver_cannot_read_denies_by_name() -> None:
    """Fail-closed, and LOUD: no readable document is not a pass."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    del doc["_hcl"]["main.tf"]["#jsonencode"]
    bad = _deny(doc)
    assert bad, "an unreadable policy document must DENY"
    assert any("cannot read the STRUCTURE" in d for d in bad), bad


@requires_opa
def test_a_topic_policy_off_the_notification_path_is_not_graded() -> None:
    """ROUND-16 RULING-3 fix, pinned.

    A correct solution that also declares an unrelated ops/alarms topic with
    its own policy was DENIED, with a message its own artifact refuted. The
    unrelated policy is attached to a topic no notification wires, so it is
    not this scenario's business.
    """
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    doc["planned_values"]["root_module"]["resources"].append(
        {"address": "aws_sns_topic.ops", "type": "aws_sns_topic", "name": "ops", "values": {}}
    )
    doc["configuration"]["root_module"]["resources"] += [
        {"address": "aws_sns_topic.ops", "type": "aws_sns_topic", "name": "ops", "mode": "managed", "expressions": {}},
        {
            "address": "aws_sns_topic_policy.ops",
            "type": "aws_sns_topic_policy",
            "name": "ops",
            "mode": "managed",
            "expressions": {
                "arn": {"references": ["aws_sns_topic.ops.arn", "aws_sns_topic.ops"]},
                "policy": {"references": ["aws_sns_topic.ops.arn", "aws_sns_topic.ops"]},
            },
        },
    ]
    doc["_hcl"]["main.tf"]["resource"]["aws_sns_topic_policy"]["ops"] = [
        {"policy": "${jsonencode({...})}"}
    ]
    doc["_hcl"]["main.tf"]["#jsonencode"].append(
        {
            "path": ["resource", "aws_sns_topic_policy", "ops", 0, "policy"],
            "doc": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowAlarms",
                        "Effect": "Allow",
                        "Principal": {"Service": "cloudwatch.amazonaws.com"},
                        "Action": "SNS:Publish",
                    }
                ],
            },
        }
    )
    assert _deny(doc) == [], _deny(doc)


@requires_opa
def test_parse_traversal_is_UNDEFINED_for_an_untokenizable_string() -> None:
    """The guard predicate itself. `not parse_traversal(x)` must be TRUE."""
    for bad in (
        "aws_s3_bucket.b[0].arn",
        "not a traversal at all !!",
        'format("%s/*", aws_s3_bucket.media.arn)',
        "aws_s3_bucket.b[*].arn",
    ):
        rc, out, err = _eval(
            "not data.cdktn_bench.hcl.parse_traversal(%s)" % json.dumps(bad), {}, LIB
        )
        assert rc == 0, f"opa ABORTED on {bad!r} (exit {rc}): {err.strip()}"
        result = json.loads(out).get("result")
        assert result, (
            f"`not parse_traversal({bad!r})` is FALSE -- the refusal path is dead "
            "code again (a comprehension over an undefined body returns the empty "
            "collection, which is DEFINED)"
        )


@requires_opa
def test_unparseable_reports_the_references_it_cannot_tokenize() -> None:
    rc, out, err = _eval(
        'data.cdktn_bench.hcl._unparseable('
        '["aws_s3_bucket.media[0].arn", "not a traversal at all !!", '
        '"aws_s3_bucket.media.arn"])',
        {},
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    value = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert sorted(value) == [
        "aws_s3_bucket.media[0].arn",
        "not a traversal at all !!",
    ], value


@requires_opa
def test_slot_refuses_a_whole_slot_holding_an_untokenizable_reference() -> None:
    """The SHIPPED path, with the numeric reference QUOTED in the reason.

    These are the three references `terraform show -json` really emits for
    `source_arn = aws_s3_bucket.media[0].arn` (a traversal plus every one of
    its prefixes). Before round 16 this returned a `resolved` verdict for
    `aws_s3_bucket.media` -- the two it could not read were dropped and the
    survivor looked confidently resolved.
    """
    rc, out, err = _eval(
        'data.cdktn_bench.hcl.slot('
        '["aws_s3_bucket.media[0].arn", "aws_s3_bucket.media[0]", '
        '"aws_s3_bucket.media"])',
        {},
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    v = json.loads(out)["result"][0]["expressions"][0]["value"]
    assert v["kind"] == "unresolvable", v
    assert "cannot tokenize" in v["reason"], v
    assert "aws_s3_bucket.media[0].arn" in v["reason"], (
        "the deny message must QUOTE the reference the resolver could not "
        f"read; it says: {v['reason']}"
    )


@requires_opa
def test_an_opaque_expression_gets_the_tokenizer_reason_not_a_locals_reason() -> None:
    """`format(...)` is not a `local.` symbol at all, and must not be
    reported as one. Before round 16 the reason read "no `locals` block in
    any supplied .tf file defines format(\"%s/*\", aws_s3_bucket.media.arn)".
    """
    v = _resolve_one(
        'format("%s/*", aws_s3_bucket.media.arn)',
        {"main.tf": {"locals": [{"a": "x"}]}},
    )
    assert v["kind"] == "unresolvable", v
    assert "not a traversal this resolver can tokenize" in v["reason"], v
    assert "locals" not in v["reason"], v


@requires_opa
def test_each_value_gets_its_own_reason_not_names_no_resource_at_all() -> None:
    """ROUND-16 RULING-3 fix. `each` used to share one reason with
    `count`/`self`/`path`/`terraform` ending "...name no resource at all".
    That is FALSE of an artifact whose `for_each` iterates a resource: the
    scenario policy resolves exactly that case via `for_each_referent`, and
    an executed deny asserted the opposite about the graded artifact.
    """
    v = _resolve_one("each.value.arn", {})
    assert v["kind"] == "unresolvable", v
    assert "name no resource at all" not in v["reason"], v
    assert "for_each" in v["reason"], v


def _for_each_plan(*, permission_key: str) -> dict:
    """Two `for_each` instances of ONE `aws_s3_bucket` block.

    `permission_key` selects which instance the invoke permission and the
    topic policy's condition are scoped to. "media" is the CORRECT twin
    (must deny nothing); "decoy" is the broken one (must deny).

    Instance keys, `.index` on each planned resource and the `["key"]`
    reference spelling are all copied from a real `terraform show -json` of
    this exact shape -- see
    solution/broken/lambda-permission-scoped-to-a-decoy-for-each-instance/.
    """
    def bucket(key: str) -> dict:
        return {
            "address": f'aws_s3_bucket.b["{key}"]',
            "type": "aws_s3_bucket",
            "name": "b",
            "index": key,
            "values": {"bucket": key},
        }

    arn = f'aws_s3_bucket.b["{permission_key}"].arn'
    return {
        "planned_values": {
            "root_module": {
                "resources": [
                    bucket("media"),
                    bucket("decoy"),
                    {"address": "aws_sns_topic.audit", "type": "aws_sns_topic", "name": "audit", "values": {}},
                    {
                        "address": "aws_lambda_permission.allow_s3_invoke",
                        "type": "aws_lambda_permission",
                        "name": "allow_s3_invoke",
                        "values": {"principal": "s3.amazonaws.com"},
                    },
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "values": {"topic": [{"events": ["s3:ObjectRemoved:*"]}]},
                    },
                ]
            }
        },
        "configuration": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.b", "type": "aws_s3_bucket", "name": "b", "mode": "managed", "expressions": {}},
                    {"address": "aws_sns_topic.audit", "type": "aws_sns_topic", "name": "audit", "mode": "managed", "expressions": {}},
                    {
                        "address": "aws_lambda_permission.allow_s3_invoke",
                        "type": "aws_lambda_permission",
                        "name": "allow_s3_invoke",
                        "mode": "managed",
                        "expressions": {"source_arn": {"references": [arn, f'aws_s3_bucket.b["{permission_key}"]', "aws_s3_bucket.b"]}},
                    },
                    {
                        "address": "aws_sns_topic_policy.audit",
                        "type": "aws_sns_topic_policy",
                        "name": "audit",
                        "mode": "managed",
                        "expressions": {
                            "arn": {"references": ["aws_sns_topic.audit.arn", "aws_sns_topic.audit"]},
                            "policy": {"references": [arn, f'aws_s3_bucket.b["{permission_key}"]', "aws_sns_topic.audit.arn"]},
                        },
                    },
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "mode": "managed",
                        "expressions": {
                            "bucket": {"references": ['aws_s3_bucket.b["media"].id', 'aws_s3_bucket.b["media"]', "aws_s3_bucket.b"]},
                            "lambda_function": [
                                {"lambda_function_arn": {"references": ["aws_lambda_function.ingest.arn"]}}
                            ],
                            "topic": [
                                {"topic_arn": {"references": ["aws_sns_topic.audit.arn", "aws_sns_topic.audit"]}}
                            ],
                        },
                    },
                ]
            }
        },
        "_hcl": {"main.tf": _topic_policy_doc("audit", '${aws_s3_bucket.b["%s"].arn}' % permission_key)},
    }


def _deny(doc: dict) -> list[str]:
    rc, out, err = _eval(
        "data.cdktn_bench.s3_notification_authoritative_singleton.deny",
        doc,
        SCENARIO_POLICY,
        LIB,
    )
    assert rc == 0, f"opa ABORTED (exit {rc}): {err.strip()}"
    return json.loads(out)["result"][0]["expressions"][0]["value"]


@requires_opa
def test_for_each_instance_key_discriminates() -> None:
    """THE ROUND-15 BLOCKER, both halves, in one test.

    Two byte-identical artifacts apart from one instance key. Under the
    round-14 oracle BOTH scored reward 1.0 (verified in the real image); the
    only acceptable outcome is that exactly one of them denies.

    The positive half is why this lives here rather than only under
    solution/broken/: the falsifiability gate has one positive slot, so a
    "correct, and must stay correct" `for_each` variant has nowhere else to
    live -- and a fix that closed the negative by refusing every `for_each`
    referent outright would pass the fixture and fail this assertion.
    """
    good = _deny(_for_each_plan(permission_key="media"))
    assert good == [], f"the CORRECT for_each twin must deny nothing: {good}"

    bad = _deny(_for_each_plan(permission_key="decoy"))
    assert bad, "a permission scoped to the DECOY for_each instance must DENY"
    assert any('aws_s3_bucket.b["decoy"]' in d for d in bad), bad
    assert any('aws_s3_bucket.b["media"]' in d for d in bad), bad


# ---------------------------------------------------------------------------
# 7. (ROUND 15) EVERY WIRED TOPIC IS GRADED, NOT JUST SOME MEMBER OF THE SET
# ---------------------------------------------------------------------------


def _two_topic_plan(*, policy_on: str) -> dict:
    """One notification with TWO `topic` blocks; ONE policy, on `policy_on`.

    `policy_on="audit"` is the honest artifact. `policy_on="decoy"` is the
    laundering: the audit topic the ticket is about is wired for deletes and
    carries NO resource policy, so S3 cannot publish to it -- yet every
    round-14 rule passed, because the anchor was a UNION and the acceptance
    test only asked for MEMBERSHIP in it.
    """
    def topic(name: str) -> dict:
        return {"address": f"aws_sns_topic.{name}", "type": "aws_sns_topic", "name": name, "mode": "managed", "expressions": {}}

    return {
        "planned_values": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.media", "type": "aws_s3_bucket", "name": "media", "values": {"bucket": "media"}},
                    {"address": "aws_sns_topic.audit", "type": "aws_sns_topic", "name": "audit", "values": {}},
                    {"address": "aws_sns_topic.decoy", "type": "aws_sns_topic", "name": "decoy", "values": {}},
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "values": {"topic": [{"events": ["s3:ObjectRemoved:*"]}, {"events": ["s3:ObjectRemoved:Delete"]}]},
                    },
                ]
            }
        },
        "configuration": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.media", "type": "aws_s3_bucket", "name": "media", "mode": "managed", "expressions": {}},
                    topic("audit"),
                    topic("decoy"),
                    {
                        "address": f"aws_sns_topic_policy.{policy_on}",
                        "type": "aws_sns_topic_policy",
                        "name": policy_on,
                        "mode": "managed",
                        "expressions": {
                            "arn": {"references": [f"aws_sns_topic.{policy_on}.arn", f"aws_sns_topic.{policy_on}"]},
                            "policy": {"references": ["aws_s3_bucket.media.arn", "aws_s3_bucket.media"]},
                        },
                    },
                    {
                        "address": "aws_s3_bucket_notification.media",
                        "type": "aws_s3_bucket_notification",
                        "name": "media",
                        "mode": "managed",
                        "expressions": {
                            "bucket": {"references": ["aws_s3_bucket.media.id", "aws_s3_bucket.media"]},
                            "topic": [
                                {"topic_arn": {"references": ["aws_sns_topic.audit.arn", "aws_sns_topic.audit"]}},
                                {"topic_arn": {"references": ["aws_sns_topic.decoy.arn", "aws_sns_topic.decoy"]}},
                            ],
                        },
                    },
                ]
            }
        },
        "_hcl": {"main.tf": _topic_policy_doc(policy_on, "${aws_s3_bucket.media.arn}")},
    }


@requires_opa
def test_an_extra_topic_block_cannot_launder_a_decoy_policy() -> None:
    """Adding ONE `topic` block used to turn a checked-in catch into a 1.0.

    Executed in the real image before the fix: two topic blocks, one
    `aws_sns_topic_policy` on the decoy, `aws_sns_topic.audit` with no
    resource policy at all -> `tier1_status=PASS`, deny `[]`, REWARD 1.0.
    """
    bad = _deny(_two_topic_plan(policy_on="decoy"))
    assert bad, "a wired topic with NO resource policy must DENY"
    assert any("aws_sns_topic.audit" in d for d in bad), bad


@requires_opa
def test_an_unresolvable_second_topic_block_is_not_carried_by_the_first() -> None:
    """The per-BLOCK gate, not the per-RESOURCE one.

    `_has_topic_anchor` was satisfied if ANY block of a notification
    resolved, so a second block whose `topic_arn` this resolver cannot
    follow contributed no instance and was never mentioned again -- an
    ungraded topic reading exactly like a graded one.
    """
    doc = _two_topic_plan(policy_on="audit")
    for r in doc["configuration"]["root_module"]["resources"]:
        if r["type"] == "aws_s3_bucket_notification":
            r["expressions"]["topic"][1]["topic_arn"] = {"references": ["var.other_topic_arn"]}
    bad = _deny(doc)
    assert bad, "a topic block whose topic_arn cannot be resolved must DENY"
    assert any("topic` block #1" in d for d in bad), bad


# ---------------------------------------------------------------------------
# 8. (ROUND 15) THE POLICY MUST NOT FAIL OPEN ON A SHAPE IT CANNOT READ
# ---------------------------------------------------------------------------


@requires_opa
@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d["configuration"]["root_module"].pop("resources"), id="configuration-resources-absent"),
        pytest.param(lambda d: d["configuration"]["root_module"].update(resources="nope"), id="configuration-resources-not-a-list"),
        pytest.param(lambda d: d.pop("configuration"), id="configuration-absent"),
    ],
)
def test_an_unreadable_configuration_fails_closed(mutate) -> None:
    """`configured_resources` was a BARE reference.

    An absent key made it UNDEFINED, which made every rule downstream of it
    undefined, and an undefined `deny` rule does not deny. Executed on the
    real merged oracle input: all three mutations below returned `deny`
    length 0 -- the whole tier-1 policy failing OPEN, nine lines above a
    `planned_resources` whose own comment already explained why.
    """
    doc = _two_topic_plan(policy_on="audit")
    mutate(doc)
    bad = _deny(doc)
    assert bad, "an unreadable .configuration must DENY, never pass silently"


@requires_opa
def test_resources_inside_a_module_are_refused_by_name() -> None:
    """The agent-reachable route to the fail-open above.

    A `module` block puts every resource under `module_calls`/
    `child_modules` and leaves `root_module.resources` ABSENT. This oracle
    reads the root module only, so those resources are not graded at all --
    and an ungraded resource must never read as a correct one.
    """
    doc = {
        "planned_values": {"root_module": {"child_modules": [{"address": "module.wiring", "resources": []}]}},
        "configuration": {"root_module": {"module_calls": {"wiring": {"source": "./modules/wiring"}}}},
        "_hcl": {"main.tf": {}},
    }
    bad = _deny(doc)
    assert bad, "resources hidden inside a module must DENY"
    assert any("wiring" in d for d in bad), bad


# ---------------------------------------------------------------------------
# 9. (ROUND 15) A `count`/`for_each` ON THE GRADED PERMISSION IS STILL GRADED
# ---------------------------------------------------------------------------


def _counted_permission_plan(*, source_arn: str) -> dict:
    """`aws_lambda_permission.allow_s3_invoke[0]` in the plan,
    `aws_lambda_permission.allow_s3_invoke` in the configuration.

    That address skew is what `count = 1` does, and joining the two on
    `.address` -- which is what the policy used to do -- never matched. The
    scoping rule was silently disabled and the fail-closed fallback fired
    with a message the plan flatly contradicts (RULING 3): a fully correct
    solution scored REWARD 0.0.
    """
    doc = _two_topic_plan(policy_on="audit")
    del doc["configuration"]["root_module"]["resources"][-1]["expressions"]["topic"][1]
    del doc["planned_values"]["root_module"]["resources"][-1]["values"]["topic"][1]
    doc["planned_values"]["root_module"]["resources"].append(
        {
            "address": "aws_lambda_permission.allow_s3_invoke[0]",
            "type": "aws_lambda_permission",
            "name": "allow_s3_invoke",
            "index": 0,
            "values": {"principal": "s3.amazonaws.com"},
        }
    )
    doc["configuration"]["root_module"]["resources"].append(
        {
            "address": "aws_lambda_permission.allow_s3_invoke",
            "type": "aws_lambda_permission",
            "name": "allow_s3_invoke",
            "mode": "managed",
            "expressions": {"source_arn": {"references": [source_arn, source_arn.rsplit(".", 1)[0]]}},
        }
    )
    for r in doc["configuration"]["root_module"]["resources"]:
        if r["type"] == "aws_s3_bucket_notification":
            r["expressions"]["lambda_function"] = [
                {"lambda_function_arn": {"references": ["aws_lambda_function.ingest.arn"]}}
            ]
    return doc


@requires_opa
def test_a_counted_permission_is_graded_not_vanished() -> None:
    good = _deny(_counted_permission_plan(source_arn="aws_s3_bucket.media.arn"))
    assert good == [], f"a CORRECT solution with `count` on the permission must deny nothing: {good}"


@requires_opa
def test_a_counted_permission_scoped_to_the_wrong_bucket_still_denies() -> None:
    """The other half: making the join work must not make it permissive."""
    doc = _counted_permission_plan(source_arn="aws_s3_bucket.decoy.arn")
    doc["planned_values"]["root_module"]["resources"].append(
        {"address": "aws_s3_bucket.decoy", "type": "aws_s3_bucket", "name": "decoy", "values": {"bucket": "decoy"}}
    )
    doc["configuration"]["root_module"]["resources"].append(
        {"address": "aws_s3_bucket.decoy", "type": "aws_s3_bucket", "name": "decoy", "mode": "managed", "expressions": {}}
    )
    bad = _deny(doc)
    assert bad, "a counted permission scoped to the wrong bucket must DENY"
    assert any("aws_s3_bucket.decoy.arn" in d for d in bad), bad


# ---------------------------------------------------------------------------
# ROUND 17 (a): the CONDITION VALUE LIST is OR-ed, and `some` is the wrong
# quantifier for it
# ---------------------------------------------------------------------------


@requires_opa
def test_a_wildcard_beside_the_wired_bucket_is_not_scoping() -> None:
    """THE ROUND-17 BLOCKER, pinned at the policy level.

    Round 16 replaced the *mention* test with a *position* test, which was
    right, and then emitted ONE SLOT PER VALUE and accepted a statement on
    `some` slot. IAM OR-s the values inside ONE condition position and AND-s
    distinct positions -- two different logical connectives, one quantifier.
    So the reference solution with ONE edit,

        ArnLike = { "aws:SourceArn" = [local.arns.media_bucket, "arn:aws:s3:::*"] }

    scored `tier0_pass=1 tier1_status=PASS`, `deny []`, REWARD 1.0 in the
    REAL image under `--network none`, on a topic policy that lets any S3
    bucket in any account publish -- the exact property the deny message
    claims to enforce. Both halves are asserted here: the single-value
    spelling must still pass (a fix that refused every list would satisfy the
    negative half and break every correct solution), and the OR-ed spelling
    must deny.
    """
    scoped = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    assert _deny(scoped) == [], _deny(scoped)

    for extra in ("arn:aws:s3:::*", "${aws_s3_bucket.decoy.arn}"):
        laundered = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
        st = laundered["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
        st["Condition"] = {
            "ArnLike": {"aws:SourceArn": ["${local.arns.media_bucket}", extra]}
        }
        bad = _deny(laundered)
        assert bad, (
            f"a condition position holding [the wired bucket, {extra!r}] is "
            "OR-ed by IAM and scopes NOTHING -- it must DENY"
        )
        assert any("aws:SourceArn" in d for d in bad), bad


@requires_opa
def test_a_second_and_ed_condition_position_does_not_break_scoping() -> None:
    """The other half of the same correction: `some` ACROSS positions.

    Distinct (operator, condition key) positions are AND-ed by IAM, so an
    extra one can only narrow a grant. A correct solution that also pins
    `aws:SourceAccount` must keep passing -- an `every`-across-positions fix
    would have broken it, which is why the two quantifiers are split rather
    than both tightened.
    """
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    st = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
    st["Condition"] = {
        "ArnLike": {"aws:SourceArn": "${local.arns.media_bucket}"},
        "StringEquals": {"aws:SourceAccount": "123456789012"},
    }
    assert _deny(doc) == [], _deny(doc)


@requires_opa
def test_a_condition_position_with_no_readable_value_list_is_refused() -> None:
    """A position must carry at least one value; `every` over an empty list
    is vacuously TRUE and would have made an unreadable value list read as
    perfect scoping."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], _ARNS_LOCALS)
    st = doc["_hcl"]["main.tf"]["#jsonencode"][0]["doc"]["Statement"][0]
    st["Condition"] = {"ArnLike": {"aws:SourceArn": {"not": "a list of values"}}}
    bad = _deny(doc)
    assert bad, "a condition value that is neither a string nor a list scopes nothing"


# ---------------------------------------------------------------------------
# ROUND 17 (b): an ordinary DRY hoist INSIDE the policy document
# ---------------------------------------------------------------------------
#
# These are the POSITIVE half of the round-17 correction and they cannot
# live under solution/broken/, which has no positive slot. All four were
# EXECUTED at `tier1_status=FAIL`, reward 0.0, on a FULLY CORRECT artifact,
# each with the identical message "...has 0 statement(s) granting the
# s3.amazonaws.com service principal sns:Publish, and not every one of them
# is scoped...". This is spike-memo defect (b) -- the false FAIL on a DRY
# hoist the whole traversal library exists to close -- reintroduced one
# level down, inside the policy document.


def _hoisted_plan(mutate) -> dict:
    """The reference artifact with part of its policy document hoisted into
    `locals`, exactly as an ordinary DRY solution would write it."""
    doc = _plan(["local.arns.media_bucket", "local.arns"], dict(_ARNS_LOCALS))
    main = doc["_hcl"]["main.tf"]
    mutate(main)
    return doc


@requires_opa
def test_a_policy_document_hoisted_into_a_local_is_read_not_refused() -> None:
    """`policy = jsonencode(local.topic_doc)`.

    The recovered `#jsonencode` body is the STRING `"${local.topic_doc}"`,
    not an object. Round 16 took it raw, so it counted as a "document",
    `_policy_document_unreadable` was FALSE, the promised loud deny never
    fired, and the artifact was graded as having zero statements.
    """

    def mutate(main):
        body = main["#jsonencode"][0]["doc"]
        main["locals"][0]["topic_doc"] = body
        main["#jsonencode"][0]["doc"] = "${local.topic_doc}"

    assert _deny(_hoisted_plan(mutate)) == [], _deny(_hoisted_plan(mutate))


@requires_opa
def test_a_statement_list_hoisted_into_a_local_is_read_not_refused() -> None:
    """`Statement = local.stmts`."""

    def mutate(main):
        body = main["#jsonencode"][0]["doc"]
        main["locals"][0]["stmts"] = body["Statement"]
        body["Statement"] = "${local.stmts}"

    assert _deny(_hoisted_plan(mutate)) == [], _deny(_hoisted_plan(mutate))


@requires_opa
def test_a_hoisted_principal_or_action_does_not_delete_the_grant() -> None:
    """`Principal = local.s3_principal` / `Action = local.publish_action`.

    Both predicates used to fall back to "covers" only when the key was
    ABSENT (`== null`), never when it was present but UNREADABLE, so a
    hoisted value silently REMOVED a real grant from grading -- which is why
    the spec's own claim that every predicate "errs towards 'this statement
    grants'" was executably false.
    """
    for key, local_name, value in (
        ("Principal", "s3_principal", {"Service": "s3.amazonaws.com"}),
        ("Action", "publish_action", "SNS:Publish"),
    ):

        def mutate(main, key=key, local_name=local_name, value=value):
            main["locals"][0][local_name] = value
            main["#jsonencode"][0]["doc"]["Statement"][0][key] = (
                "${local.%s}" % local_name
            )

        assert _deny(_hoisted_plan(mutate)) == [], _deny(_hoisted_plan(mutate))


@requires_opa
def test_an_unreadable_principal_or_action_still_counts_as_granting() -> None:
    """The fail-closed direction of the same rewrite: a value this reader
    CANNOT resolve (a `var.`, not a `local.`) must keep the statement in
    grading, so dropping its Condition still DENIES. Erring the other way is
    how an adversarial solution would delete a grant from the oracle's view.
    """
    for key in ("Principal", "Action"):

        def mutate(main, key=key):
            st = main["#jsonencode"][0]["doc"]["Statement"][0]
            st[key] = "${var.opaque}"
            del st["Condition"]

        bad = _deny(_hoisted_plan(mutate))
        assert bad, (
            f"an unreadable {key} must count as GRANTING -- otherwise hoisting "
            "it deletes a real, unconditioned grant from grading"
        )


@requires_opa
def test_a_document_that_is_still_not_an_object_denies_loudly() -> None:
    """`jsonencode(var.topic_doc)` -- nothing in the parsed `locals` can
    resolve it, so it must hit the LOUD unreadable deny (not "0 granting
    statements", and not silence)."""

    def mutate(main):
        main["#jsonencode"][0]["doc"] = "${var.topic_doc}"

    bad = _deny(_hoisted_plan(mutate))
    assert bad, "an unreadable policy document must DENY"
    assert any("cannot read the STRUCTURE" in d for d in bad), bad


@requires_opa
def test_zero_granting_statements_gets_its_own_message() -> None:
    """A document this reader reads perfectly and which grants
    s3.amazonaws.com nothing must be told THAT, not "not every one of them is
    scoped ... any S3 bucket in any account can publish" -- a sentence the
    artifact refutes on both counts (Amendment 29 RULING 3)."""

    def mutate(main):
        main["#jsonencode"][0]["doc"]["Statement"][0]["Principal"] = {
            "Service": "events.amazonaws.com"
        }

    bad = _deny(_hoisted_plan(mutate))
    assert bad, "a policy granting S3 nothing must DENY"
    assert any("found NO statement granting" in d for d in bad), bad
    assert not any("not every one of them is scoped" in d for d in bad), bad
