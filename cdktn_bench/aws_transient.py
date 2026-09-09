"""Transient-vs-resolved classification for AWS failures, host side.

The post-trial scenario reset fails the same two ways a live check's `aws`
call does: TRANSIENT -- a client-side timeout, a connection reset, throttling
or a 5xx, where the request never reached a decision -- or RESOLVED, where AWS
answered and the answer was an error. Only the first is worth re-asking.

The container-side twin of this table is the generated `tests/_live_lib.py`
(owned by `generator/gen.py`). Two copies exist because the arm images ship
python3 without this package; `cdktn_bench/tests/test_transient_classifier.py`
fails if the two marker tables ever diverge.

Reset-retry rule, bounds and contamination semantics: docs/runner.md
"Post-trial reset retry".
"""

from __future__ import annotations

import random

TRANSIENT = "transient"
RESOLVED = "resolved"

# Exception types the harness raises when its own deadline expires. Matched on
# the type, never on the message, and always RESOLVED: a phase that ran out of
# its configured seconds is a deterministic verdict, and re-running it spends
# another full reset pass -- minutes with the shard's exclusive gate held -- to
# reach the identical answer.
HARNESS_TIMEOUT_TYPES = (
    "PhaseTimeoutError",
    "TimeoutError",
    "asyncio.TimeoutError",
)

# Substrings matched case-insensitively against an exception's text. Anything
# not listed is RESOLVED and is never retried: re-running a reset that failed
# on AccessDenied or a deleted stack spends ten minutes reaching the same
# answer while the shard's exclusive gate is still held. Every timeout marker
# names the client side of a call; a bare "timed out" is forbidden, because it
# also matches a harness deadline and a stack-deletion deadline.
TRANSIENT_MARKERS = (
    "read timeout",
    "connect timeout",
    "connection timeout",
    "connection timed out",
    "client call timed out",
    "readtimeouterror",
    "connecttimeouterror",
    "endpointconnectionerror",
    "could not connect to the endpoint",
    "connection reset",
    "connection aborted",
    "connection broken",
    "requesttimeout",
    "throttling",
    "throttled",
    "requestlimitexceeded",
    "toomanyrequests",
    "rate exceeded",
    "slowdown",
    "serviceunavailable",
    "service unavailable",
    "internalerror",
    "internalfailure",
    "internal server error",
    "servicefailure",
    "(500)",
    "(502)",
    "(503)",
    "(504)",
)

# One reset attempt is minutes of stack diffing (7-13 on this corpus), so a
# budget over sleeps alone would bound nothing. The wall budget covers whole
# attempts, their own duration included, and a retry starts only while it is
# unspent: at most MAX_RESET_ATTEMPTS passes, adding at most
# MAX_RESET_RETRY_WALL_S plus the pass already running when it runs out -- less
# than the job the scenario's exclusive gate is held for.
MAX_RESET_ATTEMPTS = 3
MAX_RESET_RETRY_WALL_S = 900.0
RESET_BACKOFF_BASE_S = 30.0
RESET_BACKOFF_CAP_S = 240.0
BACKOFF_JITTER = 0.25


def classify(text: str) -> str:
    """TRANSIENT when `text` carries a marker above, RESOLVED otherwise.

    `text` is `"<ExceptionType>: <message>"`, so a harness timeout is caught by
    its type before any marker is consulted."""
    lowered = (text or "").lower()
    if any(lowered.startswith(f"{t.lower()}:") for t in HARNESS_TIMEOUT_TYPES):
        return RESOLVED
    return TRANSIENT if any(m in lowered for m in TRANSIENT_MARKERS) else RESOLVED


def reset_backoff_delays(attempts: int = MAX_RESET_ATTEMPTS, rand=random.random):
    """The sleep before each reset retry: exponential, capped, jittered upward.

    Jitter is added and never subtracted, so a delay is never shorter than its
    exponential floor; it exists so concurrent shards do not re-collide in
    lockstep against an API that is already refusing them."""
    for i in range(max(attempts - 1, 0)):
        base = min(RESET_BACKOFF_CAP_S, RESET_BACKOFF_BASE_S * (2**i))
        yield base * (1.0 + BACKOFF_JITTER * rand())
