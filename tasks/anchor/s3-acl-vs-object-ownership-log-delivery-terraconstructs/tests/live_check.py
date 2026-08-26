#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (spec_model.LiveCheck.hand_authored =
true; specs/SCHEMA.md §5). The live, GATING oracle of the brownfield scenario
`s3-acl-vs-object-ownership-log-delivery`
(specs/s3-acl-vs-object-ownership-log-delivery.yaml, DECISIONS.md Amendments 28
and 31).

Regenerating this scenario will NOT overwrite this file: gen.py's
write_tests_dir() is destructive-safe for tests/live_check.py whenever
spec.verifier.live_check.hand_authored is true (SCHEMA.md §8.2 point 8).

ARM-AGNOSTIC BY CONSTRUCTION. Byte-identical in all three arms' task
directories. It asks S3 what is actually deployed; it never reads the
workspace, the toolchain, or any synth/plan artifact. That is the point: the
scenario turns on the fact that the arms' *static* artifacts cannot express the
thing being graded, so the live oracle must not be able to tell which arm
produced the account state it reads.

WHY THIS TIER EXISTS, AND WHY IT DOES NOT SETTLE FOR "A PROPERTY IS SET"
=======================================================================
The workspace ships an application bucket whose S3 server access logs are
delivered to a second bucket, authorized the original way: a bucket ACL
granting the S3 log delivery group. The change request is the ordinary
"stop relying on ACLs" ticket, whose mechanism -- Object Ownership's
bucket-owner-enforced setting -- DISABLES ACLs, at which point that grant
"no longer affect[s] permissions"
(docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html).
Nothing announces it. The logging configuration is untouched, so
`PutBucketLogging` is never re-issued; `GetBucketLogging` keeps returning the
same answer; the plan and the apply are green. Only the log objects stop
arriving, hours later.

So a check that merely confirmed "ownership is enforced" and "a bucket policy
exists" would pass the exact solution this scenario is about. What this file
does instead is answer the AUTHORIZATION question, over deployed state:

  A. Object Ownership on the destination bucket really is the bucket-owner-
     enforced setting IN THE ACCOUNT -- not merely in the artifact. A plan that
     was never applied, or an apply that failed part-way, is invisible to every
     static tier and fails here.
  B. The destination bucket's ACL no longer grants the S3 log delivery group.
     Implied by (A) and read anyway, because it is the fact the whole scenario
     is about and reading it makes the report self-evidencing rather than
     self-referential.
  C. The application bucket's DEPLOYED logging configuration still names this
     destination bucket and this prefix -- i.e. the ticket was not "satisfied"
     by switching logging off.
  D. THE DISCRIMINATOR. With ACLs disabled, a bucket policy is the ONLY thing
     that can authorize delivery, so the deployed bucket policy is fetched and
     EVALUATED -- principals, actions, resource-ARN wildcards and Deny
     statements -- against the concrete request S3 makes: can
     `logging.s3.amazonaws.com` `s3:PutObject` an object under
     `s3://<destination>/<prefix>`? This is a policy evaluation over live
     state, not a grep for a string in a template.
  E. A BEHAVIOURAL CORROBORATION. S3's own `PutBucketLogging` is re-driven with
     the configuration read in (C). AWS validates the destination bucket's
     permissions on that call, so this asks the service itself whether the
     configuration it is holding is still one it would accept. It runs only
     after A-D pass, so it can make the verdict stricter and never looser --
     and its failure mode is named explicitly (`InvalidTargetBucketForLogging`)
     rather than being inferred from a non-zero exit.

The residual limit, stated rather than papered over: a Deny statement carrying
a CONDITION is not treated as blocking, because this file does not model an
arbitrary IAM request context. (E) is the backstop for that case -- a Deny that
really does block delivery is something AWS's own validator can see and this
file's policy evaluator cannot.

OUTCOME CONTRACT (SCHEMA.md §5, gating): a JSON object on stdout with an
`outcome` of
    "pass"           -- every assertion holds;
    "fail_stale"     -- the account contradicts at least one of them (a real,
                        legitimate verdict about the agent's work);
    "not_verifiable" -- the check could not be RUN (no `aws` CLI, no
                        credentials, an API error that is not an answer).
                        Fail-closed: tests/test.sh downgrades reward to 0.0 for
                        anything that is not "pass".

TWO CALL SHAPES, matching this repo's convention:
  * verifier-invoked, no args -- prints the JSON, always exits 0. The exit code
    is not the verdict; `.outcome` is.
  * fixture-invoked, `--expect {ok,stale}` -- used by solution/solve.sh and
    solution/broken/*/solve.sh under LIVE=1. Prints the same JSON and exits
    non-zero when the observed outcome contradicts what the caller asserted.

NO LIVE AWS CALL HAPPENS OFFLINE. With no credentials every `aws` invocation
fails and this reports "not_verifiable" -- which is why `make falsifiability`
never reaches this file: it runs tests/static_tiers.sh directly, not
tests/test.sh.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Any

SOURCE_BUCKET = "cdktn-bench-application-storage-app-data"
DESTINATION_BUCKET = "cdktn-bench-application-storage-access-logs"
LOG_PREFIX = "app-data/"
LOGGING_SERVICE_PRINCIPAL = "logging.s3.amazonaws.com"
LOG_DELIVERY_GROUP_URI = "http://acs.amazonaws.com/groups/s3/LogDelivery"

# The concrete object key S3 would write. Log object keys are
# `<TargetPrefix><YYYY>-<MM>-<DD>-<hh>-<mm>-<ss>-<UniqueString>`
# (docs.aws.amazon.com/AmazonS3/latest/userguide/ServerLogs.html), so this is a
# real member of the key space the policy has to cover -- not a wildcard we
# match against a wildcard, which would let `arn:aws:s3:::<bucket>/wrong/*`
# score as covering.
SAMPLE_LOG_OBJECT_KEY = f"{LOG_PREFIX}2026-08-26-00-00-00-EXAMPLEUNIQUESTRING"
SOURCE_BUCKET_ARN = f"arn:aws:s3:::{SOURCE_BUCKET}"
DESTINATION_OBJECT_ARN = f"arn:aws:s3:::{DESTINATION_BUCKET}/{SAMPLE_LOG_OBJECT_KEY}"

# A freshly written bucket policy and a freshly changed ownership control are
# both eventually consistent, and the verifier runs seconds after the agent's
# deploy. Sampled rather than read once, for the same reason the sibling
# brownfield scenario's live check polls: one early sample turns a correct
# solution into a spurious failure.
POLL_TIMEOUT_S = 120
POLL_INTERVAL_S = 10

# AWS error codes that are an ANSWER about the account rather than a failure to
# ask. `NoSuchBucketPolicy` on the destination bucket is the single most likely
# shape of the mistake this scenario grades; the ownership-controls codes are
# how S3 says "this bucket has no ownership controls at all", which is likewise
# a verdict, not an outage. Every OTHER error is treated as not_verifiable.
_ABSENCE_CODES = (
    "NoSuchBucketPolicy",
    "OwnershipControlsNotFoundError",
    "NoSuchOwnershipControls",
    "NoSuchBucket",
    "NoSuchKey",
)


class AwsUnavailable(RuntimeError):
    """The `aws` CLI could not be run, or refused the call -- NOT a verdict."""


class AwsAbsent(RuntimeError):
    """AWS answered, and the answer is 'that thing does not exist'."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _aws_raw(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["aws", *args, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: {exc}") from exc


def _classify(proc: subprocess.CompletedProcess, args: list[str]) -> None:
    """Raise AwsAbsent for a 'does not exist' answer, AwsUnavailable otherwise."""
    blob = f"{proc.stderr}\n{proc.stdout}"
    for code in _ABSENCE_CODES:
        if code in blob:
            raise AwsAbsent(code, f"aws {' '.join(args)}")
    raise AwsUnavailable(
        f"aws {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()[:400]}"
    )


def _aws(*args: str) -> Any:
    proc = _aws_raw(list(args))
    if proc.returncode != 0:
        _classify(proc, list(args))
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: unparseable output") from exc


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _iam_glob(pattern: str, value: str) -> bool:
    """IAM wildcard match: `*` is any run of characters, `?` is exactly one.

    Anchored on purpose. An UNanchored search would make
    `arn:aws:s3:::other-bucket/*` "match" this bucket's key ARN via a
    coincidental substring, which is the same class of false PASS that jq's
    `contains/1` produced on the sibling brownfield scenario (finding M2).
    """
    escaped = "".join(
        ".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in pattern
    )
    return re.fullmatch(escaped, value) is not None


def _principal_covers_logging_service(principal: Any) -> bool:
    if principal == "*":
        return True
    if not isinstance(principal, dict):
        return False
    if "*" in [p for p in _as_list(principal.get("AWS")) if isinstance(p, str)]:
        return True
    return LOGGING_SERVICE_PRINCIPAL in [
        p for p in _as_list(principal.get("Service")) if isinstance(p, str)
    ]


def _action_covers_putobject(action: Any) -> bool:
    return any(
        isinstance(a, str) and _iam_glob(a.lower(), "s3:putobject")
        for a in _as_list(action)
    )


def _resource_covers_log_object(resource: Any) -> bool:
    return any(
        isinstance(r, str) and _iam_glob(r, DESTINATION_OBJECT_ARN)
        for r in _as_list(resource)
    )


def _statement_targets_log_delivery(stmt: dict) -> bool:
    """Does this statement's Principal/Action/Resource triple cover the write
    S3's log delivery makes? Effect and Condition are the caller's business."""
    if any(k in stmt for k in ("NotPrincipal", "NotAction", "NotResource")):
        # Not modelled. Reported by the caller; never silently treated as a
        # grant (which would loosen the oracle) nor as a block (which would
        # fail correct solutions for an unmodelled reason).
        return False
    return (
        _principal_covers_logging_service(stmt.get("Principal"))
        and _action_covers_putobject(stmt.get("Action"))
        and _resource_covers_log_object(stmt.get("Resource"))
    )


def _condition_failures(condition: Any, account_id: str) -> list[str]:
    """The subset of condition keys this file DOES model, evaluated against the
    real request S3 makes when it delivers a log object for SOURCE_BUCKET.

    Anything unmodelled is reported by the caller and NOT treated as a failure:
    the discriminating case this oracle exists for is a policy with no
    qualifying statement at all, and being strict about condition keys nobody
    wrote would only ever produce false failures against correct solutions.
    """
    failures: list[str] = []
    if not isinstance(condition, dict):
        return failures
    for operator, kv in condition.items():
        if not isinstance(kv, dict):
            continue
        for key, expected in kv.items():
            values = [v for v in _as_list(expected) if isinstance(v, str)]
            low_key = str(key).lower()
            low_op = str(operator).lower()
            if low_key == "aws:sourcearn" and low_op in (
                "arnlike",
                "arnequals",
                "stringequals",
                "stringlike",
            ):
                if not any(_iam_glob(v, SOURCE_BUCKET_ARN) for v in values):
                    failures.append(
                        f"the granting statement's {operator}/{key} condition "
                        f"({values}) does not match the source bucket "
                        f"{SOURCE_BUCKET_ARN!r}, so S3's delivery request would "
                        "not satisfy it"
                    )
            elif low_key == "aws:sourceaccount" and low_op in (
                "stringequals",
                "stringlike",
            ):
                if account_id and not any(_iam_glob(v, account_id) for v in values):
                    failures.append(
                        f"the granting statement's {operator}/{key} condition "
                        f"({values}) does not match this account ({account_id})"
                    )
    return failures


def _unmodelled_condition_keys(condition: Any) -> list[str]:
    known = {"aws:sourcearn", "aws:sourceaccount", "aws:securetransport"}
    out: list[str] = []
    if isinstance(condition, dict):
        for operator, kv in condition.items():
            if isinstance(kv, dict):
                for key in kv:
                    if str(key).lower() not in known:
                        out.append(f"{operator}/{key}")
    return sorted(set(out))


def _account_id() -> str:
    return str(_aws("sts", "get-caller-identity").get("Account") or "")


def _ownership(bucket: str) -> list[str]:
    try:
        data = _aws("s3api", "get-bucket-ownership-controls", "--bucket", bucket)
    except AwsAbsent:
        return []
    return [
        str(rule.get("ObjectOwnership"))
        for rule in data.get("OwnershipControls", {}).get("Rules", [])
        if rule.get("ObjectOwnership")
    ]


def _acl_group_uris(bucket: str) -> list[str]:
    try:
        data = _aws("s3api", "get-bucket-acl", "--bucket", bucket)
    except AwsAbsent:
        return []
    return [
        str(g.get("Grantee", {}).get("URI"))
        for g in data.get("Grants", [])
        if isinstance(g.get("Grantee"), dict) and g["Grantee"].get("URI")
    ]


def _logging(bucket: str) -> dict:
    try:
        data = _aws("s3api", "get-bucket-logging", "--bucket", bucket)
    except AwsAbsent:
        return {}
    enabled = data.get("LoggingEnabled")
    return enabled if isinstance(enabled, dict) else {}


def _bucket_policy(bucket: str) -> dict | None:
    """The deployed bucket policy document, or None when there is none at all
    (`NoSuchBucketPolicy`) -- which is itself the most likely shape of this
    scenario's mistake and must reach the caller as a fact, not as an error."""
    try:
        data = _aws("s3api", "get-bucket-policy", "--bucket", bucket)
    except AwsAbsent:
        return None
    raw = data.get("Policy")
    if not isinstance(raw, str):
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def _probe_put_bucket_logging(logging_enabled: dict) -> tuple[str, str]:
    """Re-drive S3's OWN validator with the configuration already deployed.

    Returns (status, detail) where status is one of:
      "accepted"   -- AWS still accepts this logging configuration;
      "rejected"   -- AWS refused it with InvalidTargetBucketForLogging, i.e.
                      the service itself says the destination bucket cannot
                      receive these logs;
      and anything else raises, because an error that is not that specific
      refusal is not an answer about the agent's work.

    Idempotent: the body is exactly what `GetBucketLogging` just returned, so a
    successful call re-writes the configuration that is already there.
    """
    body = json.dumps({"LoggingEnabled": logging_enabled}, sort_keys=True)
    args = [
        "s3api",
        "put-bucket-logging",
        "--bucket",
        SOURCE_BUCKET,
        "--bucket-logging-status",
        body,
    ]
    proc = _aws_raw(args)
    if proc.returncode == 0:
        return "accepted", ""
    blob = f"{proc.stderr}\n{proc.stdout}"
    if "InvalidTargetBucketForLogging" in blob:
        return "rejected", proc.stderr.strip()[:400]
    _classify(proc, args)
    raise AssertionError("unreachable")  # pragma: no cover


def observe() -> dict:
    """One sample of the whole assertion set. Raises AwsUnavailable when the
    account could not be READ at all, which is never a verdict about the
    agent."""
    account_id = _account_id()

    failures: list[str] = []
    notes: list[str] = []

    # --- A. the ownership change actually landed in the account -------------
    ownership = _ownership(DESTINATION_BUCKET)
    if ownership != ["BucketOwnerEnforced"]:
        failures.append(
            f"the destination bucket {DESTINATION_BUCKET!r} reports Object "
            f"Ownership {ownership or '(none set)'} in this account, not "
            "['BucketOwnerEnforced'] -- ACLs are still enabled there, so the "
            "requested change either was never applied or did not survive the "
            "rollout"
        )

    # --- B. the ACL grant is really gone ------------------------------------
    acl_uris = _acl_group_uris(DESTINATION_BUCKET)
    if LOG_DELIVERY_GROUP_URI in acl_uris:
        failures.append(
            f"the destination bucket's ACL still grants {LOG_DELIVERY_GROUP_URI} "
            "-- ACLs have not been switched off"
        )

    # --- C. logging is still pointed here, under the same prefix ------------
    logging_enabled = _logging(SOURCE_BUCKET)
    if not logging_enabled:
        failures.append(
            f"the application bucket {SOURCE_BUCKET!r} has NO server access "
            "logging configuration deployed -- log delivery was switched off "
            "rather than migrated"
        )
    else:
        target_bucket = str(logging_enabled.get("TargetBucket") or "")
        target_prefix = str(logging_enabled.get("TargetPrefix") or "")
        if target_bucket != DESTINATION_BUCKET:
            failures.append(
                f"the application bucket's access logs are delivered to "
                f"{target_bucket!r}, not to {DESTINATION_BUCKET!r}"
            )
        if target_prefix != LOG_PREFIX:
            failures.append(
                f"the application bucket's access logs are delivered under "
                f"prefix {target_prefix!r}, not {LOG_PREFIX!r}"
            )

    # --- D. THE DISCRIMINATOR: is delivery actually authorized? -------------
    policy = _bucket_policy(DESTINATION_BUCKET)
    granting: list[str] = []
    blocking: list[str] = []
    conditional_denies: list[str] = []
    unmodelled: list[str] = []
    # A statement that WOULD have granted delivery but whose condition cannot be
    # satisfied by S3's request has already produced its own, more specific
    # failure. Tracked explicitly rather than inferred by grepping the failure
    # strings, which would couple this branch to wording.
    grant_blocked_by_condition = False
    if policy is None:
        failures.append(
            f"the destination bucket {DESTINATION_BUCKET!r} has NO bucket policy "
            "in this account. With ACLs disabled a bucket policy is the only "
            f"thing that can authorize {LOGGING_SERVICE_PRINCIPAL} to write log "
            "objects, so nothing authorizes log delivery and it has silently "
            "stopped"
        )
    else:
        for index, stmt in enumerate(_as_list(policy.get("Statement"))):
            if not isinstance(stmt, dict):
                continue
            sid = str(stmt.get("Sid") or f"#{index}")
            if not _statement_targets_log_delivery(stmt):
                continue
            effect = str(stmt.get("Effect") or "")
            if effect == "Allow":
                cond_failures = _condition_failures(stmt.get("Condition"), account_id)
                unmodelled += [
                    f"{sid}:{k}" for k in _unmodelled_condition_keys(stmt.get("Condition"))
                ]
                if cond_failures:
                    failures.extend(cond_failures)
                    grant_blocked_by_condition = True
                else:
                    granting.append(sid)
            elif effect == "Deny":
                if stmt.get("Condition"):
                    conditional_denies.append(sid)
                else:
                    blocking.append(sid)
        if not granting and not grant_blocked_by_condition:
            failures.append(
                f"the destination bucket's policy has no Allow statement that "
                f"lets {LOGGING_SERVICE_PRINCIPAL} run s3:PutObject on "
                f"{DESTINATION_OBJECT_ARN!r}. With ACLs disabled that is the "
                "only grant that can carry log delivery"
            )
        if blocking:
            failures.append(
                f"the destination bucket's policy has unconditional Deny "
                f"statement(s) {blocking} covering the log-delivery write, which "
                "override any Allow"
            )
        if conditional_denies:
            notes.append(
                f"conditional Deny statement(s) {conditional_denies} cover the "
                "log-delivery write; this oracle does not model an arbitrary "
                "request context, so they are left to the PutBucketLogging probe"
            )
        if unmodelled:
            notes.append(
                f"granting statement carries condition key(s) this oracle does "
                f"not model: {sorted(set(unmodelled))}"
            )

    # --- E. ask S3 itself, but only once A-D already agree ------------------
    probe = "not_run"
    probe_detail = ""
    if not failures and logging_enabled:
        probe, probe_detail = _probe_put_bucket_logging(logging_enabled)
        if probe == "rejected":
            failures.append(
                "S3 itself refused the deployed logging configuration with "
                "InvalidTargetBucketForLogging when it was re-submitted "
                f"unchanged: {probe_detail}. The destination bucket cannot "
                "receive these access logs"
            )

    return {
        "outcome": "pass" if not failures else "fail_stale",
        "failures": failures,
        "notes": notes,
        "destination_object_ownership": ownership,
        "destination_acl_group_uris": sorted(set(acl_uris)),
        "source_logging": logging_enabled,
        "destination_bucket_policy_present": policy is not None,
        "granting_statements": sorted(granting),
        "blocking_statements": sorted(blocking),
        "put_bucket_logging_probe": probe,
    }


def poll() -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        try:
            last = observe()
        except AwsAbsent as exc:
            # Every read helper above already converts a "does not exist"
            # answer into a fact it can report. The one call that does NOT is
            # the PutBucketLogging probe, because a `NoSuchBucket` there means
            # one of the two buckets the agent was asked to keep has been
            # deleted -- a real verdict about the agent's work, not an outage,
            # and therefore fail_stale rather than not_verifiable. Handled here
            # rather than left to propagate: an uncaught exception would print
            # a traceback and NO JSON object, which the verifier reads as a
            # missing outcome rather than as any verdict at all.
            return {
                "outcome": "fail_stale",
                "failures": [
                    f"AWS reports a resource this scenario depends on no longer "
                    f"exists: {exc}"
                ],
            }
        except AwsUnavailable as exc:
            return {"outcome": "not_verifiable", "reason": str(exc), "failures": []}
        if last["outcome"] == "pass" or time.monotonic() >= deadline:
            last["polled_for_s"] = None if last["outcome"] == "pass" else POLL_TIMEOUT_S
            return last
        time.sleep(POLL_INTERVAL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description="live oracle (see module docstring)")
    parser.add_argument(
        "--expect",
        choices=["ok", "stale"],
        default=None,
        help="fixture-invoked shape: assert the observed outcome. Exits non-zero "
        "when the account contradicts the assertion.",
    )
    args = parser.parse_args()

    result = poll()
    result["scenario"] = "s3-acl-vs-object-ownership-log-delivery"
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
