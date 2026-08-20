#!/usr/bin/env python3
"""steps/01-initial-deploy/tests/live_check.py -- HAND-AUTHORED
(spec_model.LiveCheck.hand_authored = true; SCHEMA.md §5). Step-01 oracle of
the MULTI-STEP `apigw-redeploy` scenario (DECISIONS.md Amendments 26/27,
docs/prompt-decomposition-audit.md).

Regenerating this scenario (`make gen SPEC=specs/apigw-redeploy.yaml`) will
NOT overwrite this file: gen.py's write_tests_dir() is destructive-safe for
tests/live_check.py whenever spec.verifier.live_check.hand_authored is true,
per-step exactly as it already was for the single-step shape (SCHEMA.md §8.2
point 8).

WHY THIS STEP HAS ITS OWN FILE INSTEAD OF SHARING A LATER STEP'S.
=================================================================
Each step of a multi-step scenario carries its own oracle under
steps/<name>/tests/. This one asserts exactly what THIS step's prompt asks
for and nothing else. Two independent reasons it is not shared:

  1. NO-FORESHADOWING, defence in depth. Harbor uploads a step's tests/ into
     the container's /tests at that step's VERIFICATION (after its agent has
     run) and only empties /tests at the start of the following step's
     verification (harbor/verifier/verifier.py::_resolve_tests,
     harbor/trial/multi_step.py::_reset_shared_step_verifier_dirs). So this
     file is never visible during this step's own agent phase, and reusing a
     following step's file here would leak nothing TODAY. It is kept clean
     anyway: the property "no artifact reachable at this step describes a
     following one" should hold by construction, not by a Harbor ordering
     detail a future release could reasonably change. Nothing in this file
     names, implies, or hints at any work beyond this step's own.
  2. IT WOULD BE THE WRONG ORACLE. A following step's oracle asserts facts
     about a state this step's correct solution does not (and must not) have.
     Running it here would fail every correct solution to this step, and the
     min_reward hard gate (Amendment 26 §3) would abort the trial before the
     next prompt ever fired.

WHAT IT ASSERTS (behavioral only -- finding 3 of the 2026-08-06
live-discriminator review): `GET /hello` and `GET /version` each return HTTP
200 on the deployed stage. No deployment-count assertion, no stage-pointer
assertion -- both were shown to be false for correct solutions on at least
one arm.

POLLING. API Gateway stage propagation after a fresh deploy was measured at
up to 60 s (hcl-raw 200 at t=30s; awscdk and terraconstructs 200 at t=60s,
403 at every earlier sample) -- finding 1 of the same review, which made
every reference solution fail its own single-curl live check ~100% of the
time. These routes are sampled immediately after a first real deploy, the
riskiest moment for a spurious failure, so the poll carries real margin
(POLL_TIMEOUT_S) rather than taking one sample.

TWO CALL SHAPES:

  Verifier-invoked (steps/01-initial-deploy/tests/test.sh, no args). Discovers
  the deployed API -- from /logs/agent/agent-output.json's `api_url` field if
  present, else by the fixed REST API name via `aws apigateway
  get-rest-apis` -- and writes a JSON report to stdout (redirected by test.sh
  to /logs/verifier/live_check-result.json). GATING for this step (task.toml
  sets SPEC_LIVE_CHECK_GATING=true on it): test.sh downgrades reward.txt to
  0.0 whenever `outcome` is not "pass". Without this gate an agent could
  author perfect IaC, never deploy at all, and still pass this step's static
  tiers -- which grade the delivered file, not the account.

  Fixture-invoked (steps/01-initial-deploy/solution/solve.sh, LIVE=1 only):
  `python3 live_check.py --api-url URL --expect ok`. Real, gating exit code.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# See this file's header for the measurement this margin comes from.
POLL_TIMEOUT_S = 180
POLL_INTERVAL_S = 5

REST_API_NAME = "apigw-redeploy-api"
STAGE_NAME = "prod"
# The routes this step's prompt asks for, and the ONLY routes this file knows
# about. Deliberately not "the routes so far" or "the initial routes" --
# nothing here implies more are coming.
ROUTES = ("hello", "version")

AGENT_OUTPUT_PATH = Path("/logs/agent/agent-output.json")
LIVE_CHECK_RESULT_NOTE = (
    "GATING for this step (SPEC_LIVE_CHECK_GATING=true in this task's "
    "[steps.verifier] env) -- steps/01-initial-deploy/tests/test.sh reads this "
    "JSON's own `outcome` field and downgrades /logs/verifier/reward.txt to "
    "0.0 whenever it is not \"pass\". A reward below this step's min_reward "
    "aborts the trial (DECISIONS.md Amendment 26 §3)."
)


def _http_get(url: str, timeout: float = 10.0) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 -- network is inherently flaky here
        return None, f"{type(exc).__name__}: {exc}"


def _poll_until_true(url: str, predicate, timeout_s: float, interval_s: float) -> tuple[bool, list[dict]]:
    """Poll `url` every `interval_s` up to `timeout_s`; returns
    (observed, samples) where `observed` is True the first time
    `predicate(status, body)` is True. Always takes at least one sample."""
    deadline = time.monotonic() + timeout_s
    start = time.monotonic()
    samples: list[dict] = []
    while True:
        status, body = _http_get(url)
        samples.append({"t": round(time.monotonic() - start, 1), "status": status, "body": body[:500]})
        if predicate(status, body):
            return True, samples
        if time.monotonic() >= deadline:
            return False, samples
        time.sleep(interval_s)


def check_ok(api_url: str) -> dict[str, Any]:
    """This step's behavioral contract: every declared route serves HTTP 200
    on the deployed stage, within the poll window."""
    base = api_url if api_url.endswith("/") else api_url + "/"

    checks: dict[str, Any] = {}
    all_ok = True
    for route in ROUTES:
        ok, samples = _poll_until_true(
            base + route,
            lambda status, _body: status == 200,
            POLL_TIMEOUT_S,
            POLL_INTERVAL_S,
        )
        all_ok = all_ok and ok
        checks[f"{route}_serves_200"] = {"pass": ok, "samples": samples}

    return {"expect": "ok", "pass": all_ok, "checks": checks}


# --------------------------------------------------------------------------
# Verifier-invoked (no args) API discovery -- best-effort, `aws` CLI only
# (no boto3 dependency assumed in the arm image).
# --------------------------------------------------------------------------


def _discover_api_url_from_agent_output() -> str | None:
    if not AGENT_OUTPUT_PATH.exists():
        return None
    try:
        data = json.loads(AGENT_OUTPUT_PATH.read_text())
        url = data.get("api_url")
        return url if isinstance(url, str) and url else None
    except (json.JSONDecodeError, OSError):
        return None


def _discover_api_url_from_aws_cli() -> str | None:
    try:
        apis_raw = subprocess.run(
            ["aws", "apigateway", "get-rest-apis", "--output", "json"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        apis = json.loads(apis_raw).get("items", [])
        match = next((a for a in apis if a.get("name") == REST_API_NAME), None)
        if match is None:
            return None
        api_id = match["id"]
        region_raw = subprocess.run(
            ["aws", "configure", "get", "region"], capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        region = region_raw or "us-east-1"
        return f"https://{api_id}.execute-api.{region}.amazonaws.com/{STAGE_NAME}/"
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="step-01 live check for apigw-redeploy")
    parser.add_argument("--api-url", default=None, help="deployed stage invoke URL (fixture-invoked shape)")
    parser.add_argument("--expect", choices=["ok"], default=None, help="fixture-invoked shape: which outcome to assert")
    args = parser.parse_args()

    if args.expect is not None:
        # Fixture-invoked shape -- steps/01-initial-deploy/solution/solve.sh,
        # LIVE=1. Real, gating exit code.
        if not args.api_url:
            print("--expect requires --api-url", file=sys.stderr)
            return 2
        result = check_ok(args.api_url)
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1

    # Verifier-invoked shape -- test.sh, no args. Three possible outcomes,
    # always reported under the `outcome` key:
    #   "pass"             -- a deployed API was found and every route served.
    #   "fail_not_serving" -- a deployed API was found but at least one route
    #                          never returned 200 within the poll window.
    #   "not_verifiable"   -- no deployed API could be discovered at all.
    # The last two both fail closed: an unverifiable claim must never
    # silently earn reward, and must never unlock the next step's prompt.
    api_url = _discover_api_url_from_agent_output() or _discover_api_url_from_aws_cli()
    if api_url is None:
        json.dump(
            {
                "outcome": "not_verifiable",
                "pass": False,
                "note": "could not discover a deployed API (no /logs/agent/agent-output.json "
                f"api_url field, and no REST API named {REST_API_NAME!r} found via "
                "`aws apigateway get-rest-apis`)",
                "info": LIVE_CHECK_RESULT_NOTE,
            },
            sys.stdout,
            indent=2,
        )
        return 0
    result = check_ok(api_url)
    result["outcome"] = "pass" if result["pass"] else "fail_not_serving"
    result["info"] = LIVE_CHECK_RESULT_NOTE
    json.dump(result, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
