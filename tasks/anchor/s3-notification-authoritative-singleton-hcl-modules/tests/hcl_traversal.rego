# SHARED tier-1 Rego library -- HAND-AUTHORED, generator-copied, never a stub.
#
#   canonical home:  oracles/rego/lib/hcl_traversal.rego
#   copied to:       tasks/<task>/tests/hcl_traversal.rego
#                    (generator/gen.py::write_tests_dir, for every arm whose
#                     spec sets `oracle.hcl_traversal: true`)
#   loaded as:       opa eval -d policy.rego -d hcl_traversal.rego ...
#
# WHAT THIS IS FOR.
# `terraform show -json` does not emit `locals`. A plan's
# `.configuration...references` list therefore dead-ends on `local.x`: the
# document says the argument was set to that symbol and says nothing at all
# about what the symbol holds. Two proven oracle defects came out of that
# single fact (docs/design/conftest-hcl-traversal-spike.md sect 1): a false
# PASS (an ARN of the WRONG resource laundered through a local) and a false
# FAIL (a correct DRY hoist the oracle could not follow). Both are defects of
# reasoning about SYMBOLS because the referent is out of reach.
#
# The harness now parses the agent's own `.tf` files with `hcl2json` and
# merges the result into the oracle input under ONE reserved key, `_hcl`
# (generator/gen.py::build_static_tiers_sh). This library turns that into a
# resolver: given a symbol, what single resource attribute does it name?
#
# THE THREE-VALUED CONTRACT, which is binding on every caller:
#
#     resolved     -- exactly ONE canonical referent traversal
#     ambiguous    -- N>1 candidate referents, none selected statically
#     unresolvable -- 0 candidates / opaque / literal / container / missing /
#                     cyclic / a chain that never reaches a concrete reference
#
# AMBIGUOUS and UNRESOLVABLE both DENY, with a message naming the symbol and
# quoting what stood in the way. There is no fourth bucket and there is no
# silent outcome in either direction.
#
# ------------------------------------------------------------------------
# WHY THIS FILE IS SHAPED THE WAY IT IS -- three executed defects
# ------------------------------------------------------------------------
# The prototype this library replaces failed its own safety contract three
# times under adversarial verification (spike memo sect 5.7/5.8/5.9): a
# missing arity gate on ONE of two twin slots (silent PASS); a `verdict` that
# went UNDEFINED past the resolver's hand-unrolled 4-hop ceiling (silent
# PASS); and a dot-joined rule key that raised `eval_conflict_error` and
# ABORTED the whole evaluation, scoring a CORRECT solution 0.0 with no deny
# message at all (silent FAIL). Three structural rules follow, and every one
# of them is load-bearing in the code below:
#
# 1. THE ARITY GATE LIVES HERE, NOT AT THE CALL SITE. `slot()` is TOTAL: it
#    returns an explicit verdict for the 0-reference and N>1-reference cases
#    instead of going undefined, so a calling rule physically cannot forget
#    to gate its slot. The prototype shipped the gate on slot 1 and omitted
#    it on slot 2 -- twin rules twenty lines apart, and review missed it.
#
# 2. CLASSIFICATION IS CARRIED BY `else` CHAINS, NOT BY AN ENUMERATION I
#    BELIEVE IS EXHAUSTIVE. Every classifier below is one function with an
#    ordered `else` chain ending in an unconditional catch-all. An `else`
#    chain is ordered and mutually exclusive BY CONSTRUCTION: the first
#    matching clause wins and no later clause is even evaluated. That buys
#    two things a bare `default` does not. It cannot go undefined (the final
#    `else` has no body), AND two clauses can never both fire with different
#    values -- which is the `eval_conflict_error` shape defect 3 was.
#
# 3. EVERY KEY IS INJECTIVE BY CONSTRUCTION, AND NO RULE THAT DATA CAN KEY
#    IS AN OBJECT RULE. This is the important one and it is worth stating
#    precisely, because a Rego `default` clause does NOT protect against it.
#
#    *** RETRACTION, carried here from the spike memo so it cannot be lost:
#    a `default` clause guarantees a rule is DEFINED for every argument. It
#    guarantees NOTHING if a rule that rule DEPENDS ON raises a RUNTIME
#    ERROR. Evaluation aborts before any clause -- `default` included -- can
#    apply, `opa eval` writes nothing to stdout, and the harness gate
#    (`opa eval ... | jq -e 'length == 0'`) sees empty stdin, exits 4, and
#    scores tier-1 FAIL. "Total by construction" is true only AGAINST
#    UNDEFINEDNESS, and only PROVIDED EVALUATION COMPLETES. ***
#
#    The executed counterexample was three lines of valid HCL:
#
#        locals { t = { "a.b" = aws_s3_bucket.media.arn,
#                       a = { b = aws_sns_topic.audit.arn } } }
#
#    HCL map keys are arbitrary strings, so a key may itself contain a dot.
#    The prototype keyed its flattened locals table by dot-joining the walk
#    path (`concat(".", array.concat(["local"], path))`), and that mapping is
#    NOT INJECTIVE: paths ["t","a.b"] and ["t","a","b"] join to the same
#    string. An object rule binding one key to two DIFFERENT values raises
#    `eval_conflict_error`. Reward 0.0, on a fully correct solution, with no
#    message naming what went wrong -- strictly worse than a false deny.
#
#    The fix here is not "handle dotted keys". It is that `node` is a SET of
#    `[path, value]` PAIRS keyed by the path ARRAY (see `node` below). A set
#    cannot conflict: two distinct paths are two distinct elements, and two
#    bindings of the SAME path with different values are two elements too,
#    which `node_values()` then reports as N>1 -> AMBIGUOUS -> DENY. Every
#    other collection in this file that data can key is likewise a set or a
#    set-comprehension. `ref_graph` is the one object comprehension, and its
#    keys are drawn from a set with a value functionally determined by the
#    key, so it cannot conflict either.
#
#    Consequently this library does not merge the per-file `locals` blocks
#    into one object at all -- a merge is exactly where a collision would
#    have to be resolved, and there is no resolution that is not a guess.
#
# 4. A CHAIN IS WALKED WITH `graph.reachable`, NEVER WITH UNROLLED HOPS.
#    Rego forbids recursive rules, and a hand-unrolled walk has a CLIFF: at
#    hop N+1 every clause fails, the verdict goes undefined, and in a
#    fail-closed design an undefined verdict is a SILENT PASS, not a loud
#    fail. `graph.reachable` is a non-recursive builtin with no depth limit
#    that terminates on cycles by construction.
#
# ------------------------------------------------------------------------
# WHAT THIS LIBRARY DOES NOT DO, stated so a caller does not assume it
# ------------------------------------------------------------------------
# * It does not EVALUATE expressions. `format(...)`, `merge(...)`, a
#   conditional, a comprehension and a `jsonencode(...)` body are all
#   refused, never guessed at. That refusal is the whole point: the oracle
#   says "I cannot tell" out loud instead of guessing, which is what
#   produced both original defects.
# * It does not resolve `var.*`. A locals resolver has no business claiming
#   to know an input variable's value.
# * It does not cross MODULE boundaries. `module.x.out` is UNRESOLVABLE.
#   A `hcl-modules` arm would need a second resolver on top of this one.
# * It handles the TWO `count`/`for_each` index spellings on the REFERENT
#   DIFFERENTLY, and the difference is worth stating precisely because the
#   text that stood here until round 15 got it wrong in the direction that
#   hid a silent PASS.
#
#   *** RETRACTION. This list used to say, flatly, that an index on the
#   referent "tokenizes to no parse -> UNRESOLVABLE -> DENY", i.e. that the
#   whole family was refused and therefore LOUD. That was true only of the
#   NUMERIC spelling. `aws_s3_bucket.b["media"].arn` PARSES -- the tokenizer
#   accepts the quoted-index form deliberately -- and, under the old
#   `instance_of` (first two segments), every key of one `for_each` block
#   collapsed to ONE instance. A Lambda permission scoped to the DECOY key
#   of a two-key `for_each` scored REWARD 1.0, executed. Not loud: silent,
#   and reached by an ordinary valid Terraform spelling. ***
#
#   As of round 15:
#     - `aws_s3_bucket.b["media"].arn` -- QUOTED key: parses, and
#       `instance_of` carries the key, so `b["media"]` and `b["decoy"]` are
#       DIFFERENT instances. Graded, not collapsed.
#     - `aws_s3_bucket.b[0].arn` -- NUMERIC index: still tokenizes to no
#       parse -> UNRESOLVABLE -> DENY on a solution that may well be
#       correct. THAT is the live, known FALSE-FAIL, and it is loud: the
#       deny names the reference it could not tokenize. It is narrower than
#       the sentence it replaces, and it is the only half of the family that
#       is still open.
# * It does not GLOB. The harness decides which files land under `_hcl`
#   (`*.tf` through hcl2json, `*.tf.json` loaded raw); this library only
#   ever sees whatever it was handed. It DOES normalise the two `locals`
#   spellings those two routes produce -- see `locals_blocks` below, and the
#   executed false-FAIL that made that necessary.
package cdktn_bench.hcl

import rego.v1

# ---------------------------------------------------------------------------
# input surface
# ---------------------------------------------------------------------------
#
# `input._hcl` is `{"<filename>": <hcl2json document>, ...}` -- one entry per
# `.tf`/`.tf.json` file the harness globbed, ALWAYS present (possibly empty)
# on an arm whose generated static_tiers.sh does the merge, and ALWAYS ABSENT
# on an arm that does not. Both states are meaningful and neither is a crash:
#
#   absent  -> this arm feeds the policy plan JSON only (terraconstructs
#              synthesizes cdk.tf.json and emits no `locals` at all, so its
#              references are already direct). `local.*` is then UNRESOLVABLE,
#              which is the correct fail-closed answer, not an accident.
#   present -> the merge ran. An EMPTY object means the glob matched nothing,
#              which `no_source_supplied` reports so a policy can deny rather
#              than fail open. This matters: a Rego builtin that cannot find
#              a file is UNDEFINED, not an error, so a policy that merely
#              looks and moves on fails OPEN.
hcl_docs := d if {
	d := object.get(input, "_hcl", {})
	is_object(d)
} else := {}

hcl_supplied if is_object(object.get(input, "_hcl", null))

# TRUE iff the harness ran the merge and it produced nothing to read. A
# calling policy should deny on this outright: with no source, every symbol
# is unresolvable and the oracle is guessing.
no_source_supplied if {
	hcl_supplied
	count(hcl_docs) == 0
}

# ---------------------------------------------------------------------------
# the locals table, flattened -- CONFLICT-FREE BY CONSTRUCTION
# ---------------------------------------------------------------------------

# TERRAFORM SPELLS `locals` TWO WAYS AND THIS LIBRARY READS BOTH.
#
#   hcl2json, over a native-HCL `.tf`, emits ONE ENTRY PER `locals { ... }`
#   BLOCK, as a LIST of objects:      "locals": [ {"a": "..."} , {...} ]
#
#   terraform's own JSON SYNTAX (`main.tf.json`, which the harness loads RAW
#   -- there is nothing for hcl2json to do to a file that is already JSON)
#   writes an OBJECT of name -> value:  "locals": {"a": "..."}
#   ...and ALSO accepts the list-of-objects spelling.
#
# *** EXECUTED DEFECT, fixed here (round 14): reading only the LIST spelling
# made `some blk in <object>` iterate the local VALUES (strings), every one
# of which failed `is_object`, so EVERY local in an object-spelled
# `main.tf.json` was silently dropped. A FULLY CORRECT solution written in
# terraform's native JSON syntax scored 0.0, denied with the message "no
# `locals` block in any supplied .tf file defines local.arns.media_bucket"
# -- about a supplied file that plainly did define it, and which the merge
# log listed under `_hcl`. That is a deny message the graded artifact
# directly contradicts (DECISIONS.md Amendment 29 sect 6 RULING 3), which is
# worse than the miss itself, and it made acceptance silently depend on
# which of two equally valid spellings the agent chose. ***
#
# Both clauses below are POSITIVE and mutually exclusive by shape (`is_array`
# vs `is_object` on the same value), so this is a set union of two disjoint
# readings, never a guess about which one was meant.
locals_blocks contains blk if {
	some _, doc in hcl_docs
	is_object(doc)
	l := object.get(doc, "locals", [])
	is_array(l)
	some blk in l
	is_object(blk)
}

locals_blocks contains blk if {
	some _, doc in hcl_docs
	is_object(doc)
	blk := object.get(doc, "locals", [])
	is_object(blk)
}

# EVERY node of EVERY `locals` block, at any nesting depth, as a SET of
# [path, value] pairs. `walk` yields each path exactly once per block and the
# path is an ARRAY of segments -- never dot-joined, never flattened into a
# string a data-dependent value could collide in (see rule 3 in the header).
#
# Intermediate containers are deliberately included: `local.arns` is a real
# symbol an agent can write, and it must land in UNRESOLVABLE ("names a
# container, not a single value"), not fall off the edge of the table.
#
# `every seg in path { is_string(seg) }` drops paths that descend through a
# LIST (whose segments are integers). A list-valued local is a container and
# resolves to nothing either way; this only keeps the path space to arrays of
# strings, which is what makes `json.marshal` injective over it.
node contains [path, value] if {
	some blk in locals_blocks
	walk(blk, [path, value])
	count(path) > 0
	every seg in path {
		is_string(seg)
	}
}

# TOTAL: a set, possibly empty, never undefined.
#   0 values -> no `locals` block defines this path
#   1 value  -> the ordinary case
#   N values -> the SAME path defined more than once, with differing values,
#               across two `locals` blocks or two files. Reported as
#               AMBIGUOUS rather than silently picking one.
node_values(path) := {v |
	some [p, v] in node
	p == path
}

node_keys := {json.marshal(p) |
	some [p, _] in node
}

# ---------------------------------------------------------------------------
# resource blocks -- read for the two things a plan does NOT carry
# ---------------------------------------------------------------------------
#
# Normalised over the same two spellings `locals_blocks` normalises, and for
# the same reason: hcl2json emits `resource.<type>.<name>` as a LIST of
# blocks, terraform's own JSON syntax as a single OBJECT. Both clauses are
# positive and discriminated by shape (`is_array` vs `is_object`), so this is
# a union of two disjoint readings and never a guess about which was meant.
resource_blocks contains [rtype, rname, blk] if {
	some _, doc in hcl_docs
	is_object(doc)
	some rtype, byname in object.get(doc, "resource", {})
	is_object(byname)
	some rname, blks in byname
	is_array(blks)
	some blk in blks
	is_object(blk)
}

resource_blocks contains [rtype, rname, blk] if {
	some _, doc in hcl_docs
	is_object(doc)
	some rtype, byname in object.get(doc, "resource", {})
	is_object(byname)
	some rname, blk in byname
	is_object(blk)
}

# `data "<dtype>" "<dname>" { ... }`, the SAME two spellings, for the same
# reason: hcl2json emits a LIST of blocks, terraform's own JSON syntax
# accepts an OBJECT. Added round 17 so a policy can read a
# `data "aws_iam_policy_document"` from the .tf SOURCE instead of from the
# plan's `expressions`: the plan reports a `condition`'s `values` as a FLAT
# `.references` list with every LITERAL DROPPED, so
# `values = [local.x, "arn:aws:s3:::*"]` and `values = [local.x]` are
# indistinguishable there -- an executed REWARD-1.0 launder. The parsed
# source still has both values.
data_blocks contains [dtype, dname, blk] if {
	some _, doc in hcl_docs
	is_object(doc)
	some dtype, byname in object.get(doc, "data", {})
	is_object(byname)
	some dname, blks in byname
	is_array(blks)
	some blk in blks
	is_object(blk)
}

data_blocks contains [dtype, dname, blk] if {
	some _, doc in hcl_docs
	is_object(doc)
	some dtype, byname in object.get(doc, "data", {})
	is_object(byname)
	some dname, blk in byname
	is_object(blk)
}

# The RAW source value(s) of one resource-block argument, as a SET, so a deny
# message can QUOTE the shape it could not read instead of asserting a
# diagnosis of it (Amendment 29 RULING 3).
resource_attr_values(rtype, rname, attr) := {v |
	some [t, n, blk] in resource_blocks
	t == rtype
	n == rname
	v := object.get(blk, attr, null)
	v != null
}

# `for_each = aws_s3_bucket.b` -- the resource a block's `for_each` argument
# expands over, and ONLY when the argument is EXACTLY one whole-resource
# reference and nothing else.
#
# WHY SO NARROW, deliberately. `each.value` denotes an INSTANCE of whatever
# `for_each` iterates, so reading it requires knowing that the iteration is
# over the resource itself with the resource's own instance keys. That is
# true for `for_each = aws_s3_bucket.b` and NOT knowable for
# `for_each = toset([...])` (values are strings, `each.value.arn` is not even
# valid), `for_each = { for k, v in ... }` (the comprehension can re-key
# arbitrarily) or a `merge()`/conditional. Every one of those fails the
# `count(segs) == 2` test below and is refused, which leaves `each.value`
# UNRESOLVABLE and therefore LOUD -- the narrow form is an ACCEPTANCE, never
# a widening.
#
# `count(refs) == 1` is the same arity gate `slot()` carries: a block
# declared twice across two files with two different `for_each` arguments
# resolves to nothing rather than to whichever happened to be picked.
for_each_referent(rtype, rname) := ref if {
	refs := {b |
		some [t, n, blk] in resource_blocks
		t == rtype
		n == rname
		b := interp_body(object.get(blk, "for_each", null))
	}
	count(refs) == 1
	some ref in refs
	segs := parse_traversal(ref)
	count(segs) == 2
	not segs[0] in {"local", "var", "data", "module", "count", "each", "self", "path", "terraform"}
}

# ---------------------------------------------------------------------------
# `#jsonencode` -- POSITION recovered from an opaque policy-document argument
# ---------------------------------------------------------------------------
#
# *** THE EXECUTED REWARD-1.0 LAUNDER THIS EXISTS FOR (round 16).
# `policy = jsonencode({...})` is ONE opaque expression. `terraform show
# -json` reports a FLAT union of every reference anywhere inside it with NO
# position, so a policy rule could only ask "does this document MENTION the
# bucket somewhere". A checked-in 0.0 fixture whose topic policy grants
# `s3.amazonaws.com` `sns:Publish` with NO `aws:SourceArn` condition at all
# was laundered to REWARD 1.0 by ONE cosmetic line -- a bucket reference
# interpolated into the statement's `Sid` string. ***
#
# The harness (generator/gen.py::build_hcl_merge_block) re-parses every
# `${jsonencode(<body>)}` argument by running THE SAME hcl2json over
# `locals { v = <body> }`, and stores the result under the reserved key
# `#jsonencode` on the file's own parsed document, as a list of
# `{"path": [...], "doc": ...}` entries. `#` cannot occur in an HCL
# identifier, so the key can never collide with a block type hcl2json emits,
# and `locals_blocks` reads `doc["locals"]` only and never sees it.
#
# Every leaf of `doc` is still the raw `"${...}"` source, so `interp_body` +
# `resolve` read it exactly as they read any other expression. NOTHING is
# evaluated here either.
#
# *** RETRACTION (round 17). THIS COMMENT USED TO CLAIM: "A body the harness
# could not re-parse (`jsonencode(local.doc)`, `jsonencode(x ? a : b)`)
# contributes NO entry, so a caller finds no document and must DENY naming
# the shape -- fail-closed, and loud." THAT IS FALSE, AND IT WAS FALSE FOR
# THE HEADLINE EXAMPLE. `locals { v = local.doc }` re-parses PERFECTLY: the
# harness gets back the STRING "${local.doc}" and stores it as an entry.
# What is NOT re-parsable is a body that is not valid HCL at all, which is
# nearly nothing. So this rule DOES contribute an entry for
# `jsonencode(local.doc)` -- a NON-OBJECT one.
#
# CALLERS MUST THEREFORE GUARD ON THE RECOVERED BODY'S SHAPE THEMSELVES
# (`is_object(doc)` for a policy document). One that did not was executed at
# REWARD 0.0 on a CORRECT, DRY solution: the string entry made
# "unreadable document" false, the loud deny never fired, and the document
# was graded as having zero statements. The same false claim was repeated in
# specs/SCHEMA.md and in the spike memo and is retracted in both.
jsonencode_docs contains [path, doc] if {
	some _, d in hcl_docs
	is_object(d)
	some e in object.get(d, "#jsonencode", [])
	path := e.path
	doc := e.doc
}

# The re-parsed body of `resource "<rtype>" "<rname>" { <attr> = jsonencode(...) }`.
# A SET (never an object rule keyed by data): two files could declare the same
# block, and a set reports that as two candidates rather than raising
# eval_conflict_error. hcl2json's path for that argument is exactly
# ["resource", <rtype>, <rname>, <block index>, <attr>].
resource_jsonencode(rtype, rname, attr) := {doc |
	some [path, doc] in jsonencode_docs
	count(path) == 5
	path[0] == "resource"
	path[1] == rtype
	path[2] == rname
	path[4] == attr
}

# ---------------------------------------------------------------------------
# the tokenizer
# ---------------------------------------------------------------------------
#
# hcl2json hands a policy the raw SOURCE of any expression it could not
# reduce to a literal, re-wrapped as "${...}". There is no static traversal
# analysis in that output (spike memo sect 2 -- this is the finding that
# refutes the original hypothesis), so a traversal has to be tokenized here.
#
# `parse_traversal` matches identifier segments and quoted-index segments and
# REQUIRES THE MATCHES TO TILE THE INPUT EXACTLY (their lengths must sum to
# the length of the input). Anything it cannot tile -- an operator, a call, a
# space, an escaped quote, a numeric index, a splat, a second interpolation
# -- yields NO PARSE, and every consumer in this file treats no-parse as
# UNRESOLVABLE. Never as "probably fine".
#
# Tiling (rather than "does it match somewhere") is what makes this sound. A
# permissive `regex.match` would happily find `aws_s3_bucket.media.arn`
# inside `format("%s/*", aws_s3_bucket.media.arn)` and report a referent that
# is NOT the value of the expression.
#
# The quoted form is required, not cosmetic: terraform emits the bracket
# spelling VERBATIM in `.references` (`local.arns["media.bucket"]`), and a
# key containing a dot is exactly the shape that made the previous
# implementation crash. Escapes are refused (`[^"\\]*`) rather than
# interpreted -- a key with a quote or a backslash in it is UNRESOLVABLE,
# which is loud, instead of mis-tokenized, which is silent.
traversal_pattern := `(?:^|\.)([A-Za-z_][A-Za-z0-9_-]*)|\["([^"\\]*)"\]`

# The raw match list, kept as its own rule because TWO things are derived
# from it and one of them needs information the segment array THROWS AWAY:
# whether a segment was written `.foo` or `["foo"]`. See `instance_of` --
# collapsing those two spellings is exactly what let a `for_each` key
# through as a silent PASS (round 15).
_parse_ms(t) := ms if {
	is_string(t)
	ms := regex.find_all_string_submatch_n(traversal_pattern, t, -1)
	count(ms) > 0
	sum([count(m[0]) | some m in ms]) == count(t)
}

# *** ROUND 16 DEFECT THIS CLOSES, executed. The body used to be the
# one-liner `parse_traversal(t) := [seg | some m in _parse_ms(t); seg :=
# _segment(m)]`. A Rego comprehension whose body is undefined evaluates to
# the EMPTY COLLECTION, not to undefined -- so `parse_traversal` returned
# `[]` for an UNTOKENIZABLE string instead of going undefined, and EVERY
# `not parse_traversal(x)` guard in this file was DEAD CODE. Executed on
# opa 1.19.0 with this library loaded alone:
#
#   hcl._unparseable(["aws_s3_bucket.media[0].arn", "not a traversal !!"])
#     -> []                                    (should be a 2-element set)
#   hcl.slot(["aws_s3_bucket.media[0].arn", "aws_s3_bucket.media[0]",
#             "aws_s3_bucket.media"])
#     -> {"kind":"resolved", "referent":"aws_s3_bucket.media", ...}
#
# i.e. the two references the tokenizer could NOT read were silently
# DROPPED by `_deepest` (`[]` is a prefix of every parse), leaving the one
# it could as a confidently-resolved lone survivor -- the exact silent
# outcome `slot()`'s unparseable clause exists to prevent. Downstream, a
# real `count = 1` plan denied with "it resolves to `aws_s3_bucket.media`,
# which names the instance but no attribute of it -- an ARN slot needs
# `.arn`" about an artifact that plainly writes `.arn`, and never quoted
# the reference it could not read (Amendment 29 RULING 3).
#
# The `segs := ...` form below binds the comprehension to a body-local
# variable AFTER `ms := _parse_ms(t)` has had to succeed, so an
# untokenizable argument makes the whole rule body fail and the function
# UNDEFINED -- which is what every `not` guard here was written against.
# `_unparseable`, `slot()`'s refusal clause and `resolve()`'s "not a
# traversal" clause are all reachable only because of this shape; the
# pinning tests for them call `hcl.slot`, not just `hcl.resolve`.
parse_traversal(t) := segs if {
	ms := _parse_ms(t)
	segs := [_segment(m) | some m in ms]
}

# Which alternative of the pattern matched. The identifier branch can never
# produce an empty group, so "the full match starts with `[`" is a sound
# discriminator even when the quoted key is itself the empty string.
_segment(m) := m[2] if {
	startswith(m[0], "[")
} else := m[1]

# NOTE (round 15): a `render(segs)` helper used to live here, to turn a
# segment array back into a traversal string for deny messages. It is
# DELETED rather than kept beside its replacement. Verdicts now carry the
# referent's own SOURCE STRING in `referent` (and `instance_addr` renders an
# instance identity as terraform's plan address), so re-deriving a string
# from the lossy segment array is never necessary -- and a round-tripper
# that cannot tell `.foo` from `["foo"]` is exactly the kind of quiet
# information loss this round exists to remove.

# ---------------------------------------------------------------------------
# expression shape
# ---------------------------------------------------------------------------
#
# hcl2json emits a literal as itself and anything else as "${<source>}".
# `interp_body` is defined ONLY for a value that is exactly one interpolation
# and nothing else -- "${x}/*" keeps its trailing text and so is refused,
# and an escaped "$${x}" is left alone by hcl2json and so never starts with
# "${" at all. This is the one genuinely favourable property of the parser's
# output and the whole resolver rests on it.
interp_body(s) := b if {
	is_string(s)
	startswith(s, "${")
	endswith(s, "}")
	count(s) >= 3
	b := substring(s, 2, count(s) - 3)
}

# ---------------------------------------------------------------------------
# the locals reference graph
# ---------------------------------------------------------------------------
#
# One node = one expression, so out-degree is at most one per DEFINITION of a
# path (a path defined twice gets two out-edges and therefore resolves to
# N>1 terminals -> AMBIGUOUS, which is the honest answer).

_local_target_path(v) := tp if {
	body := interp_body(v)
	segs := parse_traversal(body)
	segs[0] == "local"
	tp := array.slice(segs, 1, count(segs))
	count(tp) > 0
}

edge contains [from_key, to_key] if {
	some [p, v] in node
	tp := _local_target_path(v)
	from_key := json.marshal(p)
	to_key := json.marshal(tp)
	to_key in node_keys
}

# The one object comprehension in this file. Its keys come from a SET (each
# exactly once) and its value is functionally determined by the key, so no
# two bindings can disagree -- it cannot raise eval_conflict_error on any
# input. Nodes are marshalled path ARRAYS, so the graph inherits the same
# injective keying `node` has.
ref_graph := {k: ns |
	some k in node_keys
	ns := {t |
		some [f, t] in edge
		f == k
	}
}

# What ONE node's own expression points at, when that is a concrete
# (non-`local`) reference. A SET, so a path defined twice with two different
# referents yields two candidates instead of raising a conflict.
#
# ROUND 15: this yields the referent's SOURCE STRING, not its segment array.
# The segment array is lossy -- it cannot tell `.foo` from `["foo"]` -- and
# that loss is what made `aws_s3_bucket.b["media"].arn` and
# `aws_s3_bucket.b["decoy"].arn` indistinguishable downstream. Everything a
# verdict reports (`referent_path`, `instance`, `attr_path`) is now derived
# from the string at `_resolved`, where the bracket information is still
# there.
direct_referents(k) := {body |
	some [p, v] in node
	json.marshal(p) == k
	body := interp_body(v)
	parse_traversal(body)[0] != "local"
}

# Every concrete referent reachable from `path` by following `local.` hops.
# UNBOUNDED and CYCLE-SAFE: `graph.reachable` is a non-recursive builtin, so
# there is no hop ceiling to fall off, and a cycle simply contributes no
# non-`local` terminal (executed: a 3-node cycle and a self-loop both return
# the empty set without hanging). The start node is unioned in explicitly
# because `graph.reachable` returns the empty set for a node the graph does
# not contain.
chain_terminals(path) := ts if {
	k := json.marshal(path)
	reach := graph.reachable(ref_graph, {k}) | {k}
	ts := {ref |
		some n in reach
		some ref in direct_referents(n)
	}
}

# ---------------------------------------------------------------------------
# deref_local() -- what VALUE a `local.` symbol holds (round 17)
# ---------------------------------------------------------------------------
#
# `resolve()` below answers "which RESOURCE ATTRIBUTE does this symbol name",
# which is the question an ARN slot asks. A POLICY DOCUMENT asks a different
# one: `policy = jsonencode(local.topic_doc)` and `Statement = local.stmts`
# are ordinary DRY hoists whose symbol holds a STRUCTURE, not a resource
# reference, and `resolve()` correctly reports them UNRESOLVABLE. Without a
# reader for that shape a caller had only two options -- grade the string
# `"${local.topic_doc}"` as a document (which is how a CORRECT solution
# scored REWARD 0.0 with a message asserting it had zero statements), or
# deny it loudly. Neither is right when the value is sitting in the same
# parsed file.
#
# `deref_local(v)` is defined ONLY when `v` is EXACTLY one interpolation of a
# `local.` traversal AND that traversal reaches EXACTLY ONE terminal value.
# It is UNDEFINED otherwise -- for a literal, for `"${local.x}-suffix"`, for
# `var.`/`data.`/`module.` (not in this file), for a path defined twice
# (AMBIGUOUS: two candidates, and picking one would be the silent pass this
# library exists to remove) and for a cycle. Callers must therefore keep a
# fail-closed branch for the undefined case; nothing here widens what is
# accepted, it only stops a resolvable symbol being read as its own name.
#
# NOTHING IS EVALUATED. The value handed back is the raw parsed HCL,
# `"${...}"` source and all, so every leaf still goes through `interp_body` +
# `slot` exactly as an inline one does.
_value_is_local_hop(v) if {
	body := interp_body(v)
	segs := parse_traversal(body)
	segs[0] == "local"
	count(segs) > 1
}

# Every TERMINAL value reachable from a `local.` path by `local.` -> `local.`
# hops, using the SAME `ref_graph` the ARN resolver walks (so the hop count is
# unbounded and cycles are safe for the same reason).
local_terminal_values(path) := {v |
	k := json.marshal(path)
	reach := graph.reachable(ref_graph, {k}) | {k}
	some n in reach
	some [p, v] in node
	json.marshal(p) == n
	not _value_is_local_hop(v)
}

deref_local(v) := out if {
	body := interp_body(v)
	segs := parse_traversal(body)
	segs[0] == "local"
	path := array.slice(segs, 1, count(segs))
	count(path) > 0
	vs := local_terminal_values(path)
	count(vs) == 1
	some out in vs
}

# ---------------------------------------------------------------------------
# resolve() -- THE three-valued classifier. TOTAL.
# ---------------------------------------------------------------------------
#
# Ordered `else` chain ending in an unconditional catch-all: for EVERY
# argument this returns exactly one verdict, and exactly one clause can ever
# produce it. See rule 2 in the header for why that is stronger than a
# `default` clause.
#
# A verdict is always an object carrying `kind` (one of the three), `symbol`,
# and enough detail for a deny message to quote the artifact rather than
# assert a diagnosis about it. A `resolved` verdict carries `referent_path`
# (the segment ARRAY -- what callers should type-match on) alongside the
# rendered `referent` string (for humans).
resolve(sym) := v if {
	# not a traversal at all
	not parse_traversal(sym)
	v := _unresolvable(sym, sprintf("%v is not a traversal this resolver can tokenize (an operator, a function call, a numeric index, a splat, whitespace or an escaped quote all read this way) -- refused rather than guessed at", [sym]))
} else := v if {
	# HCL's other reserved roots. None of them names a resource this
	# configuration creates, and none is resolvable from the root .tf files
	# alone, so each is refused BY NAME rather than being handed back as a
	# "resolved" referent that no type test would ever match. `module.x.out`
	# in particular would need module input/output plumbing -- a second
	# resolver on top of this one -- and is the direct blocker on any future
	# `hcl-modules` arm.
	segs := parse_traversal(sym)
	segs[0] == "module"
	v := _unresolvable(sym, sprintf("%v names a module output, which lives outside the root .tf files this resolver reads -- following it would need module input/output plumbing on top of this resolver, and it is refused rather than guessed at", [sym]))
} else := v if {
	# *** ROUND-16 RETRACTION, in the message itself. `each` used to be
	# lumped in with `count`/`self`/`path`/`terraform` under one reason
	# ending "...name no resource at all". That sentence is FALSE of an
	# artifact where `for_each` iterates a resource: EXECUTED, on a real
	# terraform 1.15.8 plan with
	#     resource "aws_s3_bucket" "b" { for_each = toset(["media"]) ... }
	#     resource "aws_lambda_permission" "allow_s3_invoke" {
	#       for_each = aws_s3_bucket.b ; source_arn = each.value.arn }
	# the deny read "`each` ... name no resource at all" while `each.value`
	# WAS the very bucket instance the notification wires (Amendment 29
	# sect 6 RULING 3). `each.*` now gets its own reason, which states the
	# limit -- this resolver takes ONE argument and cannot see the block the
	# symbol was written in -- instead of a claim about the artifact.
	#
	# A CALLER THAT KNOWS THE BLOCK CAN DO BETTER, and the caller is where
	# that knowledge lives: `for_each_referent(rtype, rname)` above hands a
	# policy the resource a block iterates when the argument is exactly one
	# whole-resource reference, and the plan's own `.index` gives the
	# instance key. See s3-notification-authoritative-singleton's
	# `each_value_arn_instances`.
	segs := parse_traversal(sym)
	segs[0] == "each"
	v := _unresolvable(sym, sprintf("%v names an element of the `for_each` expression of the block it is written in, and `resolve` is handed the symbol alone -- it cannot see that block, so WHICH instance this names is not establishable here. A caller that knows the block can resolve it via `for_each_referent` when the `for_each` argument is exactly one whole-resource reference; this verdict means no caller did", [sym]))
} else := v if {
	segs := parse_traversal(sym)
	segs[0] in {"count", "self", "path", "terraform"}
	v := _unresolvable(sym, sprintf("%v starts with the reserved HCL root `%v`, which names no resource this configuration creates", [sym, segs[0]]))
} else := v if {
	# a DIRECT reference to something outside the locals table: already the
	# referent, nothing to resolve.
	segs := parse_traversal(sym)
	segs[0] != "local"
	segs[0] != "var"
	v := _resolved(sym, sym)
} else := v if {
	segs := parse_traversal(sym)
	segs[0] == "var"
	v := _unresolvable(sym, sprintf("%v is an input variable; its value is not knowable from the configuration, so this resolver refuses to claim a referent for it", [sym]))
} else := v if {
	# from here down the symbol is `local.*`
	not hcl_supplied
	v := _unresolvable(sym, sprintf("%v is a `local.` symbol, but no .tf source was supplied to this policy at all -- symbol resolution is impossible, so this denies rather than guessing", [sym]))
} else := v if {
	no_source_supplied
	v := _unresolvable(sym, sprintf("%v is a `local.` symbol, but the .tf glob matched no file -- symbol resolution is impossible, so this denies rather than guessing", [sym]))
} else := v if {
	segs := parse_traversal(sym)
	count(segs) == 1
	v := _unresolvable(sym, "the bare symbol `local` names the whole locals table, not a single value")
} else := v if {
	path := _local_path(sym)
	count(node_values(path)) == 0
	v := _unresolvable(sym, sprintf("no `locals` block in any supplied .tf file defines %v", [sym]))
} else := v if {
	path := _local_path(sym)
	ts := chain_terminals(path)
	count(ts) == 1
	some ref in ts
	v := _resolved(sym, ref)
} else := v if {
	path := _local_path(sym)
	ts := chain_terminals(path)
	count(ts) > 1
	v := object.union(
		_ambiguous(sym, sprintf("%v reaches %d different referents and nothing in the configuration selects one of them", [sym, count(ts)])),
		{"candidates": sort([ref | some ref in ts])},
	)
} else := v if {
	# defined, but the chain from it reaches no concrete reference at all:
	# a literal, a container, an opaque expression, an undefined local, or
	# a cycle. The node's own value is quoted so the message names the dead
	# end instead of asserting which of the five it was.
	path := _local_path(sym)
	v := _unresolvable(sym, sprintf("%v is defined as %v, and following it through the locals table reaches no reference to a resource this configuration creates (a literal, a container, an opaque expression such as a function call or a conditional, an undefined local, or a cycle all read this way)", [sym, sort([val | some val in node_values(path)])]))
} else := _unresolvable(sym, "unclassified symbol -- this resolver refuses to guess (if you are reading this in a deny message, the resolver met a shape nobody enumerated and fell through to its catch-all, which is a deliberate fail-closed outcome, not an error)")

_local_path(sym) := array.slice(parse_traversal(sym), 1, count(parse_traversal(sym)))

# A `resolved` verdict is built from the referent's SOURCE STRING, so every
# field below is derived where the bracket-vs-dot information still exists.
#
#   referent_path  the flat segment array (what a TYPE test matches on)
#   instance       the RESOURCE INSTANCE identity -- type, label, and the
#                  `for_each`/`count` key when there is one. THIS is what a
#                  same-type/wrong-instance test must compare.
#   attr_path      the attribute path RELATIVE TO `instance`; `["arn"]` for
#                  both `aws_s3_bucket.media.arn` and
#                  `aws_s3_bucket.b["media"].arn`, and `[]` for a referent
#                  that names a resource but no attribute of it.
_resolved(sym, ref) := {
	"kind": "resolved",
	"symbol": sym,
	"referent_path": parse_traversal(ref),
	"referent": ref,
	"instance": instance_of(ref),
	"attr_path": array.slice(
		parse_traversal(ref),
		count(instance_of(ref)),
		count(parse_traversal(ref)),
	),
}

_ambiguous(sym, reason) := {"kind": "ambiguous", "symbol": sym, "reason": reason}

_unresolvable(sym, reason) := {"kind": "unresolvable", "symbol": sym, "reason": reason}

# ---------------------------------------------------------------------------
# slot() -- THE arity gate. TOTAL. This is the entry point callers use.
# ---------------------------------------------------------------------------
#
# Takes the RAW `.references` array `terraform show -json` emits for ONE
# dedicated single-ARN argument slot and returns ONE verdict.
#
# This exists so that a calling rule physically cannot forget the arity gate.
# The three-valued contract only holds if every slot REACHES the resolver in
# the first place; the prototype's slot 2 did not, and "no rule matched" is
# indistinguishable from a pass in the output. Note the gate is `== 1` on
# EVERY slot, in this ONE place: an earlier round shipped `!= 1` on one of
# two twin rules and reintroduced exactly that silent pass, regressing a
# fixture that was already checked in.
#
# Terraform emits every PREFIX of a traversal alongside the traversal
# (`local.arns.media_bucket` reads as `["local.arns.media_bucket",
# "local.arns"]`), so prefixes are dropped first -- BY SEGMENT ARRAY, never
# by string prefix, since `local.ab` is not a prefix of `local.abc` but
# "local.ab" is a string prefix of "local.abc".
#
# A reference the tokenizer cannot parse makes the WHOLE slot unresolvable.
# It is never dropped: dropping it would leave a lone survivor looking like a
# confidently-resolved slot, which is a silent pass wearing a resolved
# verdict.
slot(refs) := v if {
	count(refs) == 0
	v := _unresolvable("<empty>", "the slot carries no resource reference at all -- an omitted argument, an inline literal ARN and a wildcard ARN string all read exactly this way")
} else := v if {
	bad := _unparseable(refs)
	count(bad) > 0
	v := _unresolvable(concat(", ", sort(bad)), sprintf("the slot holds reference(s) this resolver cannot tokenize: %v -- the whole slot is refused rather than resolving the remainder, because dropping one reference would leave the rest looking confidently resolved", [sort(bad)]))
} else := v if {
	d := _deepest(refs)
	count(d) > 1
	v := object.union(
		_ambiguous(concat(", ", sort(d)), sprintf("the slot holds %d independent references (%v) -- a conditional, a coalesce or a concatenation reads this way, and nothing statically selects one of them", [count(d), sort(d)])),
		{"candidates": sort(d)},
	)
} else := v if {
	d := _deepest(refs)
	count(d) == 1
	some r in d
	v := resolve(r)
} else := _unresolvable("<unreadable>", sprintf("the slot's reference list %v holds nothing this resolver can read as a traversal", [refs]))

_unparseable(refs) := {r |
	some r in refs
	not parse_traversal(r)
}

_parsed(refs) := {[r, p] |
	some r in refs
	p := parse_traversal(r)
}

_deepest(refs) := {r |
	some [r, p] in _parsed(refs)
	not _extended(p, _parsed(refs))
}

_extended(p, prs) if {
	some [_, q] in prs
	count(q) > count(p)
	array.slice(q, 0, count(p)) == p
}

# ---------------------------------------------------------------------------
# small helpers callers need so they do not re-derive them
# ---------------------------------------------------------------------------

# The RESOURCE INSTANCE a referent names. Takes the referent's SOURCE
# STRING, not its segment array, and that is the whole point of the round-15
# rewrite:
#
#     aws_s3_bucket.media.arn                 -> ["aws_s3_bucket","media"]
#     aws_s3_bucket.b["media"].arn            -> ["aws_s3_bucket","b","media"]
#     aws_s3_bucket.b["decoy"].arn            -> ["aws_s3_bucket","b","decoy"]
#
# This is what makes SAME-TYPE / WRONG-INSTANCE discrimination possible at
# all -- "is this the right one of two buckets", as opposed to "is this a
# bucket". It is keyed on TERRAFORM'S OWN PLAN ADDRESS COMPONENTS (type,
# label and, for an expanded resource, the instance key), never on a
# physical cloud resource name.
#
# *** ROUND 15 DEFECT THIS CLOSES, executed. The previous body was
# `array.slice(segs, 0, 2)` -- first two segments, full stop. The tokenizer
# deliberately parses the `["key"]` form, so
# `aws_s3_bucket.b["cdktn-bench-media-ingest-decoy"].arn` resolved happily
# and then collapsed to `["aws_s3_bucket","b"]` -- IDENTICAL to what
# `aws_s3_bucket.b["cdktn-bench-media-ingest-media"].arn` yields. A Lambda
# permission scoped to the DECOY bucket of a two-key `for_each` scored
# REWARD 1.0. The collapse was SILENT precisely because the parse SUCCEEDED:
# the numeric `[0]` spelling has never parsed at all (loud), which is why
# three operator-facing texts wrongly claimed the whole family was refused.
# Those texts are corrected; this function is why they can be. ***
#
# HOW THE KEY IS RECOGNISED. A bracketed segment at position 2 is an
# instance key WHEN IT IS NOT THE LAST SEGMENT. That is exact for the two
# shapes that matter and errs loudly on the third:
#
#   * `aws_s3_bucket.b["media"].arn`  -- bracket at 2, more follows -> KEY.
#   * `aws_s3_bucket.media["arn"]`    -- HCL lets an attribute be spelled
#     with brackets. Bracket at 2 but LAST, so it is read as the attribute
#     (instance `["aws_s3_bucket","media"]`, attr_path `["arn"]`) and graded
#     correctly rather than false-failed.
#   * `aws_s3_bucket.b["media"]` with no attribute at all -- read as an
#     attribute named `media`, so `attr_path` is `["media"]`, not `["arn"]`,
#     and an ARN slot REFUSES it with a message quoting the referent. Loud.
#
# A NUMERIC index (`aws_s3_bucket.b[0].arn`) still does not tokenize at all
# and is therefore UNRESOLVABLE -> DENY. That is a known, LOUD false-FAIL on
# a `count`-expanded referent; see the residual list in this file's header.
instance_of(ref) := [_segment(ms[0]), _segment(ms[1]), _segment(ms[2])] if {
	ms := _parse_ms(ref)
	count(ms) >= 4
	startswith(ms[2][0], "[")
} else := array.slice(parse_traversal(ref), 0, 2) if {
	count(_parse_ms(ref)) >= 2
} else := parse_traversal(ref)

# Render an INSTANCE identity back as terraform's own plan address, so a
# deny message can be pasted into `terraform state show`. The three-element
# form is the `for_each` address spelling verbatim.
instance_addr(inst) := sprintf("%s.%s[%q]", [inst[0], inst[1], inst[2]]) if {
	count(inst) == 3
} else := concat(".", inst)

# NOTE (round 15): `attr_of(segs)` -- "the last segment of a referent path"
# -- used to live here and is DELETED rather than kept beside its
# replacement, for the same reason `render` was. It reads the ATTRIBUTE off
# the lossy segment array, so on `aws_s3_bucket.b["media"].arn` it happened
# to be right while its sibling `instance_of` was wrong, and a caller pairing
# the two ("count(path) >= 3 and attr_of == \"arn\"") got a test that looked
# instance-aware and was not. `attr_path` on the verdict is the replacement:
# it is the attribute path RELATIVE TO the instance, so `== ["arn"]` is one
# comparison that cannot be written half-right.

# NOTE, deliberately: this library exposes NO "is this verdict an .arn of
# type T" helper. It was written and removed. A caller that only needs the
# TYPE test is the exact shape that left same-type/wrong-instance open on
# every arm for five rounds, and a helper that stops at the type invites the
# call site to stop there too. `instance_of` + the caller's own knowledge of
# WHICH instance is right is the whole point; the library deliberately makes
# the weaker test no more convenient than the stronger one.
