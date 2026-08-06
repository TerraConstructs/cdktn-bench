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
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gates.audit import KNOWN_ARMS, audit_trial
from gates.equipping import compute_equipping_hash

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
    """
    marker = Path(trial_dir) / "verifier" / "tier1-not-verifiable"
    if not marker.is_file():
        return False, None
    try:
        text = marker.read_text(errors="replace").strip()
    except OSError:
        return True, None
    return True, (text or None)


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
    except (FileNotFoundError, TypeError) as exc:
        equipping_hash = None
        equipping_hash_error = str(exc)

    tier1_not_verifiable, tier1_not_verifiable_detail = read_tier1_not_verifiable(trial_dir)

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
    }
    if equipping_hash_error is not None:
        record["equipping_hash_error"] = equipping_hash_error

    if validity_class != VALID:
        # The refusal: no score fields at all for an invalid trial.
        record["score_emitted"] = False
        return record

    record["score_emitted"] = True
    record.update(_extract_score_fields(trial_dir))
    return record


# Must match metrics/result_schema.json's "schema_version" const exactly.
RESULT_ROW_SCHEMA_VERSION = "1.0"


def to_result_row(
    record: dict[str, Any],
    *,
    model: str,
    harness: str,
    oracle_version: str,
    censored: bool = False,
    scenario: str | None = None,
    task: str | None = None,
    trial_id: str | None = None,
    job_id: str | None = None,
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

    row: dict[str, Any] = {
        "schema_version": RESULT_ROW_SCHEMA_VERSION,
        "equipping_hash": record["equipping_hash"],
        "oracle_version": oracle_version,
        "arm": record["arm"],
        "model": model,
        "harness": harness,
        "validity_class": record["validity_class"],
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

    return 0 if record["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
