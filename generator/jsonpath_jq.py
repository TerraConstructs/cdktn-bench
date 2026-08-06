"""Translate the narrow JSONPath subset used in oracle.structural_asserts
(SCHEMA.md §4.2) into an equivalent `jq` filter, at *generation* time.

Why this exists: the generated tests/static_tiers.sh runs inside an arm's
agent container, and the only JSON-query tool guaranteed present in all three
arm images is `jq` (DECISIONS.md Amendment 3 "Agent-container baseline
contract" — bash/git/curl/jq/unzip/AWS CLI v2 in every arm image; no Python,
no jsonpath-ng). So `cfn_jsonpath`/`tf_jsonpath` strings are compiled to jq
once, here, on the host, and the resulting jq filter text is baked verbatim
into the generated shell script — no JSONPath evaluation ever happens at
trial run time.

Supported grammar (SCHEMA.md §4.2's examples, plus two extensions added to
close a gap the taxonomy actually needs -- see below):

    $                               -> root
    .Field                          -> field access
    ..Field                         -> recursive descent to every Field key
                                       at any depth (jq `.. | objects | .Field?`)
    [?(@.F=='V')]                   -> filter, single equality condition
    [?(@.F=='V' || @.F=='V2')]      -> filter, OR'd equality conditions
    [?(@=='V')]                     -> filter, bare VALUE equality (no
                                       field -- the current element itself
                                       must equal 'V'; jq `select(.=="V")`)
    [*]                             -> wildcard / iterate-all

Anything else raises ValueError with the offending remainder — a scenario
author who needs richer JSONPath should widen this translator deliberately,
not have it silently mis-translate.

Why `..Field` and bare-value `[?(@=='V')]` were added: the sfn-jsonata
mode-mixing catch (SCHEMA.md §4.4/DECISIONS.md Amendment №1) needs to find
JSONPath-mode artifacts (`ResultPath`/`Parameters`/`ItemsPath`) ANYWHERE
inside a JSONata-mode state machine, at unknown depth -- `..Field` is the
only way to express that. And a wildcard-Resource-not-allowed check (a real
member of the "scoped, not broader" catch family --
policy-resource-scoped-not-wildcard is the worked example, see its entry in
specs/_toy/toy-ssm-parameter.yaml) needs to test each individual resolved
value against the literal `"*"`, not just "does this path exist at all" --
that needs a bare-value filter predicate, not a field-keyed one.
"""

from __future__ import annotations

import json
import re

_FIELD_RE = re.compile(r"^\.([A-Za-z0-9_]+)")
_RECURSIVE_FIELD_RE = re.compile(r"^\.\.([A-Za-z0-9_]+)")
_FILTER_RE = re.compile(r"^\[\?\(([^\]]*)\)\]")
_WILDCARD_RE = re.compile(r"^\[\*\]")
_FIELD_COND_RE = re.compile(r"^@\.([A-Za-z0-9_]+)\s*==\s*'([^']*)'$")
_VALUE_COND_RE = re.compile(r"^@\s*==\s*'([^']*)'$")


def _jq_string_literal(value: str) -> str:
    return json.dumps(value)


def _translate_filter(inner: str) -> str:
    conds = [c.strip() for c in inner.split("||")]
    jq_conds = []
    for cond in conds:
        m = _FIELD_COND_RE.match(cond)
        if m:
            field, literal = m.group(1), m.group(2)
            jq_conds.append(f".{field}=={_jq_string_literal(literal)}")
            continue
        m = _VALUE_COND_RE.match(cond)
        if m:
            literal = m.group(1)
            jq_conds.append(f".=={_jq_string_literal(literal)}")
            continue
        raise ValueError(
            f"jsonpath_jq: unsupported filter condition {cond!r} "
            "(only \"@.Field=='literal'\" or bare \"@=='literal'\", "
            "combined with '||', is supported)"
        )
    return " or ".join(jq_conds)


FROMJSON_SEP = "|fromjson"


def jsonpath_to_jq(path: str) -> str:
    """Compile one cfn_jsonpath/tf_jsonpath string into a jq filter body
    (no surrounding `[ ]` collection wrapper — the caller adds that, since
    whether to collect-as-array is the caller's concern, not the
    translation's).

    Supports one or more `|fromjson` markers splitting the path into
    segments -- e.g. `$.values.container_definitions|fromjson[*].linuxParameters.swappiness`
    -- for the case where a Terraform plan JSON attribute (or a CFN
    `Fn::Join`-flattened `DefinitionString`) stores its own value as a JSON
    *string* rather than nested structure (`jsonencode(...)`-style
    attributes: `container_definitions`, `assume_role_policy`, `policy`, an
    ASL `Definition`, ...). Without this, a path like
    `values.container_definitions[*].linuxParameters.swappiness` resolves
    against the raw undecoded string and finds nothing -- silently missing
    exactly the taxonomy's nested-attribute catches that plan JSON is
    documented (specs/SCHEMA.md §4.2) to reach "the same as CFN does". Each
    `|fromjson` compiles to a literal jq `fromjson` filter applied to
    whatever the preceding segment resolved to."""
    segments = path.split(FROMJSON_SEP)
    compiled_segments = [_compile_fragment(segments[0], require_dollar=True)]
    for seg in segments[1:]:
        compiled_segments.append(_compile_fragment(seg, require_dollar=False))
    return " | fromjson | ".join(compiled_segments)


def _compile_fragment(path: str, *, require_dollar: bool) -> str:
    if require_dollar:
        if not path.startswith("$"):
            raise ValueError(f"jsonpath_jq: expected a JSONPath starting with '$', got {path!r}")
        rest = path[1:]
    else:
        rest = path
    stages: list[str] = []
    field_buf = ""

    def flush_fields():
        nonlocal field_buf
        if field_buf:
            stages.append(field_buf)
            field_buf = ""

    while rest:
        m = _RECURSIVE_FIELD_RE.match(rest)
        if m:
            # Checked BEFORE _FIELD_RE: matched first so `..Field` never
            # falls through to the plain single-dot field-access branch
            # (it can't accidentally match there anyway -- _FIELD_RE
            # requires an alnum/underscore right after its one leading '.',
            # and here that position holds the second '.' -- but checking
            # recursive descent first keeps that non-overlap explicit
            # rather than incidental).
            flush_fields()
            stages.append(f".. | objects | .{m.group(1)}?")
            rest = rest[m.end():]
            continue
        m = _FIELD_RE.match(rest)
        if m:
            field_buf += f".{m.group(1)}"
            rest = rest[m.end():]
            continue
        m = _FILTER_RE.match(rest)
        if m:
            flush_fields()
            cond = _translate_filter(m.group(1))
            stages.append(f".[] | select({cond})")
            rest = rest[m.end():]
            continue
        m = _WILDCARD_RE.match(rest)
        if m:
            flush_fields()
            stages.append(".[]")
            rest = rest[m.end():]
            continue
        raise ValueError(
            f"jsonpath_jq: cannot parse remainder {rest!r} of path {path!r} "
            "— unsupported JSONPath segment for this translator"
        )
    flush_fields()

    if not stages:
        return "."
    return " | ".join(stages)


if __name__ == "__main__":
    import sys

    examples = [
        "$.Resources[?(@.Type=='AWS::SSM::Parameter')]",
        "$.Resources[?(@.Type=='AWS::SSM::Parameter')].Properties.Name",
        "$.planned_values.root_module.resources[?(@.type=='aws_ssm_parameter')].values.name",
        "$.Resources[?(@.Type=='AWS::IAM::Role')].Properties.AssumeRolePolicyDocument.Statement[*].Principal.Service",
        "$.Resources[?(@.Type=='AWS::IAM::Policy' || @.Type=='AWS::IAM::Role')].Properties.Policies[*].PolicyDocument.Statement[*].Resource",
    ]
    paths = sys.argv[1:] or examples
    for p in paths:
        print(f"{p}\n  -> {jsonpath_to_jq(p)}\n")
