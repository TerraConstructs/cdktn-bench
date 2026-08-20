"""gates/emit_result.py — Gate 3 of the three-gate integrity pattern.

Wraps a trial with a validity class and **refuses to emit a score row for an
invalid trial** — the closing move of the pattern
(``docs/lex00-bench-diff.md`` §"emit-result.py ... Refuses to write a record
for an invalid run rather than badging it").

Validity is one of three mutually exclusive classes:

- ``valid``          — audit gate (gates/audit.py) found toolchain evidence,
                        and no infra-failure signal was detected in the
                        trial's logs.
- ``invalid-bypass``  — the trial completed but never invoked the arm's
                        toolchain (gates/audit.py verdict). Not a scored
                        failure of the arm — the trial never really tested it.
- ``invalid-infra``   — an infrastructure failure (OOM, Docker-daemon
                        unreachable, missing/invalid model-auth env var, ...)
                        was detected in the trial's own **harness-owned**
                        logs (never the agent's own output — see
                        ``_LOG_CANDIDATES`` below), OR the audit gate found
                        the arm's toolchain was invoked but never actually
                        available to run (``audit_trial()["degraded"]`` —
                        command-not-found/exit 127, or SIGKILLed/exit 137).
                        Takes priority over a bypass verdict: a trial that
                        never got to run because its container was
                        OOM-killed didn't "choose" to bypass the toolchain,
                        and neither did a trial whose `cdk synth` call hit
                        `command not found` because the image never actually
                        had the CDK CLI installed. Per DECISIONS.md "Memory
                        floor for tsc-heavy arms": a tsc/cdk-synth OOM is
                        infrastructure-invalid, never a scored CDK failure.

Only ``valid`` trials get score/reward fields populated; invalid trials get
``score_emitted: false`` and no score fields, by design — a caller that
naively sums a job's rewards without checking ``validity_class`` first
cannot silently pool invalid trials into a headline number.

Every emitted record carries ``equipping_hash`` (gates/equipping.py, owned by
a companion module) so results can never be silently pooled across a
different instruction/skill/image equipping.
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

from gates.audit import KNOWN_ARMS, audit_trial, resolve_step_names
from gates.equipping import compute_equipping_hash

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

# Candidate log files, relative to the trial dir, per RECON.md/aws-bench-guide
# §6's trial-dir layout. Scanned in order; every readable one is checked.
#
# Deliberately HARNESS-OWNED artifacts only — trial.log (Harbor/docker's own
# lifecycle log), exception.txt (Harbor's own uncaught-exception dump), and
# result.json (Harbor's structured TrialResult, not agent-authored text).
# `agent/agent-output.txt` and `agent/claude-code.txt` are the AGENT'S OWN
# output stream and must never be scanned here: an agent (or a task whose
# instruction/legitimate tool output happens to mention a phrase like "out
# of memory") could otherwise self-void its own trial by typing one of the
# _INFRA_SIGNS phrases, and since invalid-infra outranks both valid and
# invalid-bypass, that silently drops a genuine failure from the scored
# denominator — see the "self-void / censoring vector" finding this
# constant was narrowed to fix. If agent-authored evidence is ever needed
# for infra detection, drive it off structured signals (container exit
# code, docker error return codes, harbor exception type) instead of
# free-text scanning of agent output, not by adding these files back here.
_LOG_CANDIDATES = [
    "trial.log",
    "exception.txt",
    "result.json",
]


# --- multi-step trial-dir layout -------------------------------------------
#
# A multi-step trial (cdktn_bench.trial.CdktnMultiStepTrial, running Harbor's
# harbor/trial/multi_step.py engine) RELOCATES the per-phase output dirs after
# every step: `agent/`, `verifier/` and `artifacts/` are moved into
# `steps/<name>/` (`MultiStepTrial._archive_step_outputs`). So at the end of a
# multi-step trial the trial dir has NO top-level `agent/` or `verifier/` at
# all -- every reader below that hardcoded those paths would silently report
# "absent" for a trial that produced full evidence.
#
# The three harness-owned logs `classify_infra_failure` scans (`trial.log`,
# `exception.txt`, `result.json`) are NOT relocated: they are written by the
# trial itself at trial level, once. That reader therefore needs no change --
# and must not gain one, since `_LOG_CANDIDATES` was deliberately narrowed to
# harness-owned artifacts (see its own comment: the self-void vector).
#
# Every helper below follows the same shape, which is what keeps a single-step
# trial dir byte-identical: look at the top-level path FIRST and return exactly
# what the pre-multi-step code returned if it is there; only fall back to
# `steps/<name>/...` when it is not.


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

    This exists because ``_create_step_dirs`` makes ``steps/<name>/verifier/``
    **before** the step runs and ``_archive_step_outputs`` runs even when
    ``_prepare_step`` raised, so a step that died in its ``pre_invoke`` leaves a
    real-but-EMPTY verifier dir behind. A first-hit-wins scan over the step dirs
    therefore skips straight past it into step N-1's evidence and attributes an
    earlier step's tier verdict to the trial -- for ``tier1_not_verifiable``,
    that is a required published-row field being filled from a step that was
    never scored. See ``_verifier_evidence_dirs``.

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
    """Read the non-gating `/logs/verifier/tier1-not-verifiable` marker a
    generated `tests/static_tiers.sh` tees whenever a scenario's tier-1
    `policy.rego` defines a `not_verifiable` rule that fired for this
    trial's plan (`generator/gen.py::build_static_tiers_sh`; the rule
    contract itself is `specs/SCHEMA.md` §4.2.1's option-3 bullet).

    Residual finding (2026-08-06): the marker was written but consumed by
    nothing, so a trial whose tier-1 action-allowlist was never actually
    checkable from plan JSON (an entirely normal, idiomatic Terraform
    pattern -- referencing another resource's provider-computed output,
    per §4.2.1) was indistinguishable in the published data from one that
    WAS checked and passed: an identical wildcard-IAM violation scores 0.0
    on `awscdk` (cfn-guard has no plan-time-unknown gap -- CFN synth is
    always fully static) but 1.0 on the TF arms, with nothing in the row
    itself to show why. This closes the read side.

    Host-side path is `<trial_dir>/verifier/tier1-not-verifiable`
    (`harbor/models/trial/paths.py`: `verifier_dir = trial_dir /
    "verifier"`, bind-mounted into the container at `/logs/verifier` --
    the exact same host/container path convention `classify_infra_failure`
    above already relies on for `/logs/agent`).

    Returns ``(present, detail)``: ``present`` is always a bool (``True``
    iff the marker file exists); ``detail`` is the marker's own text
    (already human-readable -- written by `build_static_tiers_sh`) when
    the file exists and is non-empty, else ``None``.

    Multi-step (2026-08-20, task #14): the marker is relocated to
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


# `  PASS [name]` / `  FAIL [name]: ...` -- generator/gen.py's
# `_assert_lib.sh::assert_check()` (build_static_tiers_sh, ~line 839-844)
# echoes exactly this shape for every tier-"0" structural_assert it runs,
# to the verifier's own stdout -- captured by Harbor at
# `<trial_dir>/verifier/test-stdout.txt` (docs/aws-bench-guide.md §6's
# documented trial-dir layout: "verifier/ test-stdout.txt, test-stderr.txt,
# reward.json, reward.txt, reward-details.json"). `[^\]]+` (not `.+`)
# because an assert name is generator-enforced kebab-case
# (specs/SCHEMA.md §4.2: "unique within the spec", no `]` possible) --
# using a non-greedy `.+?` would work too but this is both correct and
# cheaper.
_TIER0_ASSERT_LINE_RE = re.compile(r"^\s*(PASS|FAIL)\s*\[([^\]]+)\]", re.MULTILINE)

# `== summary: tier0_pass=$tier0_pass tier1_status=$tier1_status ==` --
# generator/gen.py::build_static_tiers_sh's template, always the last thing
# echoed before the reward is written (unless a toolchain step failed
# first and `exit 0`'d out of the script before this line ever runs -- in
# that case tier1_status is correctly reported as absent below, not
# guessed).
_TIER1_SUMMARY_RE = re.compile(r"tier1_status=(\S+)")


def read_tier_evidence(trial_dir: str | Path) -> dict[str, Any] | None:
    """Read per-assert tier-0 PASS/FAIL evidence + the bundled tier-1
    verdict from `<trial_dir>/verifier/test-stdout.txt`, for the per-catch
    tier-attribution table (docs/iac-abstraction-aws-bench-plan.md Phase 2
    item 3 / prereg §4's "per-tier catch attribution ... at what cost").

    Two different granularities, and this function is honest about which
    is which -- there is no third option available from the current
    oracle design (see specs/SCHEMA.md §4.2 / generator/gen.py's own
    tier-1 blocks):

    - **tier-0 is per-catch-real**: each tier-"0" `structural_assert` is
      independently invoked and independently echoes its own PASS/FAIL
      (`assert_check()`, see `_TIER0_ASSERT_LINE_RE` above) -- this
      function returns the real per-assert-name verdict, keyed by
      `structural_assert.name` (specs/SCHEMA.md §4.2), under `"tier0"`.
    - **tier-1 is bundle-only**: every tier-"1" `structural_assert` for a
      given arm/scenario is graded by ONE `opa eval`/`cfn-guard validate`
      call over the whole policy file (generator/gen.py's tier1_block),
      producing exactly one `tier1_status` for the WHOLE bundle -- there
      is no per-tier-1-assert breakdown to read, because the oracle itself
      never computes one (the tier-1 assert *names* are compiled into a
      bash `#`-comment for human readability, never echoed to stdout at
      runtime -- verified directly against build_static_tiers_sh's own
      f-string construction of `tier1_comment`). A tier-attribution table
      built from this data can therefore report "which tier-0 catch" a
      trial died on, or "the tier-1 bundle as a whole", but never "which
      individual tier-1 catch" -- callers (metrics/tokens_to_green.py)
      must treat all of a scenario/arm's tier-"1" catches as one unit.

    Returns ``None`` if `verifier/test-stdout.txt` doesn't exist (verifier
    never ran, or ran a non-static_tiers.sh test.sh) -- never an empty dict,
    so a caller can distinguish "no evidence file at all" from "the file
    exists but a toolchain step failed before tier-0/1 ever ran" (the
    latter yields ``{"tier0": {}, "tier1_status": None}``, not ``None``).

    Multi-step (2026-08-20, task #14): `verifier/` is relocated to
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
        # Last occurrence wins -- generator/gen.py enforces assert-name
        # uniqueness within a spec, so in practice each name is only ever
        # echoed once per run; this is just defensive, not load-bearing.
        tier0[name] = status

    tier1_status: str | None = None
    summary_match = _TIER1_SUMMARY_RE.search(text)
    if summary_match:
        tier1_status = summary_match.group(1)

    return {"tier0": tier0, "tier1_status": tier1_status}


def extract_n_llm_calls(trial_dir: str | Path) -> int | None:
    """Count LLM calls from `<trial_dir>/agent/trajectory.json`, mirroring
    `aws_bench/metrics/run_data.py::_llm_usage_from_trajectory`'s own
    `n_llm_calls` accumulation exactly (upstream source, verified against
    the pinned `aws-bench` clone): for every step with `source == "agent"`,
    add `step.llm_call_count` when it's an int, else add 1 iff `step.metrics`
    is present, else add 0. Needed for `iterations-to-green`
    (docs/iac-abstraction-aws-bench-plan.md Phase 2 item 3 / prereg §4) --
    `result.json`'s `agent_result` never carries this field itself
    (verified: only `cost_usd`/`n_input_tokens`/`n_output_tokens`/
    `n_cache_tokens` do -- `_extract_score_fields` above), only the
    trajectory does.

    Deliberately dict-``.get``-only (no ATIF/harbor model import), same
    defensive posture as `_extract_score_fields`'s own docstring explains:
    the trajectory schema is a moving upstream target.

    Returns ``None`` -- NOT ``0`` -- when the trajectory file is absent,
    unreadable, malformed JSON, or has no top-level `steps` list at all:
    "unknown" and "zero" are different claims (residual finding,
    2026-08-06: "a SUCCESSFUL trial with an unreadable trajectory enters
    iterations_to_green_km as an EVENT at time 0.0" -- one unparseable
    trajectory used to silently drag a whole cell's iterations quartile to
    zero). ``0`` is returned ONLY for a genuinely-parsed trajectory whose
    `steps` list is a real list (however short) but contains no
    agent-source step with either signal -- e.g. every synthetic
    gates/tests fixture trajectory, which is hand-authored for audit-gate
    testing and carries no per-step `metrics`/`llm_call_count` at all; that
    IS a real, known answer ("this trajectory really made zero countable
    LLM calls"), not a missing one.

    Multi-step (2026-08-20, task #14): `agent/trajectory.json` is relocated to
    `steps/<name>/agent/trajectory.json`, one per step, each covering that
    step ALONE (a fresh agent session per step -- DECISIONS.md Amendment 26).
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


def extract_n_llm_calls_per_step(trial_dir: str | Path) -> dict[str, int | None]:
    """LLM-call counts keyed by trial phase, in execution order.

    Single-step trial dir: ``{"trial": <n>}`` (or ``{}`` when there is no
    `agent/trajectory.json` at all). Multi-step: one entry per step dir, keyed
    by step name, value ``None`` for a step whose trajectory is
    missing/unreadable/malformed.

    Deliberately keyed rather than a bare list: a caller attributing
    iterations-to-green to a step needs the step's NAME, and the aborted-trial
    case (a `min_reward` gate stopping the run after step 1) shows up here as
    a shorter dict rather than as a silently smaller number.
    """
    trial_dir = Path(trial_dir)
    root = trial_dir / "agent" / "trajectory.json"
    if root.is_file():
        return {"trial": _n_llm_calls_from_trajectory(root)}

    step_names = resolve_step_names(trial_dir)
    if not step_names:
        return {}
    return {
        name: _n_llm_calls_from_trajectory(
            trial_dir / "steps" / name / "agent" / "trajectory.json"
        )
        for name in step_names
    }


def resolve_split_group(spec_id: str | None) -> str:
    """``generator/split.py::spec_group``, resolved to the schema's
    three-value enum (``"train"|"holdout"|"unclassified"``) required on
    every published result row (``metrics/result_schema.json``'s
    ``split_group``, added 2026-08-06: "the train/holdout split is
    unenforceable at the layer that matters -- the published number").

    ``spec_id`` here is the SPEC id (e.g. ``"apigw-openapi"`` --
    ``generator/gen.py``'s ``Spec.id`` / ``specs/<id>.yaml``'s filename
    stem, what ``specs/split.yaml`` actually keys on), which is NOT the
    same string as this schema's own ``scenario``/``task`` row fields
    (those name the aws-bench SCENARIO, always ``"anchor"`` in v1, and the
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
    """Read ``<jobs_dir>/budget.json`` (``scripts/run-bench.sh``'s own
    output — see that script's header for the "MAX_ITERS = 8 feedback
    cycles or MAX_TOKENS per trajectory, whichever first" budget-cap
    contract) and return ``(max_iters, max_tokens)``.

    Fixes the "MAX_TOKENS is inert" finding (2026-08-06): ``run-bench.sh``
    already asserted budget.json "is the value gates/emit_result.py /
    metrics/tokens_to_green.py actually read", but before this function
    nothing in the repo ever opened the file at all — every emitted row's
    ``censored`` came out ``False`` regardless of budget, and
    ``n_budget_censored`` was structurally always 0. This is the read
    side; ``main()``'s ``--jobs-dir`` flag below is the call site.

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
    ``TrialData.reward``, lines ~465-470). Mirrored here so a real Harbor
    ``result.json`` — not just the hand-authored scalar fixtures this
    function used to be proven against — maps to a schema-valid numeric
    ``reward``. A bare scalar (defensive fallback for any non-dict shape a
    future/older producer might still emit) is coerced the same way.
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
    these; this keeps the addends visible so a cumulative tokens-to-green
    (DECISIONS.md Amendment 26: "cumulative sum of per-step agent output
    tokens up to and including the step at which the trial's final oracle
    first passes") can be computed downstream without re-reading result.json.
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
    (``MultiStepTrial._should_stop_after_step``, verbatim). Kept identical on
    purpose — this number's job is to say "Harbor would have aborted here", so
    any drift from that predicate would make it lie. A step with BOTH an
    exception and a verifier_result does not count: Harbor keeps going, and the
    step carries a real score.
    """
    if not isinstance(step_results, list):
        return 0
    return sum(1 for step_result in step_results if _step_aborted_unverified(step_result))


def _declared_step_names(task_dir: str | Path) -> list[str] | None:
    """Step names declared by ``<task_dir>/task.toml``'s ``[[steps]]``.

    ``None`` (not ``[]``) when task.toml is absent/unreadable/malformed, so
    "we could not tell how many steps were declared" stays distinguishable
    from "the task declares no steps".
    """
    path = Path(task_dir) / "task.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    steps = data.get("steps")
    if not isinstance(steps, list):
        return []
    return [s.get("name") for s in steps if isinstance(s, dict)]


def read_step_summary(trial_dir: str | Path, task_dir: str | Path) -> dict[str, Any] | None:
    """Per-step diagnostics for a multi-step trial, or ``None`` if single-step.

    Closes the gap memo §6.7 names: Harbor's ``min_reward`` green gate aborts
    the remaining steps by RETURNING, recording the failure on the
    ``StepResult`` and never on ``TrialResult.exception_info``. So a trial that
    ran half its steps and stopped looks, to every top-level reader, exactly
    like a clean trial -- including this gate's own validity classification.
    ``n_started`` vs ``n_declared``, ``n_failed``, and ``aborted_early`` are
    the signals that distinguish them.

    Counting is subtle enough to spell out, because the obvious reading is
    wrong. Harbor appends the ``StepResult`` BEFORE running the step
    (``harbor/trial/multi_step.py``: ``step_result = StepResult(...)`` /
    ``step_results.append(step_result)``, then ``_run_step``), so
    ``len(step_results)`` counts steps *started*, not steps *finished* — a step
    that died in ``_prepare_step`` (a harness ``pre_invoke`` deploy that failed)
    is still in the list. Hence ``n_started``, not the ``n_completed`` this
    once returned: when the failing step is the LAST declared one — exactly
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
        # The audit gate positionally matched the arm's toolchain (the agent
        # DID try it — this is not a bypass) but every matched call's own
        # observation shows the tool was never actually available to run
        # (command-not-found/exit 127, or SIGKILLed/exit 137). That is a
        # degraded arm, not an agent choice — route it to invalid-infra, not
        # invalid-bypass, even though no log-file infra signal fired.
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
    # ValueError added 2026-08-20 (§2.7): compute_equipping_hash now refuses a
    # caller-supplied `workspace_seed_sha256` that contradicts the one this
    # task.toml declares. Recorded like every other equipping-input failure --
    # `equipping_hash: null` + an error string -- so a contradictory brownfield
    # seed never masquerades as "gate didn't run", and never as a valid hash.
    except (FileNotFoundError, TypeError, ValueError) as exc:
        equipping_hash = None
        equipping_hash_error = str(exc)

    tier1_not_verifiable, tier1_not_verifiable_detail = read_tier1_not_verifiable(trial_dir)
    tier_evidence = read_tier_evidence(trial_dir)

    record: dict[str, Any] = {
        "trial_dir": str(trial_dir),
        "arm": arm,
        "task_dir": str(task_dir),
        "image_ref": image_ref,
        "validity_class": validity_class,
        "valid": validity_class == VALID,
        "reason": reason,
        "equipping_hash": equipping_hash,
        "audit": audit,
        "infra": infra,
        # Always attached regardless of validity_class (same reasoning as
        # audit/infra above) -- present/absent is a fact about the trial's
        # own logs, independent of whether the trial's toolchain use
        # audited as genuine.
        "tier1_not_verifiable": tier1_not_verifiable,
        "tier1_not_verifiable_detail": tier1_not_verifiable_detail,
        # Per-catch tier-attribution evidence (see read_tier_evidence's own
        # docstring for the tier-0-real / tier-1-bundle-only caveat). Also
        # attached regardless of validity_class -- a bypassed/infra-invalid
        # trial's verifier may still have left evidence behind from a PRIOR
        # invocation of tests/static_tiers.sh in the same container, and
        # this being present/absent is itself diagnostic.
        "tier_evidence": tier_evidence,
    }
    if equipping_hash_error is not None:
        record["equipping_hash_error"] = equipping_hash_error

    # Multi-step only (task #14). Attached regardless of validity_class -- an
    # aborted or infra-invalid multi-step trial is exactly when "how far did it
    # get" matters most -- but NEVER attached for a single-step trial, so every
    # existing single-step record keeps its byte-identical shape. The published
    # schema row (to_result_row / metrics/result_schema.json, which sets
    # additionalProperties: false) is deliberately NOT extended here: the row's
    # shape is pre-registered and a multi-step-specific field would be a
    # schema-version bump, not a gate change.
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
RESULT_ROW_SCHEMA_VERSION = "1.0"


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

    This is the schema's producer: nothing before this function turned a
    gate-emitted record into something ``metrics/validate_result.py`` could
    actually check, so ``result_schema.json`` only ever validated a
    hand-authored example — the exact "silently absent from all published
    result JSONs because nothing enforced it" gap the schema's own
    description names. ``metrics/emit_fixture_rows.py`` exercises this
    function against the gate fixtures and validates the output.

    Only ``valid`` records carry meaningful reward/token fields
    (``score_emitted`` is False otherwise, per ``build_result_record``'s
    refusal contract) — for a non-``valid`` record, tokens/reward are
    schema-required but not meaningful, so they're filled with 0/0.0 and
    ``validity_reason`` is set; callers must read ``validity_class`` first,
    exactly as the schema's own field description says.

    ``censored`` (docs/iac-abstraction-aws-bench-plan.md Phase 2 item 2 /
    prereg §4's budget cap): pass an explicit ``True``/``False`` when the
    caller already knows it (e.g. from a job-level budget-tracking pass).
    Leaving it ``None`` (the default) triggers **auto-detection** from
    ``max_iters``/``max_tokens`` — mirrors ``scripts/run-bench.sh``'s
    ``budget.json`` ("MAX_ITERS = 8 feedback cycles or MAX_TOKENS per
    trajectory, whichever first"): a trial that did NOT reach reward 1.0
    and either met/exceeded ``max_tokens`` (by ``tokens_total``) or
    met/exceeded ``max_iters`` (by ``record["n_llm_calls"]``, when known)
    is censored=True; everything else defaults to False. Passing neither
    ``max_iters`` nor ``max_tokens`` (both ``None``, the default) makes
    auto-detection a no-op — ``censored`` comes out ``False`` exactly like
    this function's previous hardcoded default, so every existing caller
    keeps its prior behavior unchanged.

    ``spec_id`` (2026-08-06 fix, prereg §7.1 / DECISIONS.md Amendment 10):
    the spec id (``"apigw-openapi"``, NOT the ``scenario``/``task`` schema
    fields' aws-bench meanings — see ``resolve_split_group``'s own
    docstring) used to resolve the schema-REQUIRED ``split_group`` field.
    Omitting it does not skip the field (it cannot — the schema requires
    it on every row) — it resolves to ``"unclassified"`` instead, so a
    caller that forgets to pass it gets an honestly-labeled row, not a
    silently train/holdout-mislabeled one.
    """
    if record.get("equipping_hash") is None:
        raise ValueError(
            "to_result_row: record has no equipping_hash "
            f"({record.get('equipping_hash_error', 'unknown reason')}) — "
            f"a published result row requires one."
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
        # Residual finding (2026-08-06): REQUIRED, defaulting False when
        # build_result_record() found no `verifier/tier1-not-verifiable`
        # marker -- schema-required-with-default-false semantics, same
        # shape as `censored` above (always emitted by this producer, no
        # JSON-Schema `default` keyword needed since the row is never
        # missing it). See read_tier1_not_verifiable()'s own docstring for
        # why this must never be silently absent: it is the only signal
        # distinguishing "tier-1 was checked and passed" from "tier-1 was
        # never actually checkable" in the published data.
        "tier1_not_verifiable": bool(record.get("tier1_not_verifiable", False)),
    }
    if scenario is not None:
        row["scenario"] = scenario
    # spec_id (2026-08-06 fix): the BENCHMARK scenario id, distinct from
    # the aws-bench `scenario` field above (always "anchor" in this repo --
    # see result_schema.json's own field descriptions for why `scenario`
    # cannot be used for per-benchmark-scenario grouping). Persisted on the
    # row itself, not just consumed transiently for split_group above, so
    # downstream tools (metrics/tokens_to_green.py) can group/attribute by
    # it without re-deriving it.
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
    # --- schema-row emission (2026-08-06 fix: "MAX_TOKENS is inert and
    # budget.json has no reader" + "split_group is unenforceable at the
    # layer that matters") -- optional; a row is emitted (via
    # to_result_row, validated shape) only when --model/--harness/
    # --oracle-version are all given, in addition to the raw record this
    # CLI already always prints. ------------------------------------------
    parser.add_argument("--model", default=None, help="If set (with --harness/--oracle-version), also emit a metrics/result_schema.json row.")
    parser.add_argument("--harness", default=None, choices=["empty", "tuned"])
    parser.add_argument("--oracle-version", default=None)
    parser.add_argument("--spec-id", default=None, help="Spec id (e.g. 'apigw-openapi') for split_group resolution (generator/split.py) -- NOT the --scenario/--task values below.")
    parser.add_argument("--scenario", default=None, help="Row's 'scenario' field (aws-bench scenario id, e.g. 'anchor').")
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
