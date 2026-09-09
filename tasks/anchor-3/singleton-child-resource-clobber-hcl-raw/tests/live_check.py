#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (spec_model.LiveCheck.hand_authored =
true; specs/SCHEMA.md §5). The live, GATING oracle of the brownfield scenario
`singleton-child-resource-clobber`
(specs/singleton-child-resource-clobber.yaml, DECISIONS.md Amendments 28/31).

Regenerating this scenario
(`make gen SPEC=specs/singleton-child-resource-clobber.yaml`) will NOT
overwrite this file: gen.py's write_tests_dir() is destructive-safe for
tests/live_check.py whenever spec.verifier.live_check.hand_authored is true
(SCHEMA.md §8.2 point 8).

ARM-AGNOSTIC BY CONSTRUCTION. This file is byte-identical in all three arms'
task directories. It asks S3 what the bucket actually has; it never looks at
the workspace, the toolchain, or any synth/plan artifact. That is the point:
the whole scenario turns on the fact that a wrong artifact and a right one can
describe the same two rules while the ACCOUNT holds only one of them, so the
live oracle must not be able to tell which arm produced the state it reads.

WHAT ONLY A LIVE CHECK CAN SEE HERE
===================================
An S3 bucket has exactly ONE lifecycle configuration document.
PutBucketLifecycleConfiguration replaces it whole -- there is no per-rule
write and no create/update distinction. So two Terraform resources targeting
one bucket both plan green, both apply green, and then take turns overwriting
each other: the bucket ends up holding whichever applied last. BOTH rules are
nevertheless present in the graded artifact, one per resource, so every
value-level static assert in this scenario passes on that shape. The static
tier that does catch it is a CARDINALITY assert about the artifact
(`exactly-one-storage-rule-document-for-the-bucket`); this file is the
independent, account-side statement of the same claim, and the only instrument
in the stack that can distinguish

    "the file says both rules"      from      "the bucket has both rules".

It is also the only one that can see a change that was authored and never
rolled out, which the prompt asks for in as many words.

WHAT IT ASSERTS (all four are properties of the ACCOUNT, not of the code):
  1. the bucket exists and has a lifecycle configuration at all;
  2. the OTHER team's rule is still in effect: some rule scoped to `logs/`,
     Enabled, expiring after exactly 30 days. This is the clobber detector --
     it is the half a second document silently drops, and the half a rewritten
     document silently drops;
  3. the REQUESTED rule is in effect: some rule scoped to `exports/`, Enabled,
     transitioning to GLACIER_IR after exactly 90 days. This is the
     did-anything-happen detector; the seed's deployed document does not
     contain it, which `deploy.live_asserts` proves PRE-agent;
  4. the document holds exactly those TWO rules and nothing else -- so a
     "solution" that satisfies (2) and (3) by piling on extra retention rules
     nobody asked for is not silently accepted.

Assertions 2 and 3 are what make this oracle discriminating rather than
decorative, and they are discriminating only because
`workspace_seed.deploy.live_asserts` proved, before the agent's first token,
that this account held EXACTLY ONE rule and it was the `logs/` one. Without
that pre-condition (2) could be satisfied by a seed nobody touched and (3)
could only ever be reached by authoring from scratch -- the vacuous-pass shape
docs/brownfield-seed-not-deployed.md was filed for.

OUTCOME CONTRACT (SCHEMA.md §5, gating): a JSON object on stdout with an
`outcome` of
    "pass"           -- all four assertions hold;
    "fail_stale"     -- the account contradicts at least one of them (this is a
                        real, legitimate verdict about the agent's work). A
                        bucket with NO lifecycle configuration at all
                        (`NoSuchLifecycleConfiguration`) is this, not
                        "not_verifiable": the seed proof established that a
                        document was there before the agent ran, so its absence
                        afterwards is an observation about the change, not a
                        failure to observe;
    "not_verifiable" -- the check could not be run (no `aws` CLI, no
                        credentials, an API error other than the two named
                        above). Fail-closed: the generated tests/test.sh
                        downgrades reward to 0.0 for anything that is not
                        "pass", and an unverifiable claim must never silently
                        earn reward.

TWO CALL SHAPES, matching this repo's existing convention (see
named-resource-replacement's own live_check.py):
  * verifier-invoked, no args -- prints the JSON, always exits 0. The exit code
    is not the verdict; `.outcome` is.
  * fixture-invoked, `--expect {ok,stale}` -- used by solution/solve.sh and
    solution/broken/*/solve.sh under LIVE=1. Prints the same JSON and exits
    non-zero when the observed outcome contradicts what the caller asserted.

NO LIVE AWS CALL HAPPENS OFFLINE. With no credentials the `aws` invocations
fail and this reports "not_verifiable" -- which is why `make falsifiability` /
`make grading-proof` never reach this file: they run tests/static_tiers.sh
directly, not tests/test.sh.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any

BUCKET = "cdktn-bench-reports-archive"

LOGS_PREFIX = "logs/"
LOGS_EXPIRATION_DAYS = 30

EXPORTS_PREFIX = "exports/"
EXPORTS_TRANSITION_DAYS = 90
EXPORTS_STORAGE_CLASS = "GLACIER_IR"

# PutBucketLifecycleConfiguration is not read-your-writes on every path, and
# `cdk deploy` returns as soon as CloudFormation reports the stack complete.
# Sampled rather than read once, for the same reason named-resource-replacement's
# own live check polls: a single sample taken in the first seconds after a
# deploy turns a correct solution into a spurious failure.
POLL_TIMEOUT_S = 90
POLL_INTERVAL_S = 10

# The two S3 error codes that are OBSERVATIONS about the agent's change rather
# than failures to observe. Everything else the CLI can fail with (expired
# credentials, throttling, no network, no `aws` binary) is not_verifiable.
_VERDICT_ERROR_CODES = ("NoSuchLifecycleConfiguration", "NoSuchBucket")


class AwsUnavailable(RuntimeError):
    """The `aws` CLI could not be run, or refused the call -- NOT a verdict."""


class AwsSaysAbsent(RuntimeError):
    """S3 answered, and its answer is that the thing is not there -- a VERDICT."""


def _aws(*args: str) -> Any:
    try:
        proc = subprocess.run(
            ["aws", *args, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        for code in _VERDICT_ERROR_CODES:
            if code in stderr:
                raise AwsSaysAbsent(f"aws {' '.join(args)}: {code}")
        raise AwsUnavailable(
            f"aws {' '.join(args)}: exit {proc.returncode}: {stderr.strip()[:400]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: unparseable output") from exc


def _rule_prefix(rule: dict) -> str | None:
    """The prefix a rule is scoped to, across the two spellings S3 returns.

    The modern shape is `Filter: {"Prefix": ...}`; the legacy top-level
    `Prefix` is still returned for documents written that way. Reading both is
    not laxness: this oracle grades what the BUCKET holds, and the bucket does
    not care which spelling put it there. A rule scoped by `Filter.And` (prefix
    plus tags) deliberately resolves to None and therefore cannot satisfy
    assertion 2 or 3 -- a tag-conditioned rule is not the unconditional
    retention the requirement states.
    """
    flt = rule.get("Filter")
    if isinstance(flt, dict) and isinstance(flt.get("Prefix"), str):
        return flt["Prefix"]
    if isinstance(rule.get("Prefix"), str):
        return rule["Prefix"]
    return None


def observe() -> dict:
    """One sample of the four assertions.

    Raises AwsUnavailable if the account could not be read at all (never a
    verdict about the agent). Returns a fail_stale verdict when S3 itself says
    the bucket or its lifecycle configuration is gone.
    """
    try:
        data = _aws("s3api", "get-bucket-lifecycle-configuration", "--bucket", BUCKET)
    except AwsSaysAbsent as exc:
        return {
            "outcome": "fail_stale",
            "failures": [
                f"{exc} -- the seed proof established, before the agent ran, that "
                f"this bucket held one storage-rule document; it does not now"
            ],
            "rules": [],
        }

    rules = [r for r in data.get("Rules", []) if isinstance(r, dict)]
    failures: list[str] = []

    def _enabled(rule: dict) -> bool:
        return rule.get("Status") == "Enabled"

    logs_rules = [r for r in rules if _rule_prefix(r) == LOGS_PREFIX]
    exports_rules = [r for r in rules if _rule_prefix(r) == EXPORTS_PREFIX]

    # 2. the OTHER team's rule is still in effect.
    kept = [
        r
        for r in logs_rules
        if _enabled(r)
        and isinstance(r.get("Expiration"), dict)
        and r["Expiration"].get("Days") == LOGS_EXPIRATION_DAYS
    ]
    if not kept:
        failures.append(
            f"no enabled rule scoped to {LOGS_PREFIX!r} expires objects after "
            f"{LOGS_EXPIRATION_DAYS} days -- the rule that was deployed in this "
            f"bucket before the change is no longer in effect (rules now in the "
            f"document: {[r.get('ID') for r in rules]})"
        )

    # 3. the REQUESTED rule is in effect.
    added = [
        r
        for r in exports_rules
        if _enabled(r)
        and any(
            isinstance(t, dict)
            and t.get("Days") == EXPORTS_TRANSITION_DAYS
            and t.get("StorageClass") == EXPORTS_STORAGE_CLASS
            for t in r.get("Transitions", [])
        )
    ]
    if not added:
        failures.append(
            f"no enabled rule scoped to {EXPORTS_PREFIX!r} transitions objects to "
            f"{EXPORTS_STORAGE_CLASS} after {EXPORTS_TRANSITION_DAYS} days -- the "
            f"requested change is not in effect in this account (rules now in the "
            f"document: {[r.get('ID') for r in rules]})"
        )

    # 4. exactly those two rules, nothing else.
    if len(rules) != 2:
        failures.append(
            f"the bucket's storage-rule document holds {len(rules)} rule(s), not 2 "
            f"-- the change adds exactly one rule to the one that was already "
            f"there (ids: {[r.get('ID') for r in rules]})"
        )

    return {
        "outcome": "pass" if not failures else "fail_stale",
        "failures": failures,
        "rules": [
            {
                "id": r.get("ID"),
                "status": r.get("Status"),
                "prefix": _rule_prefix(r),
                "expiration_days": (r.get("Expiration") or {}).get("Days"),
                "transitions": [
                    {"days": t.get("Days"), "storage_class": t.get("StorageClass")}
                    for t in r.get("Transitions", [])
                    if isinstance(t, dict)
                ],
            }
            for r in rules
        ],
    }


def poll() -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last: dict | None = None
    while True:
        try:
            last = observe()
        except AwsUnavailable as exc:
            return {
                "outcome": "not_verifiable",
                "reason": str(exc),
                "failures": [],
                "rules": [],
            }
        if last["outcome"] == "pass" or time.monotonic() >= deadline:
            last["polled_for_s"] = POLL_TIMEOUT_S if last["outcome"] != "pass" else None
            return last
        time.sleep(POLL_INTERVAL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        choices=["ok", "stale"],
        default=None,
        help="fixture-invoked shape: assert the observed outcome. Exits non-zero "
        "when the account contradicts the assertion.",
    )
    args = parser.parse_args()

    result = poll()
    result["scenario"] = "singleton-child-resource-clobber"
    result["bucket"] = BUCKET
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.expect is None:
        # Verifier-invoked: `.outcome` is the verdict, the exit code is not.
        return 0
    if result["outcome"] == "not_verifiable":
        print(
            "live_check: could not read the account -- refusing to confirm or "
            "deny the fixture's assertion",
            file=sys.stderr,
        )
        return 2
    expected = "pass" if args.expect == "ok" else "fail_stale"
    if result["outcome"] != expected:
        print(
            f"live_check: expected outcome {expected!r}, observed "
            f"{result['outcome']!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
