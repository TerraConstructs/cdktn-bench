#!/usr/bin/env python3
"""tests/live_check.py -- HAND-AUTHORED (spec_model.LiveCheck.hand_authored
= true; SCHEMA.md §5), Slice G (apigw-redeploy fix pass, 2026-08-06).
Regenerating this scenario (`make gen SPEC=specs/apigw-redeploy.yaml`) will
NOT overwrite this file (gen.py's write_environment/generate_arm is
destructive-safe for tests/live_check.py whenever
spec.verifier.live_check.hand_authored is true -- mirrors solution/solve.sh's
own destructive-safe convention, SCHEMA.md §8.2 point 8).

WHY THIS FILE EXISTS (fixes verified findings from the live-discriminator
review, 2026-08-06):

  Finding 1 (blocker) -- "correct solutions re-deploy and serve the change"
  was FALSE as built: every reference solution's own solve.sh curled
  /status exactly once, immediately after the second apply/deploy, and
  API Gateway stage-propagation latency (measured: hcl-raw 200 at t=30s,
  awscdk/terraconstructs 200 at t=60s -- 403 before that) meant every one
  of them failed their own live check ~100% of the time. Fix: this module
  is the ONE place that polls, bounded, with real margin (POLL_TIMEOUT_S
  below) -- both solution/solve.sh and solution/broken/*/solve.sh call
  into it now instead of each hand-rolling its own single curl.

  Finding 2 (blocker) -- the two hcl_raw negatives' own "did the trap
  fire" checks fired on `STATUS_CODE != 200` measured ONCE, immediately
  after the second apply -- exactly the same 403 a CORRECT solution also
  produces at that instant (during the propagation window Finding 1
  documents). Fix: `check_stale()` below polls the FULL window (never
  early-exits on a single non-200 sample) and the caller additionally
  compares the deployment id observed after apply #1 against the one
  observed after apply #2 -- a real, positive discriminator ("this is
  still the OLD deployment"), not an absence-of-evidence sample.

  Finding 3 (blocker) -- the originally-proposed live_check contract
  (">=2 deployments exist, stage points at the newest one") is FALSE for
  every correct solution on every arm (create_before_destroy /
  CFN-replacement semantics mean exactly ONE deployment survives after a
  successful redeploy, not >=2) and is non-discriminating besides (a
  stale-serving stage also, trivially, "points at the newest deployment
  IT knows about" -- there is only ever one candidate). Fix: `check_ok()`
  below asserts ONLY sound, post-hoc, BEHAVIORAL facts -- GET /status
  returns the exact modified body, and GET /hello + GET /version still
  return 200 (no regression) -- no deployment-count or stage-pointer
  assertion anywhere in this file.

  Finding 5 (major) -- the two broken fixtures used to self-judge
  ("expected to fail the trap-check, i.e. exit non-zero") with duplicated,
  ad hoc, non-discriminating logic instead of letting a shared, testable
  oracle decide. Fix: `main()`'s `--expect {ok,stale}` CLI is the ONE
  shared entry point solution/solve.sh and solution/broken/*/solve.sh
  both call (with LIVE=1) -- the SAME poll/compare implementation on both
  sides, differing only in which outcome is asserted, not in how the
  observation is made.

See docs/apigw-redeploy-mechanics.md §6(c) for the underlying "why only a
live loop can see this" mechanics this module exists to check, and
DECISIONS.md "Slice G" for how this fits the rest of the schema/generator
changes this fix pass made.

  Fix-round-3 (2026-08-07, DECISIONS.md Slice G amendment) -- GATING:
  the verifier-invoked shape below used to be purely observational
  (SCHEMA.md §5's original non-gating invariant) -- but
  triggers-incomplete-hash is a `predicted_tier_caught: "live"` catch BY
  CONSTRUCTION (every static tier passes it identically to a correct
  solution, see that catch's own description in specs/apigw-redeploy.yaml),
  so a non-gating live check meant the one catch this whole scenario
  exists to motivate could never cost a real trial any reward. This
  scenario's task.toml now sets SPEC_LIVE_CHECK_GATING=true
  (verifier.live_check.gating), which generator/gen.py's build_test_sh
  reads to fold this module's own `outcome` field into
  /logs/verifier/reward.txt. Cleanup ownership also moved in this same
  amendment: the agent is no longer instructed to delete the resources it
  created (specs/apigw-redeploy.yaml's instruction no longer has a
  cleanup paragraph) -- this file (and the static tiers) now run while
  the agent's real, live deployment is still standing, and the
  benchmark's own post-trial mutating reset (ResourceManager.reset_scenarios,
  outside this repo) tears it down afterward. See DECISIONS.md for the
  full ordering rationale.

Two call shapes:

  Verifier-invoked (tests/test.sh, after the agent's own trial, while its
  live deployment is still standing -- cleanup ownership moved to the
  post-trial reset, see above): `python3 live_check.py` with no args.
  Discovers the agent's deployed API (from
  /logs/agent/agent-output.json's `api_url` field if present, else by the
  fixed REST API name `apigw-redeploy-api` via `aws apigateway
  get-rest-apis`/`get-stages`) and runs check_ok() against it, writing a
  JSON report (always including an `outcome` key -- "pass" / "fail_stale"
  / "not_verifiable", see main()'s own inline comment) to stdout
  (redirected by test.sh to /logs/verifier/live_check-result.json).
  GATING for this scenario (see above) -- test.sh downgrades reward.txt to
  0.0 whenever `outcome` is not "pass".

  Fixture-invoked (solution/solve.sh, solution/broken/*/solve.sh; LIVE=1
  only): `python3 live_check.py --api-url "$API_URL" --expect {ok,stale}
  [--deployment-id-before ID1 --deployment-id-after ID2]`. Exits 0 iff the
  EXPECTED outcome was observed (real deploy served the change / stale
  deployment genuinely never served it), non-zero otherwise -- a normal,
  gating exit code for THIS use (always was, independent of the
  verifier-invoked shape's own gating status above).
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

# Finding 1: 60s was NOT enough margin (two of three arms needed exactly
# 60s in the reviewer's own measurement: hcl-raw 200 at t=30s; awscdk and
# terraconstructs 200 at t=60s, both 403 at every earlier sample) -- use
# 180s for real margin, per the fix_hint's own ">=120s, use 120-180s".
POLL_TIMEOUT_S = 180
POLL_INTERVAL_S = 5
# /hello and /version are Lambda-proxy integrations, unaffected by the
# deployment-propagation lag the MOCK /status route hits (control test in
# the review: the same rev2 config applied ONCE from scratch served
# /status 200 at t=0) -- a short, cheap poll is a safety net, not the
# primary fix target.
REGRESSION_POLL_TIMEOUT_S = 30

EXPECTED_STATUS_BODY = {"status": "ok", "routes": 3}
REST_API_NAME = "apigw-redeploy-api"
STAGE_NAME = "prod"

AGENT_OUTPUT_PATH = Path("/logs/agent/agent-output.json")
LIVE_CHECK_RESULT_NOTE = (
    "GATING for this scenario (SPEC_LIVE_CHECK_GATING=true, DECISIONS.md "
    "Slice G amendment fix-round-3) -- tests/test.sh reads this JSON's "
    "own `outcome` field and downgrades /logs/verifier/reward.txt to 0.0 "
    "whenever it is not \"pass\""
)


def _http_get(url: str, timeout: float = 10.0) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 -- network is inherently flaky here
        return None, f"{type(exc).__name__}: {exc}"


def _status_body_matches(body: str) -> bool:
    try:
        return json.loads(body) == EXPECTED_STATUS_BODY
    except (json.JSONDecodeError, TypeError):
        return False


def _poll_until_true(url: str, predicate, timeout_s: float, interval_s: float) -> tuple[bool, list[dict]]:
    """Poll `url` every `interval_s` up to `timeout_s`; returns
    (observed, samples) where `observed` is True the first time
    `predicate(status, body)` is True. Always takes at least one sample."""
    deadline = time.monotonic() + timeout_s
    samples: list[dict] = []
    while True:
        status, body = _http_get(url)
        samples.append({"t": round(time.monotonic() - (deadline - timeout_s), 1), "status": status, "body": body[:500]})
        if predicate(status, body):
            return True, samples
        if time.monotonic() >= deadline:
            return False, samples
        time.sleep(interval_s)


def _poll_full_window_never_true(url: str, predicate, timeout_s: float, interval_s: float) -> tuple[bool, list[dict]]:
    """Finding 2's fix: poll the FULL window, never early-exiting on a
    single sample. Returns (never_observed, samples) -- `never_observed`
    is True iff `predicate` was False on EVERY sample across the whole
    window (i.e. the claimed staleness held up for the entire window, not
    just at t=0)."""
    deadline = time.monotonic() + timeout_s
    start = time.monotonic()
    samples: list[dict] = []
    never_observed = True
    while True:
        status, body = _http_get(url)
        samples.append({"t": round(time.monotonic() - start, 1), "status": status, "body": body[:500]})
        if predicate(status, body):
            never_observed = False
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_s)
    return never_observed, samples


def check_ok(api_url: str) -> dict[str, Any]:
    """The CORRECT-solution behavioral contract (finding 3): GET /status
    must return the exact modified body within POLL_TIMEOUT_S, AND GET
    /hello + GET /version must still return 200 (no regression). No
    deployment-count/stage-pointer assertion anywhere -- see this module's
    own header for why those were dropped."""
    base = api_url if api_url.endswith("/") else api_url + "/"

    status_ok, status_samples = _poll_until_true(
        base + "status",
        lambda status, body: status == 200 and _status_body_matches(body),
        POLL_TIMEOUT_S,
        POLL_INTERVAL_S,
    )
    hello_ok, hello_samples = _poll_until_true(
        base + "hello", lambda status, _body: status == 200, REGRESSION_POLL_TIMEOUT_S, POLL_INTERVAL_S
    )
    version_ok, version_samples = _poll_until_true(
        base + "version", lambda status, _body: status == 200, REGRESSION_POLL_TIMEOUT_S, POLL_INTERVAL_S
    )

    return {
        "expect": "ok",
        "pass": bool(status_ok and hello_ok and version_ok),
        "checks": {
            "status_served_modified_body": {"pass": status_ok, "samples": status_samples},
            "hello_no_regression": {"pass": hello_ok, "samples": hello_samples},
            "version_no_regression": {"pass": version_ok, "samples": version_samples},
        },
    }


def check_stale(
    api_url: str,
    deployment_id_before: str | None,
    deployment_id_after: str | None,
) -> dict[str, Any]:
    """The NEGATIVE-fixture behavioral contract (finding 2): the deployment
    id observed after apply #2 must EQUAL the one observed after apply #1
    (a real redeploy never happened), AND /status must stay non-200-with-
    the-modified-body across the SAME full poll window check_ok() uses --
    never a single early sample."""
    base = api_url if api_url.endswith("/") else api_url + "/"

    deployment_unchanged = (
        deployment_id_before is not None
        and deployment_id_after is not None
        and deployment_id_before == deployment_id_after
    )

    never_served, samples = _poll_full_window_never_true(
        base + "status",
        lambda status, body: status == 200 and _status_body_matches(body),
        POLL_TIMEOUT_S,
        POLL_INTERVAL_S,
    )

    return {
        "expect": "stale",
        "pass": bool(deployment_unchanged and never_served),
        "checks": {
            "deployment_id_unchanged": {
                "pass": deployment_unchanged,
                "before": deployment_id_before,
                "after": deployment_id_after,
            },
            "status_never_served_modified_body_full_window": {
                "pass": never_served,
                "window_s": POLL_TIMEOUT_S,
                "samples": samples,
            },
        },
    }


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=None, help="deployed stage invoke URL (fixture-invoked shape)")
    parser.add_argument("--expect", choices=["ok", "stale"], default=None, help="fixture-invoked shape: which outcome to assert")
    parser.add_argument("--deployment-id-before", default=None)
    parser.add_argument("--deployment-id-after", default=None)
    args = parser.parse_args()

    if args.expect is not None:
        # Fixture-invoked shape -- solution/solve.sh or
        # solution/broken/*/solve.sh, LIVE=1. Real, gating exit code.
        if not args.api_url:
            print("--expect requires --api-url", file=sys.stderr)
            return 2
        if args.expect == "ok":
            result = check_ok(args.api_url)
        else:
            result = check_stale(args.api_url, args.deployment_id_before, args.deployment_id_after)
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1

    # Verifier-invoked shape -- tests/test.sh, no args. GATING (fix-round-3,
    # DECISIONS.md Slice G amendment): this scenario's task.toml sets
    # SPEC_LIVE_CHECK_GATING=true, so tests/test.sh folds this branch's own
    # `outcome` field into /logs/verifier/reward.txt (AND semantics: final
    # reward requires the static tiers AND outcome=="pass"). Three possible
    # outcomes, always reported under the `outcome` key:
    #   "pass"           -- a deployed API was found and check_ok() (the
    #                        same behavioral contract the fixture-invoked
    #                        --expect ok shape asserts) succeeded.
    #   "fail_stale"     -- a deployed API was found but check_ok() did NOT
    #                        succeed within the poll window (the stage is
    #                        still serving stale content, or a regression
    #                        broke /hello or /version) -- this is the one
    #                        live-only signal that can ever catch
    #                        triggers-incomplete-hash.
    #   "not_verifiable" -- no deployed API could be discovered at all (no
    #                        /logs/agent/agent-output.json api_url field,
    #                        and no REST API named apigw-redeploy-api found
    #                        via `aws apigateway get-rest-apis`). Fails
    #                        closed, same as "fail_stale" below -- an
    #                        unverifiable claim must never silently earn
    #                        reward.
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
    result["outcome"] = "pass" if result["pass"] else "fail_stale"
    result["info"] = LIVE_CHECK_RESULT_NOTE
    json.dump(result, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
