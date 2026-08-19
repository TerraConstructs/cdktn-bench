"""gates/audit.py — Gate 2 of the three-gate integrity pattern.

"Did the trial actually run the arm's toolchain, or did the agent bypass it
and grep/cat its way to a green trial?" — the finding this gate exists to
catch is lex00's own: CDK 2/24 and Alchemy 0/24 trials ever invoked their
arm's own tool (``docs/lex00-bench-diff.md`` §2.2). A green reward with no
toolchain evidence is not a scored result, it's an invalid-bypass.

Reads Harbor's ATIF ``trajectory.json`` (``<job_dir>/<trial_name>/agent/trajectory.json``
per RECON.md §3) and walks ``steps[].tool_calls[]`` for Bash invocations
(``function_name == "Bash"``, ``arguments.command``). Matching is
**positional, not textual**: each ``&&``/``||``/``;``/``|``/newline-delimited
segment of the command is shell-tokenized (``shlex``, with ``#``-comments
stripped first), a leading ``(``/``then``/``do``/``else`` shell-syntax token
and a trailing subshell ``)`` are stripped (so ``(cd app && cdk synth)`` and
``if ...; then cdk synth; fi`` still expose the real argv[0]), any leading
wrapper the segment is invoked through (env-var assignments, ``sudo``,
``env``, ``timeout``/``nice``/``ionice``/``stdbuf`` [+ their numeric/flag
args], ``npx [flags]``, ``pnpm|yarn|npm exec|dlx|run``) is peeled off, and
the arm's tool is credited ONLY if it is the resulting argv[0] (by
basename) — with the required subcommand (``synth``/``validate``/``plan``)
present as one of the later argv tokens. A versioned npx/dlx package
argument (``npx aws-cdk@2 synth``) is resolved through
``_resolve_npm_package_token`` to the CLI binary name it actually execs
(``aws-cdk`` → ``cdk``) before the argv[0] comparison. A segment whose
resolved argv[0] is a shell itself (``bash``/``sh``/``zsh``/``ksh``/``dash``)
invoked as ``... -c '<command string>'`` is recursed into: the quoted
argument is re-segmented and matched the same way, so ``bash -c 'cdk
synth'`` is credited exactly like a direct invocation. A bare mention of
"terraform" or "cdk synth" as an *argument* to
``echo``/``printf``/``grep``/``cat``/``which``/``man``/... never satisfies
this, because those tools occupy argv[0] instead and the check fails on
argv[0] alone — no separate denylist is needed. A ``#``-comment line, or the
same words spelled inside a quoted string handed to ``echo``, both tokenize
to a non-matching (or empty) argv[0] for the same reason.

Positive-evidence matching, not exit-code sniffing on its own — we don't
require the underlying command to have exited 0 (a failed ``cdk synth``
still proves the agent *tried* the real toolchain, which is the question
this gate answers; whether it ultimately succeeded is the reward's job).
However, a positionally-matched call whose ``observation`` shows the tool
was never actually available to run — "command not found"/exit 127, or
SIGKILLed/exit 137 — is evidence of a *degraded arm*, not of the agent
choosing to bypass a working toolchain, so it is tracked separately (see
``status``/``degraded`` below) rather than silently counted as valid.

Structured exit codes, when available, are trusted over free-text
classification. Harbor's ``claude_code.py``'s ``_format_tool_result``
records the Bash tool's real exit code on the matching STEP's
``extra.metadata.tool_use_result`` (``exitCode``/``exit_code``) — see
``_extract_structured_exit_code``. When that signal is present and
unambiguous (the step carries exactly one tool call, so there's no question
which call it belongs to), it alone decides ``ok``/``failed``/``missing``/
``sigkill``, and no agent-authored observation text can override it — an
agent printing a forged ``bash: cdk: command not found`` after a real,
successful, exit-0 run no longer routes the trial to invalid-infra.
**Residual channel**: when no structured signal is available — a different
harness/producer, a step whose ``extra`` covers more than one tool call, or
a trajectory captured before this field existed — classification still
falls back to the anchored free-text heuristics below (see
``_classify_evidence_status``), and an agent can in principle still
self-void its own trial there by printing an anchored fake status line as
the first/last line of otherwise-suppressed real output. Anchoring bounds
this (see ``_tool_missing_pattern``/``_EXIT_CODE_LINE_RE``) but does not
eliminate it; closing it fully would require every trajectory producer to
supply a structured exit code.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Per-arm evidence: (pattern_name, required_argv0_basename, required_subcommand
# tokens-or-None). A segment counts as evidence iff, after wrapper-peeling
# (see _peel_wrappers), its argv[0] basename equals required_argv0_basename
# and — when required_subcommands is not None — at least one of argv[1:]
# is in that set. `tsc` has no subcommand requirement (argv[0] alone is the
# tool). Word-for-word argv[0] equality (not substring/regex search) is what
# makes "cdktn synth" (terraconstructs) never satisfy awscdk's "cdk synth"
# pattern, and makes "cdk-synth-notes.txt" (a filename, not a command) never
# satisfy it either.
ARM_TOKEN_PATTERNS: dict[str, list[tuple[str, str, frozenset[str] | None]]] = {
    "awscdk": [
        ("tsc", "tsc", None),
        ("cdk synth", "cdk", frozenset({"synth"})),
    ],
    "hcl-raw": [
        ("terraform validate", "terraform", frozenset({"validate"})),
        ("terraform plan", "terraform", frozenset({"plan"})),
    ],
    "terraconstructs": [
        ("cdktn synth", "cdktn", frozenset({"synth"})),
    ],
}

KNOWN_ARMS = sorted(ARM_TOKEN_PATTERNS)

# Heredoc opener: `<<WORD`, `<<-WORD` (tab-strip form), `<<'WORD'`, `<<"WORD"`.
# Captures (dash, tag) so `_segments` can locate the matching terminator line
# and excise the whole heredoc BODY (never real command text — it's data
# being written/piped, see module docstring) before segmenting.
_HEREDOC_OPEN_RE = re.compile(r"<<(-)?\s*(?:(['\"])([A-Za-z_][A-Za-z0-9_]*)\2|([A-Za-z_][A-Za-z0-9_]*))")

# Wrappers peeled off the front of a tokenized segment before checking
# argv[0] against a pattern's required tool name — see module docstring.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SINGLE_TOKEN_WRAPPERS = {"sudo", "env"}
_PACKAGE_RUNNER_SUBCOMMANDS = {"exec", "dlx", "run"}
_PACKAGE_RUNNERS = {"pnpm", "yarn", "npm"}

# `timeout`/`nice`/`ionice`/`stdbuf` all take a run of leading flags (some
# with attached or space-separated values, e.g. `-n 10`, `--signal=KILL`)
# and/or a bare numeric argument (timeout's DURATION, nice's niceness level)
# before the real command's own argv[0] — e.g. `timeout 600 cdk synth`,
# `nice -n 10 cdk synth`, `ionice -c2 -n7 cdk synth`, `stdbuf -oL cdk synth`.
_MULTI_ARG_WRAPPERS = {"timeout", "nice", "ionice", "stdbuf"}
_WRAPPER_NUMERIC_ARG_RE = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")

# Shells whose `-c '<command string>'` form embeds a real command as a
# single quoted argument rather than as separate argv tokens — recursed
# into by `_matches` so `bash -c 'cdk synth'` is credited like a direct
# invocation (see module docstring).
_SHELL_C_INVOKERS = {"bash", "sh", "zsh", "ksh", "dash"}

# Leading shell-syntax tokens that can precede a real command in the same
# segment without being a wrapper *around* it — a subshell opener glued to
# the next token (`(cd app && cdk synth)` splits into segments `(cd app`
# and `cdk synth)`, so the trailing `)` needs stripping too) or a
# compound-statement keyword (`if ...; then cdk synth; fi`, `for x; do cdk
# synth; done`, `... else cdk synth; fi`) whose own segment starts with the
# keyword once `_segments` has split on the surrounding `;`.
_LEADING_STRIP_TOKENS = {"(", "then", "do", "else"}

# npm package name -> the CLI binary name npx/`pnpm|yarn dlx` actually
# resolve and exec, for the (rare) cases where they differ. Most packages'
# bin name equals the package name (`npx tsc`, `npx cdktn`, ...) and need
# no entry here; `aws-cdk` -> `cdk` is the one that matters for the awscdk
# arm (arms/awscdk/README.md: `npm install -g aws-cdk@...` installs a `cdk`
# binary), so `npx -y aws-cdk@2 synth` must still credit `cdk`.
_NPM_PACKAGE_BIN_ALIASES = {"aws-cdk": "cdk"}


def _strip_npm_version_spec(token: str) -> str:
    """``pkg@2`` -> ``pkg``, ``@scope/pkg@1.2.3`` -> ``@scope/pkg``, a
    bare ``pkg`` (no version) -> unchanged. Only strips a version suffix
    introduced by an ``@`` that is not the token's own leading scope
    marker."""
    if token.startswith("@"):
        idx = token.rfind("@")
        return token[:idx] if idx > 0 else token
    idx = token.find("@")
    return token[:idx] if idx > 0 else token


def _resolve_npm_package_token(token: str) -> str:
    """Resolve an npx/dlx package argument (possibly versioned) to the CLI
    binary name it actually execs, per ``_NPM_PACKAGE_BIN_ALIASES``."""
    return _NPM_PACKAGE_BIN_ALIASES.get(_strip_npm_version_spec(token), _strip_npm_version_spec(token))


# FALLBACK PATH ONLY — consulted by `_classify_evidence_status` solely when
# `_extract_structured_exit_code` returned `None` for the step (see the
# module docstring's "Structured exit codes"/"Residual channel"
# paragraphs). Observation-text signals that a positionally-matched tool
# call never actually ran the real tool (the container/toolchain was
# unavailable), distinct from the tool running and genuinely failing. The
# agent's own Bash command chooses what text lands in `observation.content`
# (ATIF's ObservationResult has no structured exit-code/status field of its
# own to read instead — harbor/models/trajectories/observation_result.py —
# and the harness that DOES carry a structured exit code, claude_code.py's
# `_format_tool_result`, puts it on the STEP's `extra.metadata`, which is
# now read directly by `_extract_structured_exit_code`, but isn't
# guaranteed present for every agent/producer or when a step's `extra`
# would be ambiguous across multiple tool calls), so free-text matching
# here MUST stay anchored, not a bare substring search anywhere in the text
# — otherwise an agent (or a task whose legitimate output happens to
# mention a phrase like "no such file or directory" from an ordinary
# ENOENT) can self-void its own trial. Two anchors, both required (see
# `_classify_evidence_status`):
#   - "command not found"/"not found" must be immediately attached to the
#     SPECIFIC matched tool's own name, at the START of the observation
#     (`bash: cdk: command not found`, `cdk: command not found`,
#     `zsh: command not found: cdk`, ...) — never a bare substring, and
#     never satisfied by a different word ("no such file or directory" is
#     dropped entirely: it's ordinary Node/cdk ENOENT chatter, not a missing
#     toolchain signal).
#   - An exit-code phrase (127/137) must be the observation's TERMINAL
#     (last non-blank) line, matching a real status-line shape (`Exit code
#     127`, `exited (137)`, `[exit_code] 127` — the last is literally what
#     claude_code.py's own `_format_tool_result` emits), not merely
#     mentioned anywhere in running prose ("...exit 137 mentioned in the
#     log" does not qualify).
_GENERIC_FAILURE_RE = re.compile(
    r"\berror\b|\bfailed\b|\btraceback\b|\bexit(?:ed)? \(?[1-9]\d*\)?\b|\bnon-zero exit\b",
    re.IGNORECASE,
)

_SHELL_PREFIX = r"(?:\S*(?:ba)?sh\S*\s*:\s*)?(?:\d+\s*:\s*)?"


def _tool_missing_pattern(tool: str) -> re.Pattern[str]:
    """Build a pattern anchored to THIS specific matched tool's own name,
    required at the start of the observation text (see module-level comment
    above `_GENERIC_FAILURE_RE`)."""
    t = re.escape(tool)
    return re.compile(
        rf"^\s*{_SHELL_PREFIX}(?:{t}\s*:\s*(?:command not found|not found)\b"
        rf"|command not found\s*:\s*{t}\b)",
        re.IGNORECASE,
    )


_EXIT_CODE_LINE_RE = re.compile(
    r"^\[?exit(?:ed)?(?:[\s_]*code)?\]?\s*:?\s*\(?(\d+)\)?\]?$",
    re.IGNORECASE,
)
_SIGKILL_WORD_RE = re.compile(r"(?<!not )\bkilled\b|oomkilled", re.IGNORECASE)


def _terminal_exit_code(text: str) -> int | None:
    """The observation's last non-blank line, IFF that whole line is (only)
    an exit-code status report — not a phrase merely occurring somewhere in
    the middle of unrelated prose. Returns ``None`` otherwise."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    m = _EXIT_CODE_LINE_RE.match(lines[-1])
    return int(m.group(1)) if m else None


def _terminal_line(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _segments(command: str) -> list[str]:
    """Split a Bash command string into independently-checked segments so
    "cat foo.tf && terraform validate" is credited (segment 2 matches) but a
    pattern spanning two unrelated segments (e.g. "terraform" in segment 1,
    unrelated "plan" in segment 2 talking about something else) is not.

    Character-level scan (not a raw regex split on ``&&``/``||``/``;``/``|``/
    newline) so quoting and heredocs are respected:

    - A ``;``/``|``/``\\n`` (or ``&&``/``||``) sitting *inside* a quoted
      string never splits — the whole quoted argument stays one token, so
      ``echo "step 1: edit\\ncdk synth\\ndone"`` is one segment (argv[0]
      ``echo``), not three, one of which would otherwise spuriously read as
      a bare ``cdk synth`` invocation.
    - A heredoc body (``<<WORD`` ... terminator line) is excised entirely
      before segmenting — it's data being written to a file/piped to a
      command, never a command itself, so ``cat > NOTES.md <<'EOF'\\ncdk
      synth\\nEOF`` must not credit "cdk synth" as evidence. The heredoc's
      OPENING marker line is kept (so `cat`/`terraform`/etc as the real
      argv[0] of that segment still matches normally); only the body +
      terminator are dropped. The newline immediately after the terminator
      is left in place (not consumed as part of the excision) so it still
      acts as a normal segment break — a real command following a heredoc
      on the next line (``cat >x <<EOF\\n...\\nEOF\\ncdk synth``) still
      forms its own, correctly-segmented, evidence-eligible segment.
    - A ``#`` outside quotes starts a comment that runs to (but does not
      consume) the next newline, matching ``shlex.split(..., comments=True)``
      semantics for the eventual per-segment tokenization.
    """
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    n = len(command)

    def flush() -> None:
        text = "".join(current).strip()
        if text:
            segments.append(text)
        current.clear()

    while i < n:
        ch = command[i]

        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\" and i + 1 < n:
                current.append(command[i + 1])
                i += 1
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue

        if ch == "\\" and i + 1 < n:
            current.append(ch)
            current.append(command[i + 1])
            i += 2
            continue

        if ch == "#":
            while i < n and command[i] != "\n":
                i += 1
            continue

        if command.startswith("<<", i):
            m = _HEREDOC_OPEN_RE.match(command, i)
            if m:
                dash = m.group(1) == "-"
                tag = m.group(3) or m.group(4)
                current.append(command[i : m.end()])
                i = m.end()
                nl = command.find("\n", i)
                if nl == -1:
                    i = n
                else:
                    body_start = nl + 1
                    if dash:
                        term_re = re.compile(r"^[ \t]*" + re.escape(tag) + r"[ \t]*$", re.MULTILINE)
                    else:
                        term_re = re.compile(r"^" + re.escape(tag) + r"[ \t]*$", re.MULTILINE)
                    term_m = term_re.search(command, body_start)
                    i = term_m.end() if term_m else n
                continue

        if command.startswith("&&", i):
            flush()
            i += 2
            continue
        if command.startswith("||", i):
            flush()
            i += 2
            continue
        if ch in (";", "|", "\n"):
            flush()
            i += 1
            continue

        current.append(ch)
        i += 1

    flush()
    return segments


def _peel_wrappers(tokens: list[str]) -> list[str]:
    """Strip leading env-assignments/sudo/env/npx/pnpm-yarn-npm-exec-dlx-run
    wrappers so the tool's own argv[0] is exposed for comparison. A segment
    like "cd X && terraform validate" never reaches here with the "cd X"
    part attached — `_segments` already splits on `&&`/`;`/`|` — so `cd` is
    not peeled here; it simply forms its own (non-matching) segment.
    """
    tokens = list(tokens)
    changed = True
    while tokens and changed:
        changed = False
        while tokens and _ENV_ASSIGNMENT_RE.match(tokens[0]):
            tokens.pop(0)
            changed = True
        if not tokens:
            break
        head = tokens[0]
        if head in _SINGLE_TOKEN_WRAPPERS:
            tokens.pop(0)
            changed = True
            continue
        if head == "npx":
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                tokens.pop(0)
            if tokens:
                tokens[0] = _resolve_npm_package_token(tokens[0])
            changed = True
            continue
        if head in _PACKAGE_RUNNERS and len(tokens) > 1 and tokens[1] in _PACKAGE_RUNNER_SUBCOMMANDS:
            subcommand = tokens[1]
            tokens = tokens[2:]
            if subcommand == "dlx" and tokens:
                tokens[0] = _resolve_npm_package_token(tokens[0])
            changed = True
            continue
        if head in _MULTI_ARG_WRAPPERS:
            tokens.pop(0)
            while tokens and (tokens[0].startswith("-") or _WRAPPER_NUMERIC_ARG_RE.match(tokens[0])):
                tokens.pop(0)
            changed = True
            continue
    return tokens


def _tool_argv(seg: str) -> list[str]:
    """Tokenize one command segment into its effective argv, wrappers
    peeled. Returns ``[]`` if the segment is empty/comment-only or cannot be
    safely tokenized (e.g. unbalanced quotes) — such a segment is credited
    to no pattern rather than raising, since a malformed fragment is not
    positive evidence of anything.

    Before tokenizing, a leading run of ``(`` and a trailing run of ``)``
    are stripped from the raw segment text (string-level, so a subshell
    opener glued to the next word — ``(cd app`` from ``(cd app && cdk
    synth)`` — is handled the same as a spaced one), and after tokenizing,
    a leading ``then``/``do``/``else`` keyword token is stripped (see
    ``_LEADING_STRIP_TOKENS``) — both cases only arise because `_segments`
    split a compound-statement/subshell command on its `;`/`&&`/`|`, not
    because they're wrappers *around* a command the way `sudo`/`npx` are.
    """
    seg = seg.strip().lstrip("(").rstrip(")")
    try:
        tokens = shlex.split(seg, comments=True)
    except ValueError:
        return []
    while tokens and tokens[0] in _LEADING_STRIP_TOKENS:
        tokens.pop(0)
    return _peel_wrappers(tokens)


_MAX_SHELL_C_RECURSION_DEPTH = 5


def _matches(
    patterns: list[tuple[str, str, frozenset[str] | None]], command: str, _depth: int = 0
) -> list[tuple[str, str, str]]:
    """Returns ``(pattern_name, segment_text, matched_tool_basename)``
    triples — the tool basename is threaded through to
    ``_classify_evidence_status`` so its "command not found" anchor checks
    THIS call's own matched tool name, not a generic phrase.

    A segment whose resolved argv[0] is a shell (``bash``/``sh``/``zsh``/
    ``ksh``/``dash``) invoked with ``-c '<command string>'`` is recursed
    into (the quoted argument is re-segmented and matched the same way),
    so ``bash -c 'cdk synth'`` is credited exactly like a direct
    invocation. ``_depth`` bounds the recursion (nested ``bash -c 'bash -c
    ...'``) so a pathological/malicious trajectory can't cause unbounded
    recursion.
    """
    if _depth > _MAX_SHELL_C_RECURSION_DEPTH:
        return []
    hits: list[tuple[str, str, str]] = []
    for seg in _segments(command):
        argv = _tool_argv(seg)
        if not argv:
            continue
        tool = Path(argv[0]).name
        rest = argv[1:]
        if tool in _SHELL_C_INVOKERS and "-c" in rest:
            c_idx = rest.index("-c")
            if c_idx + 1 < len(rest):
                inner_command = rest[c_idx + 1]
                hits.extend(_matches(patterns, inner_command, _depth=_depth + 1))
        for name, tool_name, subcommands in patterns:
            if tool != tool_name:
                continue
            if subcommands is not None and not (subcommands & set(rest)):
                continue
            hits.append((name, seg.strip(), tool))
    return hits


def _observation_text(observation: dict[str, Any] | None) -> str:
    if not observation:
        return ""
    content = observation.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
        return "\n".join(parts)
    return ""


def _extract_structured_exit_code(step: dict[str, Any]) -> int | None:
    """The structured Bash exit code Harbor's ``claude_code.py``
    ``_format_tool_result`` attaches to a tool-call STEP's
    ``extra.metadata.tool_use_result`` (``exitCode``/``exit_code``) — see
    the module docstring's "Structured exit codes" paragraph and
    ``gates/RECON.md`` §3.

    Only trusted when the step carries exactly ONE tool call, so there is
    no ambiguity about which call the code belongs to (``extra`` is a
    step-level field). Returns ``None`` when absent, non-numeric, or
    ambiguous, in which case callers fall back to text-based
    classification (the residual channel documented in the module
    docstring).
    """
    tool_calls = step.get("tool_calls") or []
    if len(tool_calls) != 1:
        return None
    extra = step.get("extra")
    if not isinstance(extra, dict):
        return None
    metadata = extra.get("metadata")
    if not isinstance(metadata, dict):
        return None
    tool_use_result = metadata.get("tool_use_result")
    if not isinstance(tool_use_result, dict):
        return None
    code = tool_use_result.get("exitCode", tool_use_result.get("exit_code"))
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def _classify_evidence_status(
    observation: dict[str, Any] | None, tool: str, structured_exit_code: int | None = None
) -> str:
    """Classify one matched Bash call's outcome.

    ``tool`` is the specific tool basename THIS call positionally matched
    (e.g. ``"cdk"``/``"terraform"``) — the "command not found" check is
    anchored to that exact name, never a bare substring search, so the
    agent's own free-text observation content can't self-void the trial by
    mentioning an unrelated phrase (see the anchoring comment above
    ``_tool_missing_pattern``).

    ``structured_exit_code``, when not ``None`` (see
    ``_extract_structured_exit_code``), is TRUSTED OUTRIGHT and decides the
    result — no free-text classification is consulted at all, so an
    agent's own observation text can no longer override a real exit code
    (the finding this parameter closes: a forged ``bash: cdk: command not
    found`` printed after a genuine, successful run could otherwise still
    route the trial to invalid-infra). When it is ``None`` (no structured
    signal — see the module docstring's "Residual channel" paragraph),
    behavior is unchanged from before: classify from the observation text.

    Returns one of ``ok`` / ``failed`` / ``missing`` / ``sigkill`` / ``unknown``.
    ``unknown`` (no observation captured at all, and no structured exit
    code) is treated as non-degrading by callers — the pre-existing, more
    permissive behavior — since its absence is not positive evidence the
    toolchain was unavailable.
    """
    if structured_exit_code is not None:
        if structured_exit_code == 127:
            return "missing"
        if structured_exit_code == 137:
            return "sigkill"
        if structured_exit_code == 0:
            return "ok"
        return "failed"
    text = _observation_text(observation)
    if not text:
        return "unknown"
    if _tool_missing_pattern(tool).match(text.strip()):
        return "missing"
    exit_code = _terminal_exit_code(text)
    if exit_code == 127:
        return "missing"
    if exit_code == 137:
        return "sigkill"
    if _SIGKILL_WORD_RE.search(_terminal_line(text)):
        return "sigkill"
    if _GENERIC_FAILURE_RE.search(text):
        return "failed"
    return "ok"


def iter_bash_calls(trajectory: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield ``{step_id, tool_call_id, command, observation,
    structured_exit_code}`` for every Bash tool call. ``observation`` is the
    matching ``ObservationResult`` dict (joined via
    ``observation.results[].source_call_id == tool_call_id``, per Harbor's
    ATIF schema) or ``None`` if the step carries no observation for that
    call. ``structured_exit_code`` is the step's structured exit code (see
    ``_extract_structured_exit_code``), or ``None`` if unavailable/ambiguous.
    """
    for step in trajectory.get("steps") or []:
        step_id = step.get("step_id")
        structured_exit_code = _extract_structured_exit_code(step)
        obs_by_call_id: dict[str, dict[str, Any]] = {}
        for res in (step.get("observation") or {}).get("results") or []:
            call_id = res.get("source_call_id")
            if call_id is not None:
                obs_by_call_id[call_id] = res
        for tc in step.get("tool_calls") or []:
            function_name = (tc.get("function_name") or "").strip()
            if function_name.lower() != "bash":
                continue
            arguments = tc.get("arguments") or {}
            command = arguments.get("command")
            if isinstance(command, str) and command.strip():
                tool_call_id = tc.get("tool_call_id")
                yield {
                    "step_id": step_id,
                    "tool_call_id": tool_call_id,
                    "command": command,
                    "observation": obs_by_call_id.get(tool_call_id),
                    "structured_exit_code": structured_exit_code,
                }


_DEGRADED_STATUSES = frozenset({"missing", "sigkill"})


def audit_trajectory(trajectory: dict[str, Any], arm: str) -> dict[str, Any]:
    """Audit an already-parsed ATIF trajectory dict for arm-toolchain evidence.

    Returns ``{valid, evidence, degraded, degraded_kind, reason, arm,
    bash_call_count}``.

    ``evidence`` entries each carry a ``status`` (``ok``/``failed``/
    ``missing``/``sigkill``/``unknown``, see ``_classify_evidence_status``).

    ``valid`` is True iff at least one Bash call matched the arm's toolchain
    pattern(s) AND was not exclusively evidenced as unavailable (``missing``/
    ``sigkill``) — a matched call that genuinely ran and failed (``failed``)
    still counts, per the module docstring.

    ``degraded`` is True iff there IS pattern-matching evidence but every
    single matched call was ``missing``/``sigkill`` — i.e. the agent did try
    the arm's own tool, but the tool itself was never actually available to
    run. This is a different failure mode from a bypass (the agent never
    tried) and callers (``emit_result.py``) route it to invalid-infra rather
    than invalid-bypass.
    """
    if arm not in ARM_TOKEN_PATTERNS:
        raise ValueError(f"unknown arm {arm!r} (known: {KNOWN_ARMS})")

    patterns = ARM_TOKEN_PATTERNS[arm]
    bash_calls = list(iter_bash_calls(trajectory))

    evidence: list[dict[str, Any]] = []
    for call in bash_calls:
        for name, seg, tool in _matches(patterns, call["command"]):
            status = _classify_evidence_status(call["observation"], tool, call["structured_exit_code"])
            evidence.append(
                {
                    "step_id": call["step_id"],
                    "tool_call_id": call["tool_call_id"],
                    "pattern": name,
                    "command": seg[:300],
                    "status": status,
                }
            )

    has_evidence = len(evidence) > 0
    degrading = [e for e in evidence if e["status"] in _DEGRADED_STATUSES]
    live = [e for e in evidence if e["status"] not in _DEGRADED_STATUSES]
    degraded = has_evidence and not live
    valid = len(live) > 0

    expected = ", ".join(name for name, _, _ in patterns)
    if valid:
        matched_kinds = sorted({e["pattern"] for e in live})
        reason = (
            f"{arm} toolchain invoked: {', '.join(matched_kinds)} "
            f"({len(live)} matching Bash call(s) of {len(bash_calls)} total)"
        )
    elif degraded:
        degraded_kind = degrading[0]["status"]
        matched_kinds = sorted({e["pattern"] for e in degrading})
        reason = (
            f"{arm} toolchain invoked ({', '.join(matched_kinds)}) but never actually ran "
            f"({degraded_kind}: {degrading[0]['command'][:120]!r}) — degraded arm, not a bypass"
        )
    else:
        reason = (
            f"invalid-bypass: no {arm} toolchain command found in trajectory "
            f"(checked {len(bash_calls)} Bash call(s); expected one of: {expected})"
        )

    return {
        "valid": valid,
        "evidence": evidence,
        "degraded": degraded,
        "degraded_kind": degrading[0]["status"] if degraded else None,
        "reason": reason,
        "arm": arm,
        "bash_call_count": len(bash_calls),
    }


def resolve_step_names(trial_dir: str | Path) -> list[str]:
    """Ordered per-step output-dir names under ``<trial_dir>/steps/``.

    A multi-step trial relocates ``agent/``, ``verifier/`` and ``artifacts/``
    into ``steps/<name>/`` after each step
    (``harbor/trial/multi_step.py::_archive_step_outputs``), so every
    trial-dir reader in this repo needs to know which step dirs exist and in
    what order. Returns ``[]`` for a single-step trial dir (no ``steps/``),
    which is what keeps every single-step code path below byte-identical.

    Order comes from ``result.json``'s own ``step_results`` when it is
    readable — that is the authoritative execution order — with any remaining
    directories appended in sorted order. Sorted-name order is a correct
    fallback only because the task-dir convention numbers steps
    (``01-initial``, ``02-change-request``, per
    ``docs/design/multistep-trial-investigation.md`` §5); ``result.json`` is
    preferred precisely so a task that ignores that convention still reads in
    true execution order.
    """
    steps_dir = Path(trial_dir) / "steps"
    if not steps_dir.is_dir():
        return []
    present = {p.name for p in steps_dir.iterdir() if p.is_dir()}
    ordered: list[str] = []

    result_path = Path(trial_dir) / "result.json"
    if result_path.is_file():
        try:
            data = json.loads(result_path.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            for step_result in data.get("step_results") or []:
                if not isinstance(step_result, dict):
                    continue
                name = step_result.get("step_name")
                if name in present and name not in ordered:
                    ordered.append(name)

    ordered.extend(sorted(present - set(ordered)))
    return ordered


def resolve_trajectory_paths(trial_dir_or_file: str | Path) -> list[Path]:
    """Every trajectory belonging to one trial, in execution order.

    Single-step: exactly one (``agent/trajectory.json``). Multi-step: one per
    step that produced one (``steps/<name>/agent/trajectory.json``) — Harbor
    relocates the agent log dir into the step dir after each step, and starts
    the next step with an empty ``/logs/agent``, so a step's trajectory covers
    that step ALONE (a fresh ``claude --print`` session per step; DECISIONS.md
    Amendment 26).

    Raises:
        FileNotFoundError: if no trajectory exists anywhere under the dir.
    """
    p = Path(trial_dir_or_file)
    if p.is_file():
        return [p]

    candidates = [p / "agent" / "trajectory.json", p / "trajectory.json"]
    for c in candidates:
        if c.is_file():
            return [c]

    step_paths = [
        p / "steps" / name / "agent" / "trajectory.json"
        for name in resolve_step_names(p)
    ]
    step_paths = [c for c in step_paths if c.is_file()]
    if step_paths:
        return step_paths

    checked = ", ".join(str(c) for c in [*candidates, p / "steps" / "*" / "agent" / "trajectory.json"])
    raise FileNotFoundError(f"no trajectory.json found under {p} (checked: {checked})")


def resolve_trajectory_path(trial_dir_or_file: str | Path) -> Path:
    """The trial's first trajectory. See ``resolve_trajectory_paths``."""
    return resolve_trajectory_paths(trial_dir_or_file)[0]


def audit_trial(trial_dir_or_file: str | Path, arm: str) -> dict[str, Any]:
    """Load + audit a trial's trajectory. See ``audit_trajectory`` for the shape.

    A multi-step trial is audited over the CONCATENATION of its per-step
    trajectories, because the question this gate answers — "did this trial ever
    really invoke the arm's toolchain?" — is a trial-level question. An agent
    that ran ``terraform plan`` in step 1 and only edited files in step 2 has
    not bypassed the toolchain. Auditing each step separately would invent a
    stricter rule than the one this benchmark pre-registered.

    ``trajectory_path`` keeps naming the first trajectory (unchanged for
    single-step); ``trajectory_paths`` is added ONLY when there is more than
    one, so a single-step record is byte-identical to before.
    """
    traj_paths = resolve_trajectory_paths(trial_dir_or_file)
    steps: list[Any] = []
    for path in traj_paths:
        data = json.loads(path.read_text())
        steps.extend(data.get("steps") or [])
    result = audit_trajectory({"steps": steps}, arm)
    result["trajectory_path"] = str(traj_paths[0])
    if len(traj_paths) > 1:
        result["trajectory_paths"] = [str(p) for p in traj_paths]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate 2: verify a trial's trajectory actually invoked its arm's toolchain."
    )
    parser.add_argument("trial_dir", help="Trial dir, agent/ dir, or a trajectory.json path.")
    parser.add_argument("--arm", required=True, choices=KNOWN_ARMS, help="Arm to audit against.")
    parser.add_argument("--json-out", default=None, help="Also write the JSON report to this path.")
    args = parser.parse_args(argv)

    try:
        report = audit_trial(args.trial_dir, args.arm)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "valid": False,
            "evidence": [],
            "reason": f"audit error: {exc}",
            "arm": args.arm,
        }
        print(json.dumps(report, indent=2))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        return 2

    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
