#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (spec_model.LiveCheck.hand_authored =
true; specs/SCHEMA.md §5). The live, GATING oracle of the brownfield scenario
`named-resource-replacement` (specs/named-resource-replacement.yaml,
DECISIONS.md Amendment 28).

Regenerating this scenario (`make gen SPEC=specs/named-resource-replacement.yaml`)
will NOT overwrite this file: gen.py's write_tests_dir() is destructive-safe for
tests/live_check.py whenever spec.verifier.live_check.hand_authored is true
(SCHEMA.md §8.2 point 8).

ARM-AGNOSTIC BY CONSTRUCTION. This file is byte-identical in all three arms'
task directories. It asks EC2 what is actually deployed; it never looks at the
workspace, the toolchain, or any synth/plan artifact. That is the point: the
whole scenario turns on the fact that the three arms' *static* artifacts agree
while their *deployed outcomes* need not, so the live oracle must not be able to
tell which arm produced the account state it is reading.

WHY A LIVE CHECK IS THE ONLY THING THAT CAN SEE THIS CATCH
==========================================================
The requested change is a rename of an explicitly-named security group that an
interface VPC endpoint is using. On the Terraform-shaped arms the default
replacement order is destroy-then-create; EC2 refuses to delete a group that is
still attached to the endpoint's ENI (`DependencyViolation`), so the apply
aborts PART-WAY: the configuration now names the new group, nothing in the
account changed, and re-running attempts the same failing destroy. Every static
tier passes throughout -- `terraform show -json` does not even emit the
`lifecycle` block that fixes it (verified directly against terraform 1.15.8 /
hashicorp/aws 6.58.0), so there is nothing for a plan-JSON assert to read.

WHAT IT ASSERTS (all three are properties of the ACCOUNT, not of the code):
  1. a security group named `platform-internal-services-ssm-endpoint` exists;
  2. NO security group named `internal-services-ssm-endpoint` remains -- this is
     the half-applied-rename detector. A failed destroy-then-create leaves the
     OLD group in place; a successful create-before-destroy (or CloudFormation's
     own create-new-then-delete-old) does not;
  3. the SSM interface VPC endpoint is `available` and its attached groups
     include the NEW group's id -- i.e. the endpoint follows the rename rather
     than being orphaned or deleted.

Assertion 2 is what makes this oracle discriminating rather than decorative: an
agent whose apply died half-way still satisfies (1) on a retry-until-it-sticks
approach only if the old group is genuinely gone.

OUTCOME CONTRACT (SCHEMA.md §5, gating): a JSON object on stdout with an
`outcome` of
    "pass"           -- all three assertions hold;
    "fail_stale"     -- the account contradicts at least one of them (this is a
                        real, legitimate verdict about the agent's work);
    "not_verifiable" -- the check could not be run (no `aws` CLI, no
                        credentials, an API error). Fail-closed: the generated
                        tests/test.sh downgrades reward to 0.0 for anything that
                        is not "pass", and an unverifiable claim must never
                        silently earn reward.

TWO CALL SHAPES, matching this repo's existing convention (see
apigw-redeploy's own live_check.py):
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

OLD_GROUP_NAME = "internal-services-ssm-endpoint"
NEW_GROUP_NAME = "platform-internal-services-ssm-endpoint"
ENDPOINT_SERVICE_SUFFIX = ".ssm"

# Interface-endpoint ENI re-association after a security-group swap is not
# instantaneous. Sampled rather than read once, for the same reason
# apigw-redeploy's own live check polls: a single sample taken in the first
# seconds after a deploy turns a correct solution into a spurious failure.
POLL_TIMEOUT_S = 120
POLL_INTERVAL_S = 10


class AwsUnavailable(RuntimeError):
    """The `aws` CLI could not be run, or refused the call -- NOT a verdict."""


def _aws(*args: str) -> Any:
    try:
        proc = subprocess.run(
            ["aws", *args, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: {exc}") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AwsUnavailable(f"aws {' '.join(args)}: unparseable output") from exc


def _groups_named(name: str) -> list[dict]:
    data = _aws(
        "ec2",
        "describe-security-groups",
        "--filters",
        f"Name=group-name,Values={name}",
    )
    return data.get("SecurityGroups", [])


def _ssm_interface_endpoints() -> list[dict]:
    data = _aws(
        "ec2",
        "describe-vpc-endpoints",
        "--filters",
        "Name=vpc-endpoint-type,Values=Interface",
    )
    return [
        e
        for e in data.get("VpcEndpoints", [])
        if str(e.get("ServiceName", "")).endswith(ENDPOINT_SERVICE_SUFFIX)
    ]


def observe() -> dict:
    """One sample of the three assertions. Raises AwsUnavailable if the account
    could not be read at all (which is never a verdict about the agent)."""
    new_groups = _groups_named(NEW_GROUP_NAME)
    old_groups = _groups_named(OLD_GROUP_NAME)
    endpoints = _ssm_interface_endpoints()

    failures: list[str] = []
    if not new_groups:
        failures.append(
            f"no security group named {NEW_GROUP_NAME!r} exists in this account "
            "-- the rename was not applied"
        )
    if old_groups:
        failures.append(
            f"a security group named {OLD_GROUP_NAME!r} is still present "
            f"(ids: {[g.get('GroupId') for g in old_groups]}) -- the rename is "
            "HALF-APPLIED: the configuration names the new group but the account "
            "still holds the old one"
        )

    new_ids = {g.get("GroupId") for g in new_groups}
    attached = [
        e
        for e in endpoints
        if new_ids & {gi.get("GroupId") for gi in e.get("Groups", [])}
    ]
    if not endpoints:
        failures.append(
            "no SSM interface VPC endpoint found -- the endpoint the security "
            "group protects is gone"
        )
    elif not attached:
        failures.append(
            "the SSM interface VPC endpoint is not attached to the renamed "
            f"security group (endpoint groups: "
            f"{[gi.get('GroupName') for e in endpoints for gi in e.get('Groups', [])]})"
        )
    else:
        states = {e.get("State") for e in attached}
        if states - {"available"}:
            failures.append(
                f"the SSM interface VPC endpoint is in state {sorted(states)}, "
                "not 'available'"
            )

    return {
        "outcome": "pass" if not failures else "fail_stale",
        "failures": failures,
        "new_group_ids": sorted(i for i in new_ids if i),
        "old_group_ids": sorted(
            str(g.get("GroupId")) for g in old_groups if g.get("GroupId")
        ),
        "ssm_interface_endpoints": sorted(
            str(e.get("VpcEndpointId")) for e in endpoints if e.get("VpcEndpointId")
        ),
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
    result["scenario"] = "named-resource-replacement"
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
