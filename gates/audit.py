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
stripped first), any leading wrapper the segment is invoked through
(env-var assignments, ``sudo``, ``env``, ``npx [flags]``,
``pnpm|yarn|npm exec|dlx|run``) is peeled off, and the arm's tool is credited
ONLY if it is the resulting argv[0] (by basename) — with the required
subcommand (``synth``/``validate``/``plan``) present as one of the later
argv tokens. A bare mention of "terraform" or "cdk synth" as an *argument* to
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

# Observation-text signals that a positionally-matched tool call never
# actually ran the real tool (the container/toolchain was unavailable),
# distinct from the tool running and genuinely failing. The agent's own Bash
# command chooses what text lands in `observation.content` (ATIF's
# ObservationResult has no structured exit-code/status field to read
# instead — harbor/models/trajectories/observation_result.py — and the one
# harness that does carry a structured exit code, claude_code.py's
# `_format_tool_result`, puts it on the STEP's `extra.metadata`, not on this
# gate's per-call observation, and isn't guaranteed present for every
# agent/producer), so free-text matching here MUST be anchored, not a bare
# substring search anywhere in the text — otherwise an agent (or a task
# whose legitimate output happens to mention a phrase like "no such file or
# directory" from an ordinary ENOENT) can self-void its own trial. Two
# anchors, both required (see `_classify_evidence_status`):
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
            changed = True
            continue
        if head in _PACKAGE_RUNNERS and len(tokens) > 1 and tokens[1] in _PACKAGE_RUNNER_SUBCOMMANDS:
            tokens = tokens[2:]
            changed = True
            continue
    return tokens


def _tool_argv(seg: str) -> list[str]:
    """Tokenize one command segment into its effective argv, wrappers
    peeled. Returns ``[]`` if the segment is empty/comment-only or cannot be
    safely tokenized (e.g. unbalanced quotes) — such a segment is credited
    to no pattern rather than raising, since a malformed fragment is not
    positive evidence of anything.
    """
    try:
        tokens = shlex.split(seg, comments=True)
    except ValueError:
        return []
    return _peel_wrappers(tokens)


def _matches(
    patterns: list[tuple[str, str, frozenset[str] | None]], command: str
) -> list[tuple[str, str, str]]:
    """Returns ``(pattern_name, segment_text, matched_tool_basename)``
    triples — the tool basename is threaded through to
    ``_classify_evidence_status`` so its "command not found" anchor checks
    THIS call's own matched tool name, not a generic phrase."""
    hits: list[tuple[str, str, str]] = []
    for seg in _segments(command):
        argv = _tool_argv(seg)
        if not argv:
            continue
        tool = Path(argv[0]).name
        rest = argv[1:]
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


def _classify_evidence_status(observation: dict[str, Any] | None, tool: str) -> str:
    """Classify one matched Bash call's outcome from its observation text.

    ``tool`` is the specific tool basename THIS call positionally matched
    (e.g. ``"cdk"``/``"terraform"``) — the "command not found" check is
    anchored to that exact name, never a bare substring search, so the
    agent's own free-text observation content can't self-void the trial by
    mentioning an unrelated phrase (see the anchoring comment above
    ``_tool_missing_pattern``).

    Returns one of ``ok`` / ``failed`` / ``missing`` / ``sigkill`` / ``unknown``.
    ``unknown`` (no observation captured at all) is treated as non-degrading
    by callers — the pre-existing, more permissive behavior — since its
    absence is not positive evidence the toolchain was unavailable.
    """
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
    """Yield ``{step_id, tool_call_id, command, observation}`` for every Bash
    tool call. ``observation`` is the matching ``ObservationResult`` dict
    (joined via ``observation.results[].source_call_id == tool_call_id``,
    per Harbor's ATIF schema) or ``None`` if the step carries no observation
    for that call.
    """
    for step in trajectory.get("steps") or []:
        step_id = step.get("step_id")
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
            status = _classify_evidence_status(call["observation"], tool)
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


def resolve_trajectory_path(trial_dir_or_file: str | Path) -> Path:
    """Accept a trial dir, an ``agent/`` dir, or the trajectory.json itself."""
    p = Path(trial_dir_or_file)
    if p.is_file():
        return p
    candidates = [p / "agent" / "trajectory.json", p / "trajectory.json"]
    for c in candidates:
        if c.is_file():
            return c
    checked = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"no trajectory.json found under {p} (checked: {checked})")


def audit_trial(trial_dir_or_file: str | Path, arm: str) -> dict[str, Any]:
    """Load + audit a trial's trajectory. See ``audit_trajectory`` for the shape."""
    traj_path = resolve_trajectory_path(trial_dir_or_file)
    data = json.loads(traj_path.read_text())
    result = audit_trajectory(data, arm)
    result["trajectory_path"] = str(traj_path)
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
