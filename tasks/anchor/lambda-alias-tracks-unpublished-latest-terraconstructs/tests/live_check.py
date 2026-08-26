#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (spec_model.LiveCheck.hand_authored =
true; specs/SCHEMA.md §5). The live, GATING oracle of the brownfield scenario
`lambda-alias-tracks-unpublished-latest`
(specs/lambda-alias-tracks-unpublished-latest.yaml, DECISIONS.md Amendments 28
and 31).

Regenerating this scenario will NOT overwrite this file: gen.py's
write_tests_dir() is destructive-safe for tests/live_check.py whenever
spec.verifier.live_check.hand_authored is true (SCHEMA.md §8.2 point 8).

ARM-AGNOSTIC BY CONSTRUCTION. This file is byte-identical in all three arms'
task directories. It asks Lambda what is actually deployed; it never reads the
workspace, the toolchain, or any synth/plan artifact, and it never branches on
which arm produced the account. It does not even hardcode the alias's NAME --
it reads the function's alias list and uses whatever single alias is there --
because the alias's physical name is composed by the L2 on one arm and typed
literally on the other two, and an oracle that had to know that would be an
oracle that can tell the arms apart.

WHY A LIVE CHECK IS THE ONLY THING THAT CAN SEE THIS CATCH ON awscdk
====================================================================
The requested change is a configuration change (`QUOTE_CURRENCY`: EUR -> USD) on
a function that callers reach through an alias. A published Lambda VERSION is an
immutable snapshot of the function's code AND configuration; an alias names one
version. The naive change edits the function, deploys successfully, and leaves
the alias naming the version that was published before -- so the deploy is green
everywhere and the callers still get euros.

On the Terraform arms the alias's target is a plain value in the graded plan
JSON, so tier 0 catches it. On awscdk it is not: the poisoned stack
(`new lambda.Version(this, "ReleasedVersion", { lambda: fn })`) and the corrected
one (`version: fn.currentVersion`) synthesize CloudFormation templates that are
identical in every Type and every Properties block, differing only in the
CDK-generated logical id of the single `AWS::Lambda::Version` resource (measured
directly against the arm's pinned aws-cdk-lib 2.263.0; the awscdk arm's
solution/broken/alias-still-serves-the-previous-version/solve.sh re-proves it
mechanically on every `make falsifiability` run). The difference exists only in
the account, which is where this file looks.

WHAT IT ASSERTS (all properties of the ACCOUNT, never of the code):
  1. the function still exists and still has EXACTLY ONE alias -- "solve it by
     deleting the alias" and "solve it by adding a second one next to the old"
     both fail here, and neither can leave the next assertion ambiguous;
  2. THE DISCRIMINATING ONE: resolving the function's configuration THROUGH that
     alias's qualifier returns QUOTE_CURRENCY == "USD". `workspace_seed.deploy`'s
     own live assert
     `version-one-still-carries-the-configuration-being-changed` proves this is
     "EUR" BEFORE the agent starts, so a "pass" here is a measurement of the
     agent's change and not a property of the account it walked into;
  3. the function's own (unqualified, $-latest) configuration is USD too -- which
     separates "deployed, but the alias did not follow" from "never deployed at
     all". Both fail; the operator should be able to tell them apart from the
     JSON without re-reading the account.

OUTCOME CONTRACT (SCHEMA.md §5, gating): a JSON object on stdout with an
`outcome` of
    "pass"           -- every assertion holds;
    "fail_stale"     -- the account contradicts at least one of them. This is a
                        real verdict about the agent's work, and it INCLUDES the
                        case where the function or its alias no longer exists:
                        Lambda answering `ResourceNotFoundException` is the
                        account telling us something true, not a failure to read
                        it;
    "not_verifiable" -- the check could not be run at all (no `aws` CLI, no
                        credentials, a throttle, an unparseable response).
                        Fail-closed: the generated tests/test.sh downgrades
                        reward to 0.0 for anything that is not "pass", and an
                        unverifiable claim must never silently earn reward.

TWO CALL SHAPES, matching this repo's convention:
  * verifier-invoked, no args -- prints the JSON, always exits 0. The exit code
    is not the verdict; `.outcome` is.
  * fixture-invoked, `--expect {ok,stale}` -- used by solution/solve.sh and
    solution/broken/*/solve.sh under LIVE=1. Prints the same JSON and exits
    non-zero when the observed outcome contradicts what the caller asserted.
    `--expect stale` is corroboration, never a proof on its own: see the broken
    fixtures' own self-proofs before they are allowed to call it.

NO LIVE AWS CALL HAPPENS OFFLINE. With no credentials the `aws` invocations fail
and this reports "not_verifiable" -- which is why `make falsifiability` never
reaches this file: it runs tests/static_tiers.sh directly, not tests/test.sh.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any

FUNCTION_NAME = "cdktn-bench-quote-service"
ENV_KEY = "QUOTE_CURRENCY"
REQUIRED_VALUE = "USD"

# A CloudFormation stack update returns when the alias update is complete and a
# terraform apply returns after UpdateAlias, so a single sample is usually
# right. Polled anyway, for the same reason the sibling brownfield scenario
# polls: one sample taken in the first seconds after a deploy turns a correct
# solution into a spurious failure, and a spurious failure is indistinguishable
# from the catch this file exists to detect.
POLL_TIMEOUT_S = 90
POLL_INTERVAL_S = 10


class AwsUnavailable(RuntimeError):
    """The `aws` CLI could not be run, or failed for a reason that is NOT the
    account answering a question. Never a verdict about the agent."""


class ResourceMissing(RuntimeError):
    """Lambda answered `ResourceNotFoundException`. This IS the account
    answering: the thing the change request talks about is not there."""


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
        stderr = (proc.stderr or "").strip()
        # THE ONE CLASSIFICATION THAT MATTERS. Every other non-zero exit --
        # NoCredentialsError, NoRegionError, throttling, a broken CLI -- means
        # "we could not ask", and reporting that as `fail_stale` would score an
        # agent 0.0 for a harness fault. ResourceNotFoundException means "we
        # asked and the answer is: it is gone", which is a verdict.
        if "ResourceNotFoundException" in stderr:
            raise ResourceMissing(f"aws {' '.join(args)}: {stderr}")
        raise AwsUnavailable(f"aws {' '.join(args)}: exit {proc.returncode}: {stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: unparseable output") from exc


def _currency_of(qualifier: str | None) -> str | None:
    args = ["lambda", "get-function-configuration", "--function-name", FUNCTION_NAME]
    if qualifier is not None:
        args += ["--qualifier", qualifier]
    cfg = _aws(*args)
    variables = (cfg.get("Environment") or {}).get("Variables") or {}
    value = variables.get(ENV_KEY)
    return None if value is None else str(value)


def observe() -> dict:
    """One sample. Raises AwsUnavailable if the account could not be READ at all
    (never a verdict); a ResourceNotFoundException anywhere below IS a verdict
    and is folded into `failures`."""
    failures: list[str] = []
    detail: dict[str, Any] = {"function_name": FUNCTION_NAME}

    try:
        aliases = _aws("lambda", "list-aliases", "--function-name", FUNCTION_NAME).get(
            "Aliases", []
        )
    except ResourceMissing as exc:
        return {
            "outcome": "fail_stale",
            "failures": [
                f"the function {FUNCTION_NAME!r} does not exist in this account "
                f"-- the workspace this change request was made against is gone "
                f"({exc})"
            ],
            **detail,
        }

    detail["aliases"] = sorted(
        f"{a.get('Name')}->{a.get('FunctionVersion')}" for a in aliases
    )

    if len(aliases) != 1:
        failures.append(
            f"the function has {len(aliases)} alias(es) ({detail['aliases']}), "
            "not exactly one -- every caller reaches this function through its "
            "alias, so neither removing it nor leaving a second one beside it "
            "is the change that was asked for"
        )

    # ---- assertion 2: THE DISCRIMINATING ONE --------------------------------
    # Read through the alias's own qualifier: this is literally what a caller
    # gets. It is the only assertion whose pre-agent value is pinned by
    # workspace_seed.deploy.live_asserts (to "EUR"), which is what stops it from
    # being satisfiable by an account the agent never touched.
    if len(aliases) == 1:
        qualifier = str(aliases[0].get("Name"))
        detail["alias_name"] = qualifier
        detail["alias_function_version"] = aliases[0].get("FunctionVersion")
        try:
            served = _currency_of(qualifier)
        except ResourceMissing as exc:
            served = None
            failures.append(
                f"the alias {qualifier!r} names a function version that no longer "
                f"resolves ({exc})"
            )
        detail["currency_served_through_the_alias"] = served
        if served != REQUIRED_VALUE:
            failures.append(
                f"callers going through the alias {qualifier!r} (which names "
                f"version {aliases[0].get('FunctionVersion')!r}) still get "
                f"{ENV_KEY}={served!r}, not {REQUIRED_VALUE!r}"
            )

    # ---- assertion 3: separate "never deployed" from "alias did not follow" --
    try:
        unqualified = _currency_of(None)
    except ResourceMissing as exc:
        unqualified = None
        failures.append(f"the function's own configuration is unreadable ({exc})")
    detail["currency_on_the_function_itself"] = unqualified
    if unqualified != REQUIRED_VALUE:
        failures.append(
            f"the function's own configuration still carries {ENV_KEY}="
            f"{unqualified!r} -- the change was never deployed at all"
        )

    return {"outcome": "pass" if not failures else "fail_stale", "failures": failures, **detail}


def poll() -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        try:
            last = observe()
        except AwsUnavailable as exc:
            return {"outcome": "not_verifiable", "reason": str(exc), "failures": []}
        if last["outcome"] == "pass" or time.monotonic() >= deadline:
            last["polled_for_s"] = None if last["outcome"] == "pass" else POLL_TIMEOUT_S
            return last
        time.sleep(POLL_INTERVAL_S)


def main() -> int:
    parser = argparse.ArgumentParser(description="live oracle")
    parser.add_argument(
        "--expect",
        choices=["ok", "stale"],
        default=None,
        help="fixture-invoked shape: assert the observed outcome. Exits non-zero "
        "when the account contradicts the assertion.",
    )
    args = parser.parse_args()

    result = poll()
    result["scenario"] = "lambda-alias-tracks-unpublished-latest"
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
