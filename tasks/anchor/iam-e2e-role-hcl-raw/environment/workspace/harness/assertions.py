#!/usr/bin/env python3
"""harness/assertions.py -- runs ONLY under the WORKLOAD role's assumed
credentials (harness/validate.sh phase 5). stdlib + the `aws` CLI v2 only --
no boto3, matching every arm image's documented "python3 stdlib only, no
pip package ever installed" baseline (see each arm's own Dockerfile).

Two checks. Both must pass for the workload role's policy to be considered
correct by this harness:

  1. ssm get-parameters-by-path --with-decryption over the pre-provisioned
     fixture path, WITH DECRYPTION, must return BOTH parameters under it --
     the plain "config" one AND the SecureString "db-password" one,
     decrypted. ssm:GetParameter/ssm:GetParameters alone (what an L2
     grantRead()-style call derives on every library checked for this
     scenario) is not sufficient by itself for either half of this: the
     PATH read needs ssm:GetParametersByPath specifically, and the
     SecureString half additionally needs kms:Decrypt (with a
     kms:ViaService=ssm.<region>.amazonaws.com condition) on the
     pre-provisioned CMK.

  2. ec2:DescribeVolumes with a Name-tag filter -- a stand-in for the
     self-discovery call a real EC2 instance's own cloud-init would make to
     find "its own" attached volume by tag. This reduced module has no real
     EC2 instance to boot, so the harness makes this call directly under
     the workload role's own credentials instead.
"""
from __future__ import annotations

import json
import subprocess
import sys

APP_PATH_PREFIX = "/cdktn-bench-iam-e2e-role/app/"
EXPECTED_PARAM_NAMES = {APP_PATH_PREFIX + "config", APP_PATH_PREFIX + "db-password"}


def run_aws(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["aws", *args, "--output", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def check_parameters_by_path() -> str | None:
    code, out, err = run_aws(
        "ssm", "get-parameters-by-path", "--path", APP_PATH_PREFIX, "--with-decryption"
    )
    if code != 0:
        return f"ssm get-parameters-by-path denied or failed: {err.strip()}"
    try:
        params = json.loads(out).get("Parameters", [])
    except json.JSONDecodeError:
        return f"ssm get-parameters-by-path returned non-JSON output: {out[:200]!r}"
    names = {p.get("Name") for p in params}
    missing = EXPECTED_PARAM_NAMES - names
    if missing:
        return (
            f"ssm get-parameters-by-path did not return: {sorted(missing)} "
            "(the SecureString parameter missing suggests kms:Decrypt with "
            "kms:ViaService=ssm.*.amazonaws.com is not granted; either "
            "parameter missing suggests ssm:GetParametersByPath itself is "
            "not granted, or the resource scope does not cover this path)"
        )
    for p in params:
        if p.get("Name") == APP_PATH_PREFIX + "db-password" and not p.get("Value"):
            return "the SecureString parameter was returned but its Value is empty -- decryption likely failed silently"
    return None


def check_volume_self_discovery() -> str | None:
    code, out, err = run_aws(
        "ec2", "describe-volumes",
        "--filters", "Name=tag:Name,Values=cdktn-bench-iam-e2e-*",
    )
    if code != 0:
        return f"ec2 describe-volumes denied or failed: {err.strip()}"
    return None


def main() -> int:
    failures = [msg for msg in (check_parameters_by_path(), check_volume_self_discovery()) if msg]
    report = {"pass": not failures, "failures": failures}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
