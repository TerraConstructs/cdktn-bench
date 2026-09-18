"""Compile oracle.structural_asserts (SCHEMA.md §4.2) to Rego, at *generation*
time -- the sibling of jsonpath_jq.py over the identical grammar, so one assert
source in the spec YAML feeds both static tiers in one policy language.

The grammar, its `|fromjson` extension and the ValueError raised on anything
outside it are jsonpath_jq.py's; this module imports its regexes rather than
restating them, so the two backends cannot drift apart on what a path means.

What is NOT shared is error behaviour, and that is the whole difficulty. jq
raises on a field access into a scalar, on iterating a non-collection, and on
`fromjson` over a non-string, invalid JSON or escapes only its own decoder
rejects, and `assert_check` reports each raise as UNRESOLVABLE (rc 2) rather
than as a verdict. Rego turns the same situations into silent undefined, which
would collapse "the question could not be asked" into "the path found no node"
-- a vacuous pass. So each is emitted as an EXPLICIT rule contributing a reason
string to the assert's `_err` set, and an assert with a non-empty `_err` is
unresolvable whatever its op would have said.

Emitted shape and op semantics: docs/design/m10-one-rego-engine.md §3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from jsonpath_jq import (
    FROMJSON_SEP,
    _FIELD_COND_RE,
    _FIELD_RE,
    _FILTER_RE,
    _RECURSIVE_FIELD_RE,
    _VALUE_COND_RE,
    _WILDCARD_RE,
)

# Ops jq's assert_check implements. Anything else is UNRESOLVABLE (the emitted
# file says so in its own reason string) rather than a generation-time refusal:
# "an op this library does not know" is a three-valued outcome the translation
# has to be able to produce, not an error to raise here.
SUPPORTED_OPS = frozenset(
    {
        "exists", "not_exists", "eq", "in", "contains", "regex", "set_eq",
        "absent_or_eq", "not_regex",
    }
)

# The `expected` type four of those ops need, which SCHEMA.md §4.2's schema
# does not itself carry. jq coerces silently (`index` over a string `expected`
# becomes a SUBSTRING search) and Rego cannot coerce at all -- `regex.match(5,
# v)` is a TYPE error that refuses to compile the WHOLE policy, taking every
# other assert in the file with it. Emitting an `_err` instead keeps a mistyped
# `expected` a per-assert unresolvable, so the arm still grades its remaining
# asserts; generator/spec_model.py refuses it at spec load, which is where an
# author sees it.
EXPECTED_TYPE: dict[str, tuple[type, str]] = {
    "in": (list, "a list"),
    "set_eq": (list, "a list"),
    "regex": (str, "a string"),
    "not_regex": (str, "a string"),
}


@dataclass(frozen=True)
class FieldCond:
    """One `@.F.G=='V'` filter condition: a chain of field hops, then equality."""

    chain: tuple[str, ...]
    literal: str


@dataclass(frozen=True)
class ValueCond:
    """One bare `@=='V'` filter condition: the element itself equals a literal."""

    literal: str


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Wildcard:
    pass


@dataclass(frozen=True)
class Descend:
    name: str


@dataclass(frozen=True)
class FromJson:
    pass


@dataclass(frozen=True)
class Filter:
    conds: tuple[FieldCond | ValueCond, ...]


Stage = Field | Wildcard | Descend | FromJson | Filter


def parse_jsonpath(path: str) -> list[Stage]:
    """Tokenize one cfn_jsonpath/tf_jsonpath into the stage list the emitter
    unrolls. Each stage maps a list of nodes to the next list of nodes, exactly
    as the corresponding jq filter fragment does."""
    segments = path.split(FROMJSON_SEP)
    stages = _parse_fragment(segments[0], path, require_dollar=True)
    for seg in segments[1:]:
        stages.append(FromJson())
        stages.extend(_parse_fragment(seg, path, require_dollar=False))
    return stages


def _parse_fragment(fragment: str, path: str, *, require_dollar: bool) -> list[Stage]:
    if require_dollar:
        if not fragment.startswith("$"):
            raise ValueError(
                f"jsonpath_rego: expected a JSONPath starting with '$', got {fragment!r}"
            )
        rest = fragment[1:]
    else:
        rest = fragment
    stages: list[Stage] = []
    while rest:
        # Recursive descent is matched before plain field access for the same
        # reason jsonpath_jq does it: keeping the non-overlap explicit.
        m = _RECURSIVE_FIELD_RE.match(rest)
        if m:
            stages.append(Descend(m.group(1)))
            rest = rest[m.end():]
            continue
        m = _FIELD_RE.match(rest)
        if m:
            stages.append(Field(m.group(1)))
            rest = rest[m.end():]
            continue
        m = _FILTER_RE.match(rest)
        if m:
            stages.append(Filter(_parse_filter(m.group(1))))
            rest = rest[m.end():]
            continue
        m = _WILDCARD_RE.match(rest)
        if m:
            stages.append(Wildcard())
            rest = rest[m.end():]
            continue
        raise ValueError(
            f"jsonpath_rego: cannot parse remainder {rest!r} of path {path!r} "
            "— unsupported JSONPath segment for this translator"
        )
    return stages


def _parse_filter(inner: str) -> tuple[FieldCond | ValueCond, ...]:
    conds: list[FieldCond | ValueCond] = []
    for raw in inner.split("||"):
        cond = raw.strip()
        m = _FIELD_COND_RE.match(cond)
        if m:
            conds.append(FieldCond(tuple(m.group(1).split(".")), m.group(2)))
            continue
        m = _VALUE_COND_RE.match(cond)
        if m:
            conds.append(ValueCond(m.group(1)))
            continue
        raise ValueError(
            f"jsonpath_rego: unsupported filter condition {cond!r} "
            "(only \"@.Field=='literal'\" -- optionally with further "
            "\".Nested\" field hops -- or bare \"@=='literal'\", combined "
            "with '||', is supported)"
        )
    return tuple(conds)


# ---------------------------------------------------------------------------
# emission
# ---------------------------------------------------------------------------

# jq's type rules, restated once per emitted file so every per-assert rule
# below is a plain application of them. A field access yields the value (or
# null for a missing key) on an object and null on null, and is an error on
# every other type; iteration covers arrays and objects only.
_HELPERS = """\
_fieldable(v) if is_object(v)

_fieldable(v) if is_null(v)

_field(v, k) := object.get(v, k, null) if is_object(v)

_field(v, _) := null if is_null(v)

_iterable(v) if is_array(v)

_iterable(v) if is_object(v)

_elems(v) := v if is_array(v)

_elems(v) := [x | some k; x := v[k]] if is_object(v)

# One level of list flattening, for `in`/`set_eq`: a property that is a bare
# string on one matched node and a list on the next compares the same way.
_as_list(v) := v if is_array(v)

_as_list(v) := [v] if not is_array(v)

_flat1(vals) := [x |
	some i, j
	x := _as_list(vals[i])[j]
]

_member(haystack, x) if {
	some i
	haystack[i] == x
}
"""


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)


def _lit(value: object) -> str:
    """A JSON literal is also a Rego term, for every value a spec can carry."""
    return json.dumps(value)


def _chain_expr(target: str, chain: tuple[str, ...]) -> str:
    expr = target
    for hop in chain:
        expr = f"_field({expr}, {_lit(hop)})"
    return expr


def _emit_stage(prefix: str, index: int, stage: Stage) -> tuple[list[str], list[str]]:
    """One stage's node-list rule plus the rules that name its jq errors."""
    prev = f"{prefix}_n{index - 1}"
    cur = f"{prefix}_n{index}"
    nodes: list[str] = []
    errs: list[str] = []

    if isinstance(stage, Field):
        nodes.append(f"{cur} := [x |\n\tsome i\n\tx := _field({prev}[i], {_lit(stage.name)})\n]")
        errs.append(
            f"{prefix}_err contains sprintf("
            f'"field access .%s on a %s node", [{_lit(stage.name)}, type_name(v)]) if {{\n'
            f"\tsome i\n\tv := {prev}[i]\n\tnot _fieldable(v)\n}}"
        )
    elif isinstance(stage, Wildcard):
        nodes.append(f"{cur} := [x |\n\tsome i, j\n\tx := _elems({prev}[i])[j]\n]")
        errs.append(
            f'{prefix}_err contains sprintf("[*] cannot iterate over a %s node", '
            f"[type_name(v)]) if {{\n\tsome i\n\tv := {prev}[i]\n\tnot _iterable(v)\n}}"
        )
    elif isinstance(stage, Descend):
        nodes.append(
            f"{cur} := [x |\n\tsome i\n\twalk({prev}[i], [_, sub])\n\tis_object(sub)\n"
            f"\tx := object.get(sub, {_lit(stage.name)}, null)\n]"
        )
    elif isinstance(stage, FromJson):
        nodes.append(
            f"{cur} := [x |\n\tsome i\n\tv := {prev}[i]\n\tis_string(v)\n"
            f"\tjson.is_valid(v)\n\tx := json.unmarshal(v)\n]"
        )
        errs.append(
            f'{prefix}_err contains sprintf("|fromjson on a %s node -- only strings '
            f'can be parsed", [type_name(v)]) if {{\n\tsome i\n\tv := {prev}[i]\n'
            f"\tnot is_string(v)\n}}"
        )
        errs.append(
            f'{prefix}_err contains "|fromjson on a string that is not valid JSON" if {{\n'
            f"\tsome i\n\tv := {prev}[i]\n\tis_string(v)\n\tnot json.is_valid(v)\n}}"
        )
        # The one input the two DECODERS read differently while neither calls
        # the string invalid: jq rejects a lone \uD800-\uDBFF escape, Go
        # accepts it and substitutes U+FFFD, so the assert would reach a verdict
        # under Rego and rc 2 under jq. RE2 has no lookahead, so "unpaired" is
        # counted -- high-surrogate escapes minus those a low one follows, which
        # leaves an escaped astral character (a pair) gradeable. The count also
        # sees a LITERAL backslash before the text uD800, which jq grades: an
        # over-refusal, in the safe direction.
        high = "\\\\u[dD][89abAB][0-9a-fA-F]{2}"
        pair = high + "\\\\u[dD][c-fC-F][0-9a-fA-F]{2}"
        errs.append(
            f'{prefix}_err contains "|fromjson on a string with an unpaired '
            f'high-surrogate escape -- jq rejects it, Rego substitutes U+FFFD" if {{\n'
            f"\tsome i\n\tv := {prev}[i]\n\tis_string(v)\n"
            f"\tcount(regex.find_n(`{high}`, v, -1)) != count(regex.find_n(`{pair}`, v, -1))\n}}"
        )
    elif isinstance(stage, Filter):
        pred = f"{prefix}_f{index}"
        for m, cond in enumerate(stage.conds):
            if isinstance(cond, FieldCond):
                test = f"{_chain_expr('x', cond.chain)} == {_lit(cond.literal)}"
            else:
                test = f"x == {_lit(cond.literal)}"
            nodes.append(f"{pred}c{m}(x) if {test}")
            nodes.append(f"{pred}(x) if {pred}c{m}(x)")
        nodes.append(
            f"{cur} := [x |\n\tsome i, j\n\tx := _elems({prev}[i])[j]\n\t{pred}(x)\n]"
        )
        errs.append(
            f'{prefix}_err contains sprintf("[?(...)] cannot iterate over a %s node", '
            f"[type_name(v)]) if {{\n\tsome i\n\tv := {prev}[i]\n\tnot _iterable(v)\n}}"
        )
        # jq's `or` short-circuits, so a condition only ever indexes an element
        # that every condition to its left already declined -- reproduced by
        # the `not <earlier condition>` guards, or a filter whose first
        # condition matches would be reported unresolvable for an error jq
        # never reaches.
        for m, cond in enumerate(stage.conds):
            if not isinstance(cond, FieldCond):
                continue
            guards = "".join(f"\tnot {pred}c{e}(x)\n" for e in range(m))
            for depth in range(len(cond.chain)):
                target = _chain_expr("x", cond.chain[:depth])
                errs.append(
                    f'{prefix}_err contains sprintf("filter condition .%s on a %s node", '
                    f"[{_lit(cond.chain[depth])}, type_name(t)]) if {{\n"
                    f"\tsome i, j\n\tx := _elems({prev}[i])[j]\n{guards}"
                    f"\tt := {target}\n\tnot _fieldable(t)\n}}"
                )
    else:
        raise AssertionError(f"unhandled stage {stage!r}")
    return nodes, errs


# ---------------------------------------------------------------------------
# where the two regex flavours mean different things
# ---------------------------------------------------------------------------
#
# jq matches with Oniguruma, Rego with RE2, and three constructs mean different
# things in the two -- so a pattern using one can reach OPPOSITE verdicts in
# the two backends with neither engine reporting an error. That is the failure
# this whole translation exists to be incapable of, and it is invisible to a
# gate that grades only the artifacts that exist: it depends on the SUBJECT.
#
# So the applicability test is emitted as a rule over the resolved values, not
# decided here: the pattern is screened at generation time for the construct,
# and the emitted rule makes the assert UNRESOLVABLE only when a value it
# actually resolved to is one the two engines would read differently. A
# refusal to grade is safe; a verdict is not. Corpus patterns
# (`^prod$`, `^GET /orders$`, `^1$`) keep grading exactly as they do today,
# because no artifact value they meet carries a trailing newline or a
# non-ASCII character.
#
# The third construct, a Go-style named group `(?P<name>...)`, is refused
# outright: RE2 accepts it and Oniguruma (which spells it `(?<name>...)`)
# cannot compile it at all, so there is no subject for which the two agree.


def _scan_pattern(pattern: str) -> tuple[bool, bool, bool]:
    r"""`(dollar_anchor, ascii_class, go_named_group)` for one pattern.

    `dollar_anchor`: an unescaped `$` outside a character class, where
    Oniguruma also matches just before a single trailing newline and RE2 only
    at end of text.

    `ascii_class`: a character-class shorthand (`\w`/`\d`/`\s`/`\b` or its
    negation) or a POSIX bracket expression (`[:alpha:]`, `[:alnum:]`, ...),
    both Unicode-aware in Oniguruma and ASCII-only in RE2. `[:ascii:]` is the
    one exception: it is ASCII-only in both, and is what the emitted refusal
    rule tests with.
    """
    dollar = ascii_class = named = False
    i, in_class = 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            if pattern[i + 1] in "wWdDsSbB":
                ascii_class = True
            i += 2
            continue
        if in_class:
            posix = re.match(r"\[:\^?([a-z]+):\]", pattern[i:])
            if posix:
                if posix.group(1) != "ascii":
                    ascii_class = True
                i += posix.end()
                continue
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "$":
            dollar = True
        elif pattern.startswith("(?P<", i):
            named = True
        i += 1
    return dollar, ascii_class, named


def _flavour_guards(prefix: str, exp: str, vals: str, pattern: str) -> list[str]:
    dollar, ascii_class, named = _scan_pattern(pattern)
    out: list[str] = []
    if named:
        out.append(
            f'{prefix}_err contains sprintf("pattern uses a Go-style named group '
            f'(?P<...>), which RE2 accepts and jq\'s Oniguruma cannot compile: %s", '
            f"[{exp}])"
        )
    if dollar:
        out.append(
            f'{prefix}_err contains sprintf("`$` in %s ends at end-of-text under RE2 '
            f'and also before one trailing newline under jq\'s Oniguruma, and %s ends '
            f'in a newline -- the two engines would reach opposite verdicts", '
            f"[{exp}, json.marshal(v)]) if {{\n"
            f"\tsome i\n\tv := {vals}[i]\n\tis_string(v)\n"
            f'\tendswith(v, "\\n")\n}}'
        )
    if ascii_class:
        out.append(
            f'{prefix}_err contains sprintf("the character-class shorthand or POSIX '
            f'bracket expression in %s is '
            f"ASCII-only under RE2 and Unicode-aware under jq's Oniguruma, and %s is "
            f'not ASCII -- the two engines would reach opposite verdicts", '
            f"[{exp}, json.marshal(v)]) if {{\n"
            f"\tsome i\n\tv := {vals}[i]\n\tis_string(v)\n"
            f'\tnot regex.match("^[[:ascii:]]*$", v)\n}}'
        )
    return out


def _emit_op(prefix: str, op: str, expected: object) -> list[str]:
    """The `<prefix>_ok` rule: assert_check's op table, clause for clause.

    The pattern ops also contribute to `<prefix>_err`, because whether a
    pattern is applicable at all is only decidable inside Rego.
    """
    exp = f"{prefix}_expected"
    vals = f"{prefix}_vals"
    ok = f"{prefix}_ok"
    out: list[str] = []
    if op == "exists":
        out.append(f"{ok} if count({vals}) > 0")
    elif op == "not_exists":
        out.append(f"{ok} if count({vals}) == 0")
    elif op == "eq":
        out.append(f"{ok} if {{\n\tcount({vals}) == 1\n\t{vals}[0] == {exp}\n}}")
    elif op == "absent_or_eq":
        out.append(f"{ok} if count({vals}) == 0")
        out.append(f"{ok} if {{\n\tcount({vals}) == 1\n\t{vals}[0] == {exp}\n}}")
    elif op == "in":
        out.append(
            f"{prefix}_not_member contains x if {{\n\tsome i\n\tx := {prefix}_flat[i]\n"
            f"\tnot _member({exp}, x)\n}}"
        )
        out.append(
            f"{ok} if {{\n\tcount({prefix}_flat) > 0\n\tcount({prefix}_not_member) == 0\n}}"
        )
    elif op == "contains":
        out.append(
            f"{prefix}_has if {{\n\tsome i, j\n\tv := {vals}[i]\n\tis_array(v)\n"
            f"\tv[j] == {exp}\n}}"
        )
        if isinstance(expected, str):
            out.append(
                f"{prefix}_has if {{\n\tsome i\n\tv := {vals}[i]\n\tis_string(v)\n"
                f"\tcontains(v, {exp})\n}}"
            )
        out.append(
            f"{prefix}_has if {{\n\tsome i\n\tv := {vals}[i]\n\tnot is_array(v)\n"
            f"\tnot is_string(v)\n\tv == {exp}\n}}"
        )
        out.append(f"{ok} if {{\n\tcount({vals}) >= 1\n\t{prefix}_has\n}}")
    elif op in ("regex", "not_regex"):
        # regex.match ERRORS on a pattern RE2 cannot compile -- a lookaround,
        # a backreference, an unbalanced character class -- and a Rego builtin
        # error is silent undefined. Left at that, `not_regex`'s `not _has`
        # would SUCCEED for a pattern that was never applied to anything and
        # report "this string appears nowhere": the vacuous pass, on the one op
        # whose entire purpose is proving an absence. Binding the builtin's
        # result is what separates "compiled, did not match" from "did not
        # compile", so an uncompilable pattern is unresolvable for both ops.
        out.append(f'{prefix}_re_usable if is_boolean(regex.match({exp}, ""))')
        out.append(
            f'{prefix}_err contains sprintf("expected is not a pattern regex.match '
            f'(RE2) can compile: %s", [{exp}]) if not {prefix}_re_usable'
        )
        out.append(
            f"{prefix}_has if {{\n\tsome i\n\tv := {vals}[i]\n\tis_string(v)\n"
            f"\tregex.match({exp}, v)\n}}"
        )
        if isinstance(expected, str):
            out.extend(_flavour_guards(prefix, exp, vals, expected))
        if op == "regex":
            out.append(f"{ok} if {{\n\tcount({vals}) >= 1\n\t{prefix}_has\n}}")
        else:
            out.append(f"{ok} if not {prefix}_has")
    elif op == "set_eq":
        out.append(
            f"{ok} if {{\n\t{{x | some i; x := {prefix}_flat[i]}} == "
            f"{{y | some j; y := {exp}[j]}}\n}}"
        )
    else:
        raise AssertionError(f"unhandled op {op!r}")
    return out


def compile_assert(name: str, jsonpath: str, op: str, expected: object) -> str:
    """One assert's Rego block: node collection, the reasons it can be
    unresolvable, the op, the three-valued outcome and the printed line."""
    prefix = f"a_{_slug(name)}"
    header = f"# --- {name} ({op}) ---\n# {jsonpath}"
    if op not in SUPPORTED_OPS:
        # No node is ever collected: an op the translation does not implement
        # is a generator/library defect, and grading it as a verdict would
        # point the operator at the artifact instead of at this file.
        return "\n\n".join(
            [
                header,
                f'{prefix}_err contains sprintf("unknown op %s", [{_lit(op)}])',
                f"{prefix}_vals := []",
                f'{prefix}_outcome := "unresolvable"',
                f'{prefix}_line := sprintf("  FAIL [%s]: %s (UNRESOLVABLE, not '
                f'contradicted)", [{_lit(name)}, concat("; ", {prefix}_err)])',
            ]
        )

    stages = parse_jsonpath(jsonpath)
    blocks: list[str] = [header, f"{prefix}_n0 := [input]"]
    errs: list[str] = []
    for i, stage in enumerate(stages, start=1):
        nodes, stage_errs = _emit_stage(prefix, i, stage)
        blocks.extend(nodes)
        errs.extend(stage_errs)
    last = f"{prefix}_n{len(stages)}"
    # jq drops JSON null from the collected array, so an absent key and an
    # explicit null both resolve to "no node". Intermediate nulls are NOT
    # dropped -- jq propagates them through further field hops, and so do the
    # stage rules above.
    blocks.append(f"{prefix}_vals := [v |\n\tsome i\n\tv := {last}[i]\n\tnot is_null(v)\n]")
    # `_err` is ALWAYS a partial set, never the `:= set()` complete form: a
    # complete rule and a `contains` rule of the same name are a compile-time
    # conflict, and a path with no raising stage (`$` alone, or only `..Field`)
    # can still gain a `contains` rule from the op guards below. The seed body
    # cannot hold, so an assert with nothing to report has an EMPTY set rather
    # than an undefined one -- undefined would be an unsafe-var error in every
    # rule that reads it.
    blocks.append(f'{prefix}_err contains reason if {{\n\tfalse\n\treason := ""\n}}')
    blocks.extend(errs)

    blocks.append(f"{prefix}_expected := {_lit(expected)}")
    required = EXPECTED_TYPE.get(op)
    if required is not None and not isinstance(expected, required[0]):
        blocks.append(
            f'{prefix}_err contains "op {op} requires {required[1]} `expected`, got '
            f'{type(expected).__name__}"'
        )
        # `_ok` is never reached (the outcome is unresolvable), but Rego needs
        # every referenced rule to exist: an undefined one is a compile-time
        # unsafe-var error, not a runtime undefined.
        blocks.append(f"default {prefix}_ok := false")
    else:
        if op in ("in", "set_eq"):
            blocks.append(f"{prefix}_flat := _flat1({prefix}_vals)")
        blocks.extend(_emit_op(prefix, op, expected))

    blocks.append(
        f'{prefix}_outcome := "unresolvable" if count({prefix}_err) > 0\n\n'
        f'{prefix}_outcome := "held" if {{\n\tcount({prefix}_err) == 0\n\t{prefix}_ok\n}}\n\n'
        f'{prefix}_outcome := "contradicted" if {{\n\tcount({prefix}_err) == 0\n'
        f"\tnot {prefix}_ok\n}}"
    )
    blocks.append(
        f'{prefix}_line := "  PASS [{name}]" if {prefix}_outcome == "held"\n\n'
        f'{prefix}_line := sprintf("  FAIL [%s]: op=%s expected=%s resolved=%s", '
        f"[{_lit(name)}, {_lit(op)}, json.marshal({prefix}_expected), "
        f'json.marshal({prefix}_vals)]) if {prefix}_outcome == "contradicted"\n\n'
        f'{prefix}_line := sprintf("  FAIL [%s]: %s (UNRESOLVABLE, not contradicted)", '
        f'[{_lit(name)}, concat("; ", {prefix}_err)]) if {prefix}_outcome == "unresolvable"'
    )
    return "\n\n".join(blocks)


HEADER = """\
# Generated -- generator/gen.py, from the spec YAML by
# generator/jsonpath_rego.py. Do not hand-edit; regenerate the owning scenario.
#
# One assert source, one policy language: the same oracle.structural_asserts
# entries the jq backend compiles to tests/_assert_lib.sh calls are compiled
# here to Rego, with jq's three-valued outcome preserved -- `held`,
# `contradicted` and `unresolvable` are disjoint and exhaustive per assert, and
# `unresolvable` is reached only through the explicit `_err` rules that name a
# situation jq raises on (a field access into a scalar, iterating a
# non-collection, `|fromjson` over a non-string, over invalid JSON or over an
# unpaired surrogate escape, an unknown op). Without those rules Rego's silent
# undefined would report them as "no node resolved", a vacuous pass.
#
# `resolved` and `reasons` are for ad-hoc `opa eval` of this file by hand; the
# verifier reads `render` and the parity gate reads the three verdict sets.
#
# `render` is what tests/static_tiers.sh evaluates: TIER0_PASS=<0|1> on the
# FIRST line, then one log line per assert. The verdict leads because the log
# lines quote resolved artifact values, and a value reading "TIER0_PASS=1"
# would spoof a substring search for it. Op semantics: specs/SCHEMA.md §4.2.
"""


def build_tier0_rego(pkg: str, asserts: list[tuple[str, str, str, object]]) -> str:
    """The whole tests/tier0.rego for one arm.

    `asserts` is (name, jsonpath, op, expected) in spec order, already filtered
    to this arm's tier-"0" entries (and, for a multi-step task, to the step's
    own projection of them)."""
    slugs = {}
    for name, *_ in asserts:
        slug = _slug(name)
        if slug in slugs:
            raise ValueError(
                f"jsonpath_rego: assert names {slugs[slug]!r} and {name!r} both "
                f"compile to the Rego identifier {slug!r} -- rename one"
            )
        slugs[slug] = name

    parts = [HEADER.rstrip("\n"), f"package cdktn_bench.{pkg}.tier0", "import rego.v1", _HELPERS.rstrip("\n")]
    for name, jsonpath, op, expected in asserts:
        parts.append(compile_assert(name, jsonpath, op, expected))

    if not asserts:
        parts.append(
            "# This arm runs no tier-0 assert, so every verdict set is empty by\n"
            "# construction rather than by an absent rule.\n"
            "held := set()\n\n"
            "contradicted := set()\n\n"
            "unresolvable := set()\n\n"
            "resolved := {}\n\n"
            "reasons := {}\n\n"
            "lines := []"
        )
    else:
        agg: list[str] = []
        for name, *_ in asserts:
            prefix = f"a_{_slug(name)}"
            agg.append(
                f'held contains {_lit(name)} if {prefix}_outcome == "held"\n\n'
                f'contradicted contains {_lit(name)} if {prefix}_outcome == "contradicted"\n\n'
                f'unresolvable contains {_lit(name)} if {prefix}_outcome == "unresolvable"\n\n'
                f"resolved[{_lit(name)}] := {prefix}_vals\n\n"
                f'reasons[{_lit(name)}] := concat("; ", {prefix}_err)'
            )
        parts.extend(agg)
        line_refs = ",\n\t".join(f"a_{_slug(name)}_line" for name, *_ in asserts)
        parts.append(f"lines := [\n\t{line_refs},\n]")

    parts.append(
        "# tier0_pass is derived the way the jq backend derives it: every assert\n"
        "# held, nothing contradicted and nothing unresolvable. `default 0` is what\n"
        "# makes a missing or conflicting outcome fail closed.\n"
        "default tier0_pass := 0\n\n"
        "tier0_pass := 1 if {\n"
        f"\tcount(held) == {len(asserts)}\n"
        "\tcount(contradicted) == 0\n"
        "\tcount(unresolvable) == 0\n"
        "}"
    )
    parts.append(
        'render := concat("\\n", array.concat('
        '[sprintf("TIER0_PASS=%d", [tier0_pass])], lines))'
    )
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# the same semantics in Python
# ---------------------------------------------------------------------------
#
# What the emitted rules above are supposed to compute, written once more as a
# plain function. It exists so the three implementations in
# oracles/tests/test_op_parity.py can be compared cell by cell: jsonpath-ng
# (oracles/lib/structural.py::resolve) is a real JSONPath engine and answers
# "no match" where jq RAISES, so it cannot express the unresolvable class on
# its own and cannot stand in for this.


class Unresolvable(ValueError):
    """The path could not be resolved at all -- assert_check's rc 2.

    Never a verdict about the artifact: a field access into a scalar, an
    iteration over a non-collection, `|fromjson` over a non-string or over a
    string that is not JSON. jq raises on each; Rego needs the explicit rules
    above to say the same thing.
    """


def resolve_nodes(document: object, path: str) -> list:
    """The node list an assert resolves to, with jq's raise conditions.

    JSON `null` is dropped from the RESULT only: nulls flow through
    intermediate stages exactly as jq propagates them through further field
    hops.
    """
    nodes: list = [document]
    for stage in parse_jsonpath(path):
        nodes = _resolve_stage(stage, nodes)
    return [v for v in nodes if v is not None]


def _resolve_field(node: object, name: str) -> object:
    if isinstance(node, dict):
        return node.get(name)
    if node is None:
        return None
    raise Unresolvable(f"field access .{name} on a {_type_name(node)} node")


def _resolve_elems(node: object, what: str) -> list:
    if isinstance(node, list):
        return list(node)
    if isinstance(node, dict):
        return list(node.values())
    raise Unresolvable(f"{what} cannot iterate over a {_type_name(node)} node")


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    return {
        bool: "boolean", int: "number", float: "number", str: "string",
        list: "array", dict: "object",
    }[type(value)]


def _cond_holds(element: object, cond: FieldCond | ValueCond) -> bool:
    if isinstance(cond, ValueCond):
        return element == cond.literal
    target: object = element
    for hop in cond.chain:
        target = _resolve_field(target, hop)
    return target == cond.literal


# jq's decoder rejects a \uD800-\uDBFF escape that no low surrogate follows;
# Python's json accepts it and Go's substitutes U+FFFD, so answering here would
# tell a spec author the assert HOLDS where both graders refuse to grade.
_UNPAIRED_HIGH_SURROGATE = re.compile(
    r"\\u[dD][89abAB][0-9a-fA-F]{2}(?!\\u[dD][c-fC-F][0-9a-fA-F]{2})"
)


def _resolve_stage(stage: Stage, nodes: list) -> list:
    out: list = []
    for node in nodes:
        if isinstance(stage, Field):
            out.append(_resolve_field(node, stage.name))
        elif isinstance(stage, Wildcard):
            out.extend(_resolve_elems(node, "[*]"))
        elif isinstance(stage, Descend):
            out.extend(
                sub.get(stage.name) for sub in _subterms(node) if isinstance(sub, dict)
            )
        elif isinstance(stage, FromJson):
            if not isinstance(node, str):
                raise Unresolvable(
                    f"|fromjson on a {_type_name(node)} node -- only strings can be parsed"
                )
            if _UNPAIRED_HIGH_SURROGATE.search(node):
                raise Unresolvable(
                    "|fromjson on a string with an unpaired high-surrogate escape"
                )
            try:
                out.append(json.loads(node))
            except ValueError as exc:
                raise Unresolvable(
                    "|fromjson on a string that is not valid JSON"
                ) from exc
        elif isinstance(stage, Filter):
            for element in _resolve_elems(node, "[?(...)]"):
                # jq's `or` short-circuits, so a later condition never indexes
                # an element an earlier one already matched.
                if any(_cond_holds(element, c) for c in stage.conds):
                    out.append(element)
        else:
            raise AssertionError(f"unhandled stage {stage!r}")
    return out


def _subterms(node: object) -> list:
    """Every subterm of `node`, itself included -- jq's `..`."""
    found = [node]
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_subterms(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_subterms(value))
    return found
