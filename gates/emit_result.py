"""Gate 3 of the three-gate integrity pattern: validity class + score row.

Wraps a trial with a validity class and **refuses to emit a score row for an
invalid trial**. Validity is one of three mutually exclusive classes:
``valid`` (the audit gate found toolchain evidence and no infra-failure
signal), ``invalid-bypass`` (the trial completed but never invoked the arm's
toolchain -- not a scored failure of the arm, the trial never tested it), and
``invalid-infra`` (OOM, Docker daemon unreachable, bad model-auth env var, or
a toolchain that was never available to run -- outranks a bypass verdict).

Only ``valid`` trials get score/reward fields populated; invalid trials get
``score_emitted: false`` and no score fields, so a caller that naively sums a
job's rewards without checking ``validity_class`` cannot silently pool them.
Every record carries ``equipping_hash`` (gates/equipping.py) so results can
never be pooled across a different instruction/skill/image equipping.

See docs/gates.md#emit-result.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gates.audit import (
    AUDIT_SOURCE_STREAM,
    KNOWN_ARMS,
    TRANSCRIPT_NAME,
    audit_trial,
    resolve_step_names,
)
from gates.blast_radius import BlastRadiusUnavailable, from_artifacts_dir
from gates.equipping import compute_equipping_hash
from metrics.extract_signals import trial_signals

sys.path.insert(0, str(_REPO_ROOT / "generator"))
from split import spec_group  # noqa: E402

VALID = "valid"
INVALID_BYPASS = "invalid-bypass"
INVALID_INFRA = "invalid-infra"

# (kind, regex) — searched, in order, over the text of each candidate log
# file. First match wins. Patterns are deliberately specific phrases seen in
# real docker/Claude-Code-CLI/OOM output, not bare keywords like "error",
# so a trial's own instruction text or agent chatter mentioning "memory"
# doesn't misfire this classifier.
_INFRA_SIGNS: list[tuple[str, re.Pattern[str]]] = [
    ("oom", re.compile(r"oomkilled|out of memory|exit code (?:is )?137\b|exited \(137\)", re.IGNORECASE)),
    (
        "docker-daemon",
        re.compile(
            r"cannot connect to the docker daemon|docker daemon is not running|is the docker daemon running",
            re.IGNORECASE,
        ),
    ),
    (
        "env-auth",
        re.compile(
            r"anthropic_api_key.{0,40}not set|claude_code_oauth_token.{0,40}not set|"
            r"authentication_error|invalid api key|no auth credentials found|"
            r"credit balance is too low",
            re.IGNORECASE,
        ),
    ),
]

# Candidate log files relative to the trial dir, scanned in order. HARNESS-OWNED
# artifacts ONLY: adding the agent's own output streams
# (`agent/agent-output.txt`, `agent/claude-code.txt`) lets an agent self-void
# its trial by typing an _INFRA_SIGNS phrase, dropping a genuine failure out of
# the scored denominator. See docs/gates.md#emit-result.
_LOG_CANDIDATES = [
    "trial.log",
    "exception.txt",
    "result.json",
]


# --- multi-step trial-dir layout -------------------------------------------
#
# A multi-step trial moves `agent/`, `verifier/` and `artifacts/` into
# `steps/<name>/` after every step, so its trial dir has no top-level `agent/`
# or `verifier/` at all. Every helper below therefore checks the top-level path
# FIRST and falls back to `steps/<name>/...` only when it is absent, which is
# what keeps a single-step trial dir on its original path.
# `classify_infra_failure` needs no fallback: its logs are written once at trial
# level and never relocated. See docs/gates.md#emit-result.


def _step_verifier_dirs(trial_dir: str | Path) -> list[Path]:
    """Per-step ``steps/<name>/verifier/`` dirs in execution order.

    Empty list for a single-step trial dir. Both verifier-evidence readers
    below consume this REVERSED (last step first) -- see their docstrings for
    why the scoring step, not the first one, owns the published evidence.
    """
    trial_dir = Path(trial_dir)
    return [
        trial_dir / "steps" / name / "verifier" for name in resolve_step_names(trial_dir)
    ]


def _read_step_results(trial_dir: str | Path) -> Any:
    """``result.json``'s ``step_results``, or ``None`` when unavailable.

    ``None`` (not ``[]``) for "no result.json / unparseable / no such key", so
    "we cannot tell what the steps did" stays distinguishable from "the trial
    ran no steps".
    """
    result_path = Path(trial_dir) / "result.json"
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data.get("step_results")


def _step_aborted_unverified(step_result: Any) -> bool:
    """Harbor's OWN abort predicate for one ``StepResult``, verbatim.

    ``MultiStepTrial._should_stop_after_step`` (``harbor/trial/multi_step.py``):
    ``exception_info and not verifier_result``. A step carrying BOTH an
    exception and a ``verifier_result`` is not an abort -- Harbor keeps going
    and the step carries a real score. Single definition on purpose: every
    reader that asks "did this step start and die?" must ask it the same way,
    or the answers disagree.
    """
    if not isinstance(step_result, dict):
        return False
    return bool(step_result.get("exception_info")) and not step_result.get(
        "verifier_result"
    )


def _unverified_scoring_step(trial_dir: str | Path) -> str | None:
    """Name of the LAST started step iff it died before its verifier ran.

    ``None`` when the last step verified, when there are no steps, or when
    ``result.json`` cannot be read -- i.e. ``None`` means "no reason to
    distrust the usual evidence lookup".

    Harbor's ``_create_step_dirs`` makes ``steps/<name>/verifier/`` BEFORE the
    step runs and ``_archive_step_outputs`` runs even when ``_prepare_step``
    raised, so a step that died in its ``pre_invoke`` leaves a real-but-EMPTY
    verifier dir behind. A first-hit-wins scan over the step dirs would skip
    past it into step N-1's evidence and attribute an earlier step's tier
    verdict to the trial -- for ``tier1_not_verifiable``, a required
    published-row field filled from a step that was never scored. See
    ``_verifier_evidence_dirs``.

    An aborted last step whose ``step_name`` is missing or not a string yields
    ``""``, which matches no step dir: "the scoring step aborted and we cannot
    even name it" must still suppress the fallback, never re-enable it.
    """
    step_results = _read_step_results(trial_dir)
    if not isinstance(step_results, list) or not step_results:
        return None
    last = step_results[-1]
    if not _step_aborted_unverified(last):
        return None
    name = last.get("step_name") if isinstance(last, dict) else None
    return name if isinstance(name, str) else ""


def _verifier_evidence_dirs(trial_dir: str | Path) -> list[Path]:
    """Search order for the two verifier-evidence readers below.

    Top-level ``verifier/`` FIRST (a single-step trial dir must behave exactly
    as it did before multi-step existed), then the per-step dirs in REVERSE
    execution order: under the cdktn default ``multi_step_reward_strategy =
    "final"`` (DECISIONS.md Amendment 26) the published reward comes from the
    LAST step, so the evidence must describe the verification that actually
    produced the score.

    **Unless that last step never verified.** When Harbor's own abort predicate
    says the scoring step started and died (``_unverified_scoring_step``), the
    earlier steps are dropped from the search entirely: falling back to them
    would answer a question about the scored step with an unscored step's
    evidence. The readers then find nothing and return their honest
    "no evidence" value, which is the truth -- the trial has no verdict from
    the step whose verdict the row reports. The aborted step's own dir stays in
    the list (it is normally empty; if the abort happened after the verifier
    wrote something, that IS the scoring step's evidence).
    """
    trial_dir = Path(trial_dir)
    step_dirs = _step_verifier_dirs(trial_dir)
    unverified = _unverified_scoring_step(trial_dir)
    if unverified is not None:
        step_dirs = [d for d in step_dirs if d.parent.name == unverified]
    return [trial_dir / "verifier", *reversed(step_dirs)]


def classify_infra_failure(trial_dir: str | Path) -> dict[str, Any] | None:
    """Scan a trial dir's logs for an infra-failure signal.

    Returns ``{"kind", "file", "match"}`` on the first hit, or ``None`` if no
    known infra-failure phrase is found in any readable candidate log.
    """
    trial_dir = Path(trial_dir)
    for rel in _LOG_CANDIDATES:
        f = trial_dir / rel
        if not f.is_file():
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for kind, pattern in _INFRA_SIGNS:
            m = pattern.search(text)
            if m:
                return {"kind": kind, "file": rel, "match": m.group(0)[:200]}
    return None


def read_tier1_not_verifiable(trial_dir: str | Path) -> tuple[bool, str | None]:
    """Read the non-gating `/logs/verifier/tier1-not-verifiable` marker the
    generated verifier tees whenever a scenario's tier-1 `policy.rego`
    defines a `not_verifiable` rule that fired for this trial's plan
    (`tests/tiers.py`, emitted from `generator/verify_py.py`; the rule
    contract itself is `specs/SCHEMA.md` §4.2.1's option-3 bullet).

    Without this flag, a trial whose tier-1 action-allowlist was never
    actually checkable from plan JSON -- an entirely normal, idiomatic
    Terraform pattern: referencing another resource's provider-computed
    output -- is indistinguishable in the published data from one that WAS
    checked and passed. An identical wildcard-IAM violation scores 0.0 on
    `awscdk` (CFN synth is always fully static, so that arm has no
    plan-time-unknown gap) but 1.0 on the TF arms, with nothing in the row to
    show why.

    Host-side path is `<trial_dir>/verifier/tier1-not-verifiable`
    (`harbor/models/trial/paths.py`: `verifier_dir = trial_dir /
    "verifier"`, bind-mounted into the container at `/logs/verifier` --
    the exact same host/container path convention `classify_infra_failure`
    above already relies on for `/logs/agent`).

    Returns ``(present, detail)``: ``present`` is always a bool (``True``
    iff the marker file exists); ``detail`` is the marker's own text
    (already human-readable -- written by `tests/tiers.py`) when
    the file exists and is non-empty, else ``None``.

    Multi-step: the marker is relocated to
    `<trial_dir>/steps/<name>/verifier/tier1-not-verifiable`. Steps are
    searched in REVERSE execution order and the first hit wins, because the
    published reward comes from the LAST step under the cdktn default
    `multi_step_reward_strategy = "final"` (DECISIONS.md Amendment 26) -- the
    flag must describe the verification that actually produced the score, not
    an earlier one that has since been superseded. A single-step trial dir
    never reaches that branch.

    If the scoring step ABORTED before verifying, there is no fallback to an
    earlier step (`_verifier_evidence_dirs`) and this returns ``(False, None)``
    -- the same "no marker found" answer it gives any trial whose verifier left
    no marker, and the only honest one: the trial has no tier-1 verdict from
    the step its published reward comes from. Returning an earlier step's
    marker would put a never-scored step's flag on a required published-row
    field (`to_result_row`'s ``tier1_not_verifiable``).
    """
    for verifier_dir in _verifier_evidence_dirs(trial_dir):
        marker = verifier_dir / "tier1-not-verifiable"
        if not marker.is_file():
            continue
        try:
            text = marker.read_text(errors="replace").strip()
        except OSError:
            return True, None
        return True, (text or None)
    return False, None


# `  PASS [name]` / `  FAIL [name]: ...` -- the shape generator/gen.py's
# tests/ops.py::report() echoes for every tier-"0" structural_assert,
# captured by Harbor at `<trial_dir>/verifier/test-stdout.txt`. `[^\]]+` is safe
# because an assert name is generator-enforced kebab-case (specs/SCHEMA.md §4.2
# structural_asserts) and so contains no `]`.
_TIER0_ASSERT_LINE_RE = re.compile(r"^\s*(PASS|FAIL)\s*\[([^\]]+)\]", re.MULTILINE)

# `== summary: tier0_pass=N tier1_status=X ==` -- the last line the generated
# verifier (`tests/tiers.py`) prints before writing the reward. A toolchain step
# that failed first returns before this line runs, in which case tier1_status is
# reported absent below rather than guessed. Anchored to a WHOLE line: the same
# transcript carries tier-0 log lines and tier-1 `DENY:` messages that quote the
# artifact's own addresses, and an unanchored match would read a forged verdict
# out of one of those ahead of the real line.
_TIER1_SUMMARY_RE = re.compile(
    r"^== summary: tier0_pass=\d tier1_status=(\S+) ==\r?$", re.MULTILINE
)


def read_tier_evidence(trial_dir: str | Path) -> dict[str, Any] | None:
    """Read per-assert tier-0 PASS/FAIL evidence + the bundled tier-1
    verdict from `<trial_dir>/verifier/test-stdout.txt`, for the per-catch
    tier-attribution table (docs/prereg-iac-abstraction-benchmark.md's
    "per-tier catch attribution ... at what cost").

    Two different granularities, and this function is honest about which is
    which -- there is no third option available from the current oracle design
    (specs/SCHEMA.md §4.2 structural_asserts; `tests/tiers.py::tier_1`):

    - **tier-0 is per-catch-real**: each tier-"0" `structural_assert` is
      independently invoked and independently echoes its own PASS/FAIL
      (tests/ops.py::report, see `_TIER0_ASSERT_LINE_RE` above) -- this
      function returns the real per-assert-name verdict, keyed by
      `structural_assert.name` (specs/SCHEMA.md §4.2), under `"tier0"`.
    - **tier-1 is bundle-only**: every tier-"1" `structural_assert` for a
      given arm/scenario is graded by ONE `opa eval` call over the whole
      policy file (`tests/tiers.py::tier_1`),
      producing exactly one `tier1_status` for the WHOLE bundle -- there
      is no per-tier-1-assert breakdown to read, because the oracle itself
      never computes one -- the tier-1 assert *names* are recorded in the
      task's own `tests/verify.py` CONFIG (`tier1.asserts`) for a reader and
      never echoed to stdout at runtime. A
      tier-attribution table
      built from this data can therefore report "which tier-0 catch" a
      trial died on, or "the tier-1 bundle as a whole", but never "which
      individual tier-1 catch" -- callers (metrics/tokens_to_green.py)
      must treat all of a scenario/arm's tier-"1" catches as one unit.

    Returns ``None`` if `verifier/test-stdout.txt` doesn't exist (verifier
    never ran, or ran a test.sh that is not this generator's) -- never an
    empty dict,
    so a caller can distinguish "no evidence file at all" from "the file
    exists but a toolchain step failed before tier-0/1 ever ran" (the
    latter yields ``{"tier0": {}, "tier1_status": None}``, not ``None``).

    Multi-step: `verifier/` is relocated to
    `steps/<name>/verifier/`. Same reverse-order, first-hit-wins rule as
    `read_tier1_not_verifiable` and for the same reason -- the tier
    attribution must describe the verification that produced the published
    reward (the last step, under `multi_step_reward_strategy = "final"`), not
    an earlier step's. Per-step tier evidence for every step is a separate
    (not yet needed) metric; nothing is merged across steps here, because
    merging would silently claim an earlier step's tier-0 PASS as evidence
    about the step that was actually scored. For the same reason, a scoring
    step that aborted before verifying does not fall back to an earlier step
    (`_verifier_evidence_dirs`): this returns ``None``, exactly as it does for
    a trial whose verifier never ran at all -- which is what happened.
    """
    path = None
    for verifier_dir in _verifier_evidence_dirs(trial_dir):
        candidate = verifier_dir / "test-stdout.txt"
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None

    tier0: dict[str, str] = {}
    for m in _TIER0_ASSERT_LINE_RE.finditer(text):
        status, name = m.group(1), m.group(2)
        # Last occurrence wins. Defensive only: generator/gen.py enforces
        # assert-name uniqueness, so each name is echoed once per run.
        tier0[name] = status

    tier1_status: str | None = None
    summary_match = _TIER1_SUMMARY_RE.search(text)
    if summary_match:
        tier1_status = summary_match.group(1)

    return {"tier0": tier0, "tier1_status": tier1_status}


def extract_n_llm_calls(trial_dir: str | Path) -> int | None:
    """Count LLM calls from `<trial_dir>/agent/trajectory.json`, mirroring
    `aws_bench/metrics/run_data.py::_llm_usage_from_trajectory`'s own
    `n_llm_calls` accumulation exactly: for every step with
    `source == "agent"`, add `step.llm_call_count` when it's an int, else add 1
    iff `step.metrics` is present, else add 0. Needed for the pre-registered
    `iterations-to-green` metric (docs/prereg-iac-abstraction-benchmark.md).
    `result.json`'s `agent_result` never carries this field -- only
    `cost_usd`/`n_input_tokens`/`n_output_tokens`/`n_cache_tokens`
    (`_extract_score_fields` above) -- so only the trajectory has it.

    Deliberately dict-``.get``-only (no ATIF/harbor model import), same
    defensive posture as `_extract_score_fields`'s own docstring explains:
    the trajectory schema is a moving upstream target.

    Returns ``None`` -- NOT ``0`` -- when the trajectory file is absent,
    unreadable, malformed JSON, or has no top-level `steps` list at all:
    "unknown" and "zero" are different claims: a ``0`` here would enter
    ``iterations_to_green_km`` as an event at time 0.0, and one unparseable
    trajectory drags a whole cell's iterations quartile to zero. ``0`` is
    returned ONLY for a genuinely-parsed trajectory whose
    `steps` list is a real list (however short) but contains no
    agent-source step with either signal -- e.g. every synthetic
    gates/tests fixture trajectory, which is hand-authored for audit-gate
    testing and carries no per-step `metrics`/`llm_call_count` at all; that
    IS a real, known answer ("this trajectory really made zero countable
    LLM calls"), not a missing one.

    Multi-step: `agent/trajectory.json` is relocated to
    `steps/<name>/agent/trajectory.json`, one per step, each covering that step
    ALONE -- a fresh agent session per step (multi-step scenarios, DECISIONS.md
    Amendment 26).
    The trial's `n_llm_calls` is the CUMULATIVE sum across steps, matching the
    cumulative definition Amendment 26 pre-registers for tokens-to-green: a
    two-step trial's iterations-to-green is what it cost end to end, not what
    the last step cost. Per-step counts are additionally reported under the
    record's `steps` block by `build_result_record`.

    The `None`-not-`0` contract extends across steps: if ANY step's trajectory
    is missing, unreadable, malformed, or has no `steps` list, the whole sum
    is unknown and `None` is returned. A partial sum silently understates
    iterations-to-green, which is exactly the failure the `None` contract
    exists to prevent.
    """
    per_step = extract_n_llm_calls_per_step(trial_dir)
    if not per_step:
        return None
    values = list(per_step.values())
    if any(v is None for v in values):
        return None
    return sum(values)  # type: ignore[arg-type]


def _n_llm_calls_from_trajectory(path: Path) -> int | None:
    """`extract_n_llm_calls`'s per-file core. See that function's docstring."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    steps = data.get("steps")
    if not isinstance(steps, list):
        return None

    n_llm_calls = 0
    for step in steps:
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        llm_call_count = step.get("llm_call_count")
        if isinstance(llm_call_count, int) and not isinstance(llm_call_count, bool):
            n_llm_calls += llm_call_count
        elif step.get("metrics") is not None:
            n_llm_calls += 1
    return n_llm_calls


def _n_llm_calls_from_claude_code_stream(path: Path) -> int | None:
    """`_n_llm_calls_from_trajectory`'s counterpart for a step whose
    trajectory Harbor's converter rejected (see `gates/audit.py`'s transcript
    fallback and docs/upstream/harbor-trajectory-step-id-gap.md).

    Prefers the transcript's terminal ``result`` event's own ``num_turns`` --
    the same count harbor reports -- and falls back to the number of DISTINCT
    assistant message ids, which is one per LLM call (streaming repeats an id
    across chunks). The two differ (13 vs 15 on the awscdk trial that motivated
    this), so the harness's own number wins wherever it exists.

    Returns ``None`` when the transcript is absent, unreadable, or carries
    neither signal -- the `None`-not-`0` contract `extract_n_llm_calls`
    documents.
    """
    if not path.is_file():
        return None
    message_ids: list[str] = []
    num_turns: int | None = None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            turns = event.get("num_turns")
            if isinstance(turns, int) and not isinstance(turns, bool):
                num_turns = turns
        elif event.get("type") == "assistant":
            message = event.get("message")
            if isinstance(message, dict):
                mid = message.get("id")
                if isinstance(mid, str) and mid not in message_ids:
                    message_ids.append(mid)
    if num_turns is not None:
        return num_turns
    return len(message_ids) or None


def _n_llm_calls_from_agent_dir(agent_dir: Path) -> int | None:
    """One step's LLM-call count from whichever file the audit gate would read
    for it: the ATIF trajectory, else the stream transcript beside it."""
    trajectory = agent_dir / "trajectory.json"
    if trajectory.is_file():
        return _n_llm_calls_from_trajectory(trajectory)
    return _n_llm_calls_from_claude_code_stream(agent_dir / TRANSCRIPT_NAME)


def extract_n_llm_calls_per_step(trial_dir: str | Path) -> dict[str, int | None]:
    """LLM-call counts keyed by trial phase, in execution order.

    Single-step trial dir: ``{"trial": <n>}`` (or ``{}`` when the agent dir
    holds neither a trajectory nor a transcript). Multi-step: one entry per step
    dir, keyed by step name, value ``None`` for a step whose trajectory is
    missing/unreadable/malformed and whose transcript gives no count either.

    A step Harbor left without a trajectory is counted from its
    ``agent/claude-code.txt`` instead, the same fallback and the same per-step
    resolution the audit gate uses (``gates.audit.resolve_audit_sources``).

    Deliberately keyed rather than a bare list: a caller attributing
    iterations-to-green to a step needs the step's NAME, and the aborted-trial
    case (a `min_reward` gate stopping the run after step 1) shows up here as
    a shorter dict rather than as a silently smaller number.
    """
    trial_dir = Path(trial_dir)
    root = trial_dir / "agent"
    if (root / "trajectory.json").is_file() or (root / TRANSCRIPT_NAME).is_file():
        return {"trial": _n_llm_calls_from_agent_dir(root)}

    step_names = resolve_step_names(trial_dir)
    if not step_names:
        return {}
    return {
        name: _n_llm_calls_from_agent_dir(trial_dir / "steps" / name / "agent")
        for name in step_names
    }


def resolve_split_group(spec_id: str | None) -> str:
    """``generator/split.py::spec_group``, resolved to the schema's
    three-value enum (``"train"|"holdout"|"unclassified"``) required on
    every published result row (``metrics/result_schema.json``'s
    ``split_group``). Without it on the row, the train/holdout split is
    unenforceable at the layer that matters -- the published number.

    ``spec_id`` here is the SPEC id (e.g. ``"apigw-openapi"`` --
    ``generator/gen.py``'s ``Spec.id`` / ``specs/<id>.yaml``'s filename
    stem, what ``specs/split.yaml`` actually keys on), which is NOT the
    same string as this schema's own ``scenario``/``task`` row fields
    (those name the aws-bench SCENARIO shard, ``"anchor"`` or ``"anchor-k"``, and the
    Harbor task name respectively) -- callers must pass it explicitly
    (``build_result_record``/``to_result_row``'s own ``spec_id=`` kwarg,
    or ``--spec-id`` on this module's CLI), not derive it from either.

    Never raises: no ``spec_id``, no ``specs/split.yaml`` yet, or a
    ``spec_id`` with no entry in it all map to ``"unclassified"`` -- the
    same "not yet classified, don't guess a side" contract
    ``spec_group()`` itself documents for its own ``None`` return.
    """
    if not spec_id:
        return "unclassified"
    try:
        group = spec_group(spec_id)
    except FileNotFoundError:
        return "unclassified"
    return group or "unclassified"


def read_budget(jobs_dir: str | Path | None) -> tuple[int | None, int | None]:
    """Read ``<jobs_dir>/budget.json`` (``scripts/run-bench.sh``'s own output;
    that script's header carries the "MAX_ITERS feedback cycles or MAX_TOKENS
    per trajectory, whichever first" budget-cap contract) and return
    ``(max_iters, max_tokens)``.

    This is the ONLY reader of budget.json. Without it every emitted row's
    ``censored`` is ``False`` regardless of budget and ``n_budget_censored`` is
    structurally always 0. ``main()``'s ``--jobs-dir`` flag is the call site.

    Returns ``(None, None)`` if ``jobs_dir`` is falsy, the file doesn't
    exist, isn't valid JSON, isn't a JSON object, or a key is JSON
    ``null``/absent/non-integer — never raises, so a missing/malformed
    budget.json degrades to "no budget known" (auto-censoring becomes a
    no-op, matching ``to_result_row``'s own documented default) rather
    than crashing row emission.
    """
    if not jobs_dir:
        return None, None
    path = Path(jobs_dir) / "budget.json"
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    def _int_or_none(v: Any) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    return _int_or_none(data.get("max_iters")), _int_or_none(data.get("max_tokens"))


def _as_number(value: Any) -> float | None:
    """Mirrors ``aws_bench/metrics/run_data.py``'s own ``_as_number`` exactly
    (bool excluded even though ``bool`` is an ``int`` subclass; NaN rejected)
    so this gate's reward coercion agrees with upstream's."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN
            return None
        return f
    return None


def _coerce_reward(rewards: Any) -> float | None:
    """Unwrap Harbor's real ``VerifierResult.rewards`` shape.

    Harbor's schema is ``dict[str, float | int] | None``
    (``harbor/models/verifier/result.py``), read by upstream aws-bench as
    ``rewards.get("reward")``, falling back to the first numeric value if
    the ``"reward"`` key itself is absent (``aws_bench/metrics/run_data.py``
    ``TrialData.reward``). Mirrored here so a real Harbor ``result.json`` maps
    to a schema-valid numeric ``reward``. A bare scalar -- defensive fallback
    for any non-dict shape a future/older producer might emit -- is coerced the
    same way.
    """
    if isinstance(rewards, dict):
        n = _as_number(rewards.get("reward"))
        if n is not None:
            return n
        for value in rewards.values():
            n = _as_number(value)
            if n is not None:
                return n
        return None
    return _as_number(rewards)


def _aggregate_step_tokens(step_results: Any) -> dict[str, Any]:
    """Sum token/cost fields across ``step_results[].agent_result``.

    Mirrors ``TrialResult.compute_token_cost_totals()``
    (``harbor/models/trial/result.py``): multi-step trials never set the
    top-level ``agent_result`` and instead record one ``AgentContext`` per
    step on ``step_results[i].agent_result`` — the caller only reaches here
    when the top-level field was absent, exactly matching that method's own
    branch order.
    """
    out: dict[str, Any] = {"cost_usd": None, "n_input_tokens": None, "n_output_tokens": None, "n_cache_tokens": None}
    if not isinstance(step_results, list):
        return out
    contexts = [
        sr.get("agent_result")
        for sr in step_results
        if isinstance(sr, dict) and isinstance(sr.get("agent_result"), dict)
    ]
    for ctx in contexts:
        if ctx.get("n_input_tokens") is not None:
            out["n_input_tokens"] = (out["n_input_tokens"] or 0) + ctx["n_input_tokens"]
        if ctx.get("n_cache_tokens") is not None:
            out["n_cache_tokens"] = (out["n_cache_tokens"] or 0) + ctx["n_cache_tokens"]
        if ctx.get("n_output_tokens") is not None:
            out["n_output_tokens"] = (out["n_output_tokens"] or 0) + ctx["n_output_tokens"]
        if ctx.get("cost_usd") is not None:
            out["cost_usd"] = (out["cost_usd"] or 0.0) + ctx["cost_usd"]
    return out


def _step_token_breakdown(step_results: Any) -> list[dict[str, Any]]:
    """Per-step token/cost rows, in ``result.json`` order.

    The trial-level totals `_aggregate_step_tokens` produces are the SUM of
    these; keeping the addends visible lets a cumulative tokens-to-green be
    computed downstream without re-reading result.json (DECISIONS.md
    Amendment 26 defines it as the cumulative sum of per-step agent output
    tokens up to and including the step at which the final oracle first passes).
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(step_results, list):
        return rows
    for step_result in step_results:
        if not isinstance(step_result, dict):
            continue
        ctx = step_result.get("agent_result")
        ctx = ctx if isinstance(ctx, dict) else {}
        verifier_result = step_result.get("verifier_result") or {}
        rewards = verifier_result.get("rewards") if isinstance(verifier_result, dict) else None
        rows.append(
            {
                "step_name": step_result.get("step_name"),
                "reward": _coerce_reward(rewards) if rewards is not None else None,
                "cost_usd": ctx.get("cost_usd"),
                "n_input_tokens": ctx.get("n_input_tokens"),
                "n_output_tokens": ctx.get("n_output_tokens"),
                "n_cache_tokens": ctx.get("n_cache_tokens"),
                "exception_type": (step_result.get("exception_info") or {}).get("exception_type")
                if isinstance(step_result.get("exception_info"), dict)
                else None,
            }
        )
    return rows


def _count_failed_steps(step_results: Any) -> int:
    """Steps that started and died, by Harbor's own abort predicate.

    ``_step_aborted_unverified`` is that predicate
    (``MultiStepTrial._should_stop_after_step``, verbatim). This number's job is
    to say "Harbor would have aborted here", so any drift from that predicate
    makes it lie. A step with BOTH an exception and a verifier_result does not
    count: Harbor keeps going, and the step carries a real score.
    """
    if not isinstance(step_results, list):
        return 0
    return sum(1 for step_result in step_results if _step_aborted_unverified(step_result))


class TaskTomlUnreadable(ValueError):
    """``<task_dir>/task.toml`` is absent, unreadable or malformed.

    Raised by the single loader below so every caller decides for itself
    whether that is fatal; nothing in this module parses task.toml twice.
    """


def _load_task_toml(task_dir: str | Path) -> dict[str, Any]:
    """``<task_dir>/task.toml``, parsed. The only parser of that file in this
    module -- two parsers of one file can disagree after a schema change.

    Raises TaskTomlUnreadable when it is absent, unreadable or malformed.
    """
    path = Path(task_dir) / "task.toml"
    if not path.is_file():
        raise TaskTomlUnreadable(f"{path} does not exist")
    try:
        return tomllib.loads(path.read_text(errors="replace"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TaskTomlUnreadable(f"{path} is unreadable/malformed ({exc})") from exc


def _step_names(data: dict[str, Any]) -> list[str]:
    """The ``[[steps]]`` names declared by a parsed task.toml (``[]`` when it
    declares none)."""
    steps = data.get("steps")
    if not isinstance(steps, list):
        return []
    return [s.get("name") for s in steps if isinstance(s, dict)]


def _declared_step_names(task_dir: str | Path) -> list[str] | None:
    """Step names declared by ``<task_dir>/task.toml``'s ``[[steps]]``.

    ``None`` (not ``[]``) when task.toml is absent/unreadable/malformed, so
    "we could not tell how many steps were declared" stays distinguishable
    from "the task declares no steps".
    """
    try:
        return _step_names(_load_task_toml(task_dir))
    except TaskTomlUnreadable:
        return None


GREENFIELD = "greenfield"
BROWNFIELD = "brownfield"
MULTI_STEP = "multi-step"
MULTI_STEP_BROWNFIELD = "multi-step-brownfield"
PRE_CONFIGURED_ACCOUNT = "pre-configured-account"
PRE_CONFIGURED_ACCOUNT_BROWNFIELD = "pre-configured-account-brownfield"

# The seeded (brownfield) variant of each unseeded base form. Seeding is
# independent of step shape, so it rides in the label rather than replacing the
# base: a seeded row must never share a cell with an unseeded one (DECISIONS.md
# Amendment 36, scenario_form as a required, never-pooled row field).
_BROWNFIELD_OF = {
    GREENFIELD: BROWNFIELD,
    MULTI_STEP: MULTI_STEP_BROWNFIELD,
    PRE_CONFIGURED_ACCOUNT: PRE_CONFIGURED_ACCOUNT_BROWNFIELD,
}


class ScenarioFormUndeterminable(ValueError):
    """The task dir carries nothing to derive ``scenario_form`` from.

    Raised rather than defaulted: ``greenfield`` is the most-pooled form, so a
    silent default would pool an unlabelled row into the headline number the
    forms exist to keep apart.
    """


def derive_scenario_form(task_dir: str | Path) -> str:
    """The row's ``scenario_form`` (metrics/result_schema.json), from the task
    directory alone -- never guessed from a spec id.

    Base, most specific first:

    1. ``pre-configured-account`` -- some ``steps/<name>/pre_invoke/pre_invoke.sh``
       exists (specs/SCHEMA.md §2.6: the harness deploys prior-step work into
       the account before that step's agent runs). It outranks ``multi-step``
       because it occurs only on a multi-step task and refines the same
       dimension rather than adding a second one. The brownfield seed script at
       ``<task_dir>/pre_invoke/pre_invoke.sh`` (§2.7.1) is not matched here.
    2. ``multi-step`` -- ``task.toml`` declares ``[[steps]]``. Its own stratum
       because a multi-step trial's tokens-to-green is the cumulative
       across-steps sum, so N-step and 1-step tasks are not comparable on it.
    3. ``greenfield`` -- neither.

    ``[metadata] workspace_seed_sha256`` appends a ``-brownfield`` suffix rather
    than replacing the base: seeding is independent of step shape and a task may
    be both. On the ``greenfield`` base the label is plain ``brownfield``.

    Raises ScenarioFormUndeterminable when ``task.toml`` is absent or malformed:
    it is the only evidence and the form is never defaulted.

    Reasoning: DECISIONS.md Amendment 36, scenario_form as a required row field
    whose forms are never pooled.
    """
    task_dir = Path(task_dir)
    try:
        data = _load_task_toml(task_dir)
    except TaskTomlUnreadable as exc:
        raise ScenarioFormUndeterminable(
            f"derive_scenario_form: {exc} -- scenario_form is derivable only "
            "from the task dir and is never defaulted"
        ) from exc

    if any((task_dir / "steps").glob("*/pre_invoke/pre_invoke.sh")):
        base = PRE_CONFIGURED_ACCOUNT
    elif _step_names(data):
        base = MULTI_STEP
    else:
        base = GREENFIELD

    metadata = data.get("metadata")
    seeded = isinstance(metadata, dict) and bool(metadata.get("workspace_seed_sha256"))
    return _BROWNFIELD_OF[base] if seeded else base


def read_step_summary(trial_dir: str | Path, task_dir: str | Path) -> dict[str, Any] | None:
    """Per-step diagnostics for a multi-step trial, or ``None`` if single-step.

    Harbor's ``min_reward`` green gate aborts the remaining steps by
    RETURNING, recording the failure on the
    ``StepResult`` and never on ``TrialResult.exception_info``. So a trial that
    ran half its steps and stopped looks, to every top-level reader, exactly
    like a clean trial -- including this gate's own validity classification.
    ``n_started`` vs ``n_declared``, ``n_failed``, and ``aborted_early`` are
    the signals that distinguish them.

    Counting is subtle enough to spell out, because the obvious reading is
    wrong. Harbor appends the ``StepResult`` BEFORE running the step
    (``harbor/trial/multi_step.py``), so ``len(step_results)`` counts steps
    *started*, not steps *finished* -- a step that died in ``_prepare_step`` (a
    harness ``pre_invoke`` deploy that failed) is still in the list. Hence
    ``n_started``, never ``n_completed``: when the failing step is the LAST
    declared one -- exactly
    where the design puts the harness deploy of the prior step's work —
    ``n_started == n_declared`` and a purely arithmetic ``aborted_early`` would
    read ``False`` for a trial whose final step never ran an agent.

    So ``aborted_early`` also fires on ``n_failed``, using Harbor's OWN abort
    predicate verbatim (``_should_stop_after_step``: ``exception_info and not
    verifier_result``). A step carrying ``exception_info`` *with* a
    ``verifier_result`` is deliberately NOT counted: Harbor does not stop for
    it, the step was scored, and the trial genuinely continued.

    Returns ``None`` for a single-step trial dir, which is what keeps every
    existing single-step record byte-identical.
    """
    trial_dir = Path(trial_dir)
    names = resolve_step_names(trial_dir)

    step_results: Any = _read_step_results(trial_dir)

    if not names and not isinstance(step_results, list):
        return None

    declared = _declared_step_names(task_dir)
    n_started = len(step_results) if isinstance(step_results, list) else len(names)
    n_declared = len(declared) if declared is not None else None
    n_failed = _count_failed_steps(step_results)

    return {
        "names": names,
        "n_started": n_started,
        "n_declared": n_declared,
        "n_failed": n_failed,
        # Two independent ways a trial can fail to run its declared program:
        # steps MISSING from the tail (we know both numbers and they
        # disagree), or a step that started and died. The second is the only
        # signal when the LAST declared step is the one that failed.
        "aborted_early": (n_declared is not None and n_started < n_declared) or n_failed > 0,
        "per_step": _step_token_breakdown(step_results),
        "n_llm_calls_per_step": extract_n_llm_calls_per_step(trial_dir),
    }


def _tokens_from_claude_code_stream(agent_dir: Path) -> dict[str, Any] | None:
    """Recover token totals from ``agent/claude-code.txt`` (Claude Code's
    ``--output-format stream-json`` transcript) when ``result.json`` carries
    none.

    Harbor's ``AgentContext`` token fields are filled only if its trajectory
    conversion succeeds; a conversion that fails validation (e.g.
    ``steps[N].step_id: expected N+1, got N+2`` on a step-id gap) leaves every
    field ``None`` while the transcript on disk is complete. The transcript's
    terminal ``{"type": "result", ...}`` event carries the session totals
    harbor itself reports — per-message ``usage`` entries are streaming
    partials and must NOT be summed:

      n_input_tokens  = usage.input_tokens + cache_read_input_tokens + cache_creation_input_tokens
      n_cache_tokens  = usage.cache_read_input_tokens
      n_output_tokens = usage.output_tokens
      cost_usd        = total_cost_usd

    Returns ``None`` when the transcript or its result event is absent.
    """
    path = Path(agent_dir) / "claude-code.txt"
    if not path.is_file():
        return None
    result_event: dict[str, Any] | None = None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{") or '"result"' not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            result_event = ev
    if result_event is None or not isinstance(result_event.get("usage"), dict):
        return None
    u = result_event["usage"]
    cached = int(u.get("cache_read_input_tokens") or 0)
    return {
        "n_input_tokens": int(u.get("input_tokens") or 0) + cached + int(u.get("cache_creation_input_tokens") or 0),
        "n_cache_tokens": cached,
        "n_output_tokens": int(u.get("output_tokens") or 0),
        "cost_usd": result_event.get("total_cost_usd"),
    }


def _recover_tokens_from_transcripts(trial_dir: Path, out: dict[str, Any]) -> None:
    """Fill ``None`` token fields in ``out`` from the on-disk transcript(s):
    ``agent/`` for a single-step trial, the sum over ``steps/*/agent/`` for a
    multi-step one. Records ``tokens_source = "claude-code-stream"`` so a row
    built this way is distinguishable from one harbor priced itself."""
    if out.get("n_output_tokens") is not None:
        return
    agent_dirs = [trial_dir / "agent"]
    steps_dir = trial_dir / "steps"
    if steps_dir.is_dir():
        agent_dirs = [d / "agent" for d in sorted(steps_dir.iterdir()) if (d / "agent").is_dir()]
    totals = [t for t in (_tokens_from_claude_code_stream(d) for d in agent_dirs) if t]
    if not totals:
        return
    for key in ("n_input_tokens", "n_cache_tokens", "n_output_tokens"):
        out[key] = sum(t[key] for t in totals)
    costs = [t["cost_usd"] for t in totals if t.get("cost_usd") is not None]
    out["cost_usd"] = sum(costs) if costs else out.get("cost_usd")
    out["tokens_source"] = "claude-code-stream"


ARTIFACTS_DIRNAME = "artifacts"


def read_blast_radius(trial_dir: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(blast_radius, unavailable_reason)`` -- exactly one of the two is None.

    Reads the plan (or synthesized template) the verifier persisted into
    ``/logs/artifacts``, which harbor collects into the trial's own
    ``artifacts/`` (``harbor/models/trial/paths.py``, the convention directory).
    A trial run before the verifier persisted it has an empty ``artifacts/`` and
    yields ``(None, reason)``: the field is not computable after the fact from
    anything else the trial kept, and saying so is the whole point of the reason
    string. See gates/blast_radius.py for what each source carries.

    Multi-step: the FINAL step's artifacts, which is the change the row's reward
    is attributed to, with earlier steps tried only if the final one persisted
    nothing.
    """
    trial_dir = Path(trial_dir)
    steps = resolve_step_names(trial_dir)
    dirs = (
        [trial_dir / "steps" / name / ARTIFACTS_DIRNAME for name in reversed(steps)]
        if steps
        else [trial_dir / ARTIFACTS_DIRNAME]
    )
    reasons: list[str] = []
    for artifacts in dirs:
        if not artifacts.is_dir():
            reasons.append(f"no {artifacts.relative_to(trial_dir)}/ in this trial dir")
            continue
        try:
            radius, path = from_artifacts_dir(artifacts)
        except BlastRadiusUnavailable as exc:
            reasons.append(str(exc))
            continue
        radius["artifact"] = str(path.relative_to(trial_dir))
        return radius, None
    return None, "; ".join(reasons) or "no artifacts directory in this trial dir"


def read_rbw_and_escape_hatch(trial_dir: str | Path, arm: str) -> dict[str, Any]:
    """``{"rbw": ..., "escape_hatch": ...}``, both None when the trial left no
    session transcript for metrics/extract_signals.py to scan.

    Emitted at gate time rather than extracted post-hoc, so the published row
    carries the profile columns (ROADMAP "a profile, not a scalar") instead of
    requiring a second pass over a job dir that may no longer exist.
    """
    try:
        signals = trial_signals(trial_dir, arm)
    except OSError as exc:
        return {"rbw": None, "escape_hatch": None, "signals_error": str(exc)}
    if signals is None:
        return {
            "rbw": None,
            "escape_hatch": None,
            "signals_error": "no agent/sessions/**/*.jsonl transcript in this trial dir",
        }
    return signals


def _extract_score_fields(trial_dir: Path) -> dict[str, Any]:
    """Best-effort reward/token/cost extraction from the harbor-level result.json.

    Deliberately defensive (``.get`` everywhere, no schema import): the
    harbor-level ``TrialResult`` schema (``harbor/models/trial/result.py``)
    is a moving upstream target and gates/ shouldn't hard-fail just because a
    field it doesn't strictly need moved. Absence of a field here is not
    itself evidence of an invalid trial — see ``classify_infra_failure`` /
    ``audit_trial`` for the fields that actually gate validity.

    ``reward`` is unwrapped from Harbor's real ``rewards: dict[str, float |
    int]`` shape (``_coerce_reward``); ``n_*_tokens``/``cost_usd`` come from
    the top-level ``agent_result`` when present, else are aggregated across
    ``step_results[].agent_result`` (``_aggregate_step_tokens``) — the same
    two branches ``TrialResult.compute_token_cost_totals()`` takes, so a
    multi-step trial's tokens are never silently reported as 0.
    """
    result_path = trial_dir / "result.json"
    out: dict[str, Any] = {
        "result_json_found": result_path.is_file(),
        "reward": None,
        "cost_usd": None,
        "n_input_tokens": None,
        "n_output_tokens": None,
        "n_cache_tokens": None,
    }
    if not result_path.is_file():
        return out
    try:
        data = json.loads(result_path.read_text())
    except json.JSONDecodeError:
        out["result_json_parse_error"] = True
        return out

    verifier_result = data.get("verifier_result") or {}
    if "rewards" in verifier_result:
        out["reward"] = _coerce_reward(verifier_result["rewards"])

    agent_result = data.get("agent_result")
    if isinstance(agent_result, dict) and agent_result:
        for key in ("cost_usd", "n_input_tokens", "n_output_tokens", "n_cache_tokens"):
            if key in agent_result:
                out[key] = agent_result[key]
    else:
        out.update(_aggregate_step_tokens(data.get("step_results")))

    _recover_tokens_from_transcripts(trial_dir, out)
    return out


def build_result_record(
    trial_dir: str | Path,
    arm: str,
    task_dir: str | Path,
    image_ref: str,
    extra_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one trial and, iff valid, attach its score fields.

    Always attaches ``equipping_hash`` (best-effort — a failure to compute it,
    e.g. a missing ``instruction.md`` under ``task_dir``, is recorded as
    ``equipping_hash: null`` + ``equipping_hash_error`` rather than raised,
    so a broken equipping input never masquerades as "gate didn't run").
    """
    trial_dir = Path(trial_dir)
    if not trial_dir.is_dir():
        raise FileNotFoundError(f"trial_dir does not exist or is not a directory: {trial_dir}")

    infra = classify_infra_failure(trial_dir)

    audit: dict[str, Any] | None
    audit_error: str | None
    try:
        audit = audit_trial(trial_dir, arm)
        audit_error = None
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        audit = None
        audit_error = str(exc)

    if infra is not None:
        validity_class = INVALID_INFRA
        reason = f"infra failure detected: {infra['kind']} (in {infra['file']}: {infra['match']!r})"
    elif audit is None:
        # Can't even audit the trial (no trajectory, bad arm, corrupt JSON) —
        # treat as infra-invalid: this is a harness/plumbing problem, not
        # evidence the agent chose to bypass the toolchain.
        validity_class = INVALID_INFRA
        reason = f"could not audit trial (treated as infra failure): {audit_error}"
        infra = {"kind": "audit-unavailable", "file": None, "match": audit_error}
    elif audit.get("degraded"):
        # The audit gate matched the arm's toolchain (the agent DID try it, so
        # not a bypass) but every matched call shows the tool was never
        # available to run: exit 127 command-not-found, or exit 137 SIGKILL.
        # A degraded arm, not an agent choice -- invalid-infra, even though no
        # log-file infra signal fired.
        validity_class = INVALID_INFRA
        reason = audit["reason"]
        infra = {
            "kind": f"toolchain-{audit['degraded_kind']}",
            "file": "agent/trajectory.json",
            "match": audit["reason"],
        }
    elif not audit["valid"]:
        validity_class = INVALID_BYPASS
        reason = audit["reason"]
    else:
        validity_class = VALID
        reason = audit["reason"]

    try:
        equipping_hash: str | None = compute_equipping_hash(task_dir, image_ref, extra_cfg or {})
        equipping_hash_error = None
    # ValueError: compute_equipping_hash refuses a caller-supplied
    # `workspace_seed_sha256` contradicting the one task.toml declares
    # (brownfield seeds, specs/SCHEMA.md §2.7). Recorded like every other
    # equipping-input failure, so a contradictory seed never masquerades as
    # "gate didn't run" and never as a valid hash.
    except (FileNotFoundError, TypeError, ValueError) as exc:
        equipping_hash = None
        equipping_hash_error = str(exc)

    # Recorded best-effort, exactly like equipping_hash above: an underivable
    # form is carried as null plus an error string here and refused by
    # to_result_row, so it can never reach a published row as a default.
    try:
        scenario_form: str | None = derive_scenario_form(task_dir)
        scenario_form_error = None
    except ScenarioFormUndeterminable as exc:
        scenario_form = None
        scenario_form_error = str(exc)

    tier1_not_verifiable, tier1_not_verifiable_detail = read_tier1_not_verifiable(trial_dir)
    tier_evidence = read_tier_evidence(trial_dir)
    blast_radius, blast_radius_unavailable = read_blast_radius(trial_dir)
    signals = read_rbw_and_escape_hatch(trial_dir, arm)

    record: dict[str, Any] = {
        "trial_dir": str(trial_dir),
        "arm": arm,
        "task_dir": str(task_dir),
        "image_ref": image_ref,
        "validity_class": validity_class,
        "valid": validity_class == VALID,
        "reason": reason,
        "equipping_hash": equipping_hash,
        "scenario_form": scenario_form,
        "audit": audit,
        "infra": infra,
        # Always attached regardless of validity_class (same reasoning as
        # audit/infra above) -- present/absent is a fact about the trial's
        # own logs, independent of whether the trial's toolchain use
        # audited as genuine.
        "tier1_not_verifiable": tier1_not_verifiable,
        "tier1_not_verifiable_detail": tier1_not_verifiable_detail,
        # Per-catch tier-attribution evidence (read_tier_evidence's docstring
        # has the tier-0-real / tier-1-bundle-only caveat). Attached regardless
        # of validity_class: a bypassed/infra-invalid trial's verifier may still
        # have left evidence from a prior static-tier run in the same
        # container, and its presence is itself diagnostic.
        "tier_evidence": tier_evidence,
        # The profile columns, attached regardless of validity_class for the
        # same reason as tier_evidence: what the agent read before it wrote, and
        # what the change would move, are facts about the trial's own logs.
        "blast_radius": blast_radius,
        "rbw": signals["rbw"],
        "escape_hatch": signals["escape_hatch"],
    }
    if blast_radius_unavailable is not None:
        record["blast_radius_unavailable"] = blast_radius_unavailable
    if signals.get("signals_error") is not None:
        record["signals_error"] = signals["signals_error"]
    # Provenance, present only when the audit fell back to the stream
    # transcript because harbor's converter left the step without a trajectory
    # (gates/audit.py, docs/upstream/harbor-trajectory-step-id-gap.md). Absent
    # means the ATIF trajectory was read, so every pre-existing record is
    # unchanged.
    if audit is not None and audit.get("audit_source") == AUDIT_SOURCE_STREAM:
        record["audit_source"] = AUDIT_SOURCE_STREAM
    if equipping_hash_error is not None:
        record["equipping_hash_error"] = equipping_hash_error
    if scenario_form_error is not None:
        record["scenario_form_error"] = scenario_form_error

    # Multi-step only, attached regardless of validity_class -- an aborted or
    # infra-invalid trial is when "how far did it get" matters most. The
    # published row (metrics/result_schema.json, additionalProperties: false) is
    # deliberately NOT extended: its shape is pre-registered, so a multi-step
    # field would be a schema-version bump.
    step_summary = read_step_summary(trial_dir, task_dir)
    if step_summary is not None:
        record["steps"] = step_summary

    if validity_class != VALID:
        # The refusal: no score fields at all for an invalid trial.
        record["score_emitted"] = False
        return record

    record["score_emitted"] = True
    record.update(_extract_score_fields(trial_dir))
    record["n_llm_calls"] = extract_n_llm_calls(trial_dir)
    return record


# Must match metrics/result_schema.json's "schema_version" const exactly.
RESULT_ROW_SCHEMA_VERSION = "1.1"


def to_result_row(
    record: dict[str, Any],
    *,
    model: str,
    harness: str,
    oracle_version: str,
    censored: bool | None = None,
    max_iters: int | None = None,
    max_tokens: int | None = None,
    scenario: str | None = None,
    task: str | None = None,
    trial_id: str | None = None,
    job_id: str | None = None,
    spec_id: str | None = None,
) -> dict[str, Any]:
    """Map a ``build_result_record()`` record + run config into a
    ``metrics/result_schema.json``-shaped published result row.

    This is the schema's only producer: without it ``result_schema.json``
    validates nothing but a hand-authored example, and a required field can be
    silently absent from every published result JSON.
    ``metrics/emit_fixture_rows.py`` exercises this function against the gate
    fixtures and validates the output.

    Only ``valid`` records carry meaningful reward/token fields
    (``score_emitted`` is False otherwise, per ``build_result_record``'s
    refusal contract) — for a non-``valid`` record, tokens/reward are
    schema-required but not meaningful, so they're filled with 0/0.0 and
    ``validity_reason`` is set; callers must read ``validity_class`` first,
    exactly as the schema's own field description says.

    ``censored`` (the pre-registered budget cap,
    docs/prereg-iac-abstraction-benchmark.md): pass an explicit
    ``True``/``False`` when the caller already knows it, e.g. from a job-level
    budget-tracking pass. Leaving it ``None`` (the default) triggers
    auto-detection from ``max_iters``/``max_tokens``, mirroring
    ``scripts/run-bench.sh``'s ``budget.json`` contract of "MAX_ITERS feedback
    cycles or MAX_TOKENS per trajectory, whichever first": a trial that did NOT
    reach reward 1.0 and met/exceeded either ``max_tokens`` (by
    ``tokens_total``) or ``max_iters`` (by ``record["n_llm_calls"]``, when
    known) is censored=True. Passing neither makes auto-detection a no-op and
    ``censored`` comes out ``False``.

    ``spec_id``: the spec id (``"apigw-openapi"``), NOT the
    ``scenario``/``task`` schema fields' aws-bench meanings -- see
    ``resolve_split_group``. Used to resolve the schema-REQUIRED
    ``split_group`` field. Omitting it cannot skip that field (the schema
    requires it on every row); it resolves to ``"unclassified"`` instead, so a
    caller that forgets gets an honestly-labeled row, not a silently
    train/holdout-mislabeled one.
    """
    if record.get("equipping_hash") is None:
        raise ValueError(
            "to_result_row: record has no equipping_hash "
            f"({record.get('equipping_hash_error', 'unknown reason')}) — "
            f"a published result row requires one."
        )
    if record.get("scenario_form") is None:
        raise ValueError(
            "to_result_row: record has no scenario_form "
            f"({record.get('scenario_form_error', 'unknown reason')}) — "
            "a published result row requires one; rows of different scenario "
            "forms are never pooled, so it is never defaulted."
        )

    tokens_input = record.get("n_input_tokens") or 0
    tokens_output = record.get("n_output_tokens") or 0
    tokens_cached = record.get("n_cache_tokens")
    tokens_total = tokens_input + tokens_output + (tokens_cached or 0)
    reward = record.get("reward")
    if reward is None:
        reward = 0.0

    if censored is None:
        n_llm_calls = record.get("n_llm_calls")
        censored = reward < 1.0 and (
            (max_tokens is not None and tokens_total >= max_tokens)
            or (max_iters is not None and n_llm_calls is not None and n_llm_calls >= max_iters)
        )

    row: dict[str, Any] = {
        "schema_version": RESULT_ROW_SCHEMA_VERSION,
        "equipping_hash": record["equipping_hash"],
        "scenario_form": record["scenario_form"],
        "oracle_version": oracle_version,
        "arm": record["arm"],
        "model": model,
        "harness": harness,
        "validity_class": record["validity_class"],
        "split_group": resolve_split_group(spec_id),
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_total": tokens_total,
        "reward": reward,
        "censored": censored,
        # Schema-REQUIRED, defaulting False when no `verifier/tier1-not-
        # verifiable` marker was found. Always emitted, like `censored` above:
        # it is the only signal distinguishing "tier-1 was checked and passed"
        # from "tier-1 was never actually checkable" in the published data
        # (read_tier1_not_verifiable).
        "tier1_not_verifiable": bool(record.get("tier1_not_verifiable", False)),
    }
    if scenario is not None:
        row["scenario"] = scenario
    # The BENCHMARK scenario id, distinct from the aws-bench `scenario` field
    # above (an "anchor"/"anchor-k" shard shared by many specs, so unusable
    # for per-scenario grouping).
    # Persisted on the row, not just consumed for split_group, so downstream
    # tools (metrics/tokens_to_green.py) can group by it without re-deriving.
    if spec_id is not None:
        row["spec_id"] = spec_id
    if task is not None:
        row["task"] = task
    if trial_id is not None:
        row["trial_id"] = trial_id
    if job_id is not None:
        row["job_id"] = job_id
    if tokens_cached is not None:
        row["tokens_cached"] = tokens_cached
    if record.get("tier1_not_verifiable_detail"):
        row["tier1_not_verifiable_detail"] = record["tier1_not_verifiable_detail"]
    if record.get("cost_usd") is not None:
        row["cost_usd"] = record["cost_usd"]
    if record.get("n_llm_calls") is not None:
        row["n_llm_calls"] = record["n_llm_calls"]
    if record.get("tier_evidence") is not None:
        row["tier_evidence"] = record["tier_evidence"]
    # Null-with-a-reason, never omitted-and-silent: a row from a trial whose
    # verifier did not persist a plan says so in `blast_radius_unavailable`, so
    # "not computable for this trial" is distinguishable from "nobody looked".
    if record.get("blast_radius") is not None:
        row["blast_radius"] = record["blast_radius"]
    elif record.get("blast_radius_unavailable") is not None:
        row["blast_radius_unavailable"] = record["blast_radius_unavailable"]
    if record.get("rbw") is not None:
        row["rbw"] = record["rbw"]
    if record.get("escape_hatch") is not None:
        row["escape_hatch"] = record["escape_hatch"]
    # Provenance for a row harbor could not price or convert itself: both keys
    # are absent on a row built from the ATIF trajectory and harbor's own
    # token totals, so their presence is the whole signal.
    if record.get("audit_source") is not None:
        row["audit_source"] = record["audit_source"]
    if record.get("tokens_source") is not None:
        row["tokens_source"] = record["tokens_source"]
    if record["validity_class"] != VALID:
        row["validity_reason"] = record["reason"]
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate 3: classify a trial's validity and (iff valid) emit its score row."
    )
    parser.add_argument("trial_dir", help="Trial dir (containing agent/trajectory.json, result.json, ...).")
    parser.add_argument("--arm", required=True, choices=KNOWN_ARMS, help="Arm the trial ran.")
    parser.add_argument("--task-dir", required=True, help="Task dir containing instruction.md (for the equipping hash).")
    parser.add_argument("--image-ref", required=True, help="Docker image ref/tag the agent ran in.")
    parser.add_argument(
        "--extra-cfg",
        default="{}",
        help="JSON object of extra equipping config (model, harness flags, ...). Default: '{}'.",
    )
    parser.add_argument("--out", default=None, help="Also write the JSON record to this path.")
    # --- schema-row emission: optional. A row is emitted (via to_result_row,
    # validated shape) only when --model/--harness/--oracle-version are all
    # given, in addition to the raw record this CLI always prints. ----------
    parser.add_argument("--model", default=None, help="If set (with --harness/--oracle-version), also emit a metrics/result_schema.json row.")
    parser.add_argument("--harness", default=None, choices=["empty", "tuned"])
    parser.add_argument("--oracle-version", default=None)
    parser.add_argument("--spec-id", default=None, help="Spec id (e.g. 'apigw-openapi') for split_group resolution (generator/split.py) -- NOT the --scenario/--task values below.")
    parser.add_argument("--scenario", default=None, help="Row's 'scenario' field (aws-bench scenario id, e.g. 'anchor' or 'anchor-2').")
    parser.add_argument("--task", default=None, help="Row's 'task' field (task.toml [task].name).")
    parser.add_argument("--trial-id", default=None)
    parser.add_argument("--job-id", default=None)
    parser.add_argument(
        "--jobs-dir",
        default=None,
        help="Job output dir containing budget.json (scripts/run-bench.sh's own output) -- read to auto-censor the emitted row via max_iters/max_tokens. Overridden per-field by --max-iters/--max-tokens if also given.",
    )
    parser.add_argument("--max-iters", type=int, default=None, help="Explicit MAX_ITERS override (wins over --jobs-dir's budget.json).")
    parser.add_argument("--max-tokens", type=int, default=None, help="Explicit MAX_TOKENS override (wins over --jobs-dir's budget.json).")
    parser.add_argument("--row-out", default=None, help="Also write the to_result_row()-shaped schema row to this path.")
    args = parser.parse_args(argv)

    try:
        extra_cfg = json.loads(args.extra_cfg)
        if not isinstance(extra_cfg, dict):
            raise ValueError("--extra-cfg must decode to a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": f"invalid --extra-cfg: {exc}"}, indent=2))
        return 2

    try:
        record = build_result_record(
            args.trial_dir,
            args.arm,
            args.task_dir,
            args.image_ref,
            extra_cfg,
        )
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    text = json.dumps(record, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")

    if args.model and args.harness and args.oracle_version:
        budget_max_iters, budget_max_tokens = read_budget(args.jobs_dir)
        max_iters = args.max_iters if args.max_iters is not None else budget_max_iters
        max_tokens = args.max_tokens if args.max_tokens is not None else budget_max_tokens
        row = to_result_row(
            record,
            model=args.model,
            harness=args.harness,
            oracle_version=args.oracle_version,
            max_iters=max_iters,
            max_tokens=max_tokens,
            scenario=args.scenario,
            task=args.task,
            trial_id=args.trial_id,
            job_id=args.job_id,
            spec_id=args.spec_id,
        )
        row_text = json.dumps(row, indent=2)
        print(row_text)
        if args.row_out:
            Path(args.row_out).write_text(row_text + "\n")

    return 0 if record["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
