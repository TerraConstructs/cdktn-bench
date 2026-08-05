"""gates/preflight.py — Gate 1 of the three-gate integrity pattern.

Runs an arm's *real* in-container preflight script (the same one
``arms/<arm>/preflight.sh`` / ``make preflight`` invoke — see
``docs/lex00-bench-diff.md`` "three-gate pattern" and each arm's own
``environment/preflight.sh``) and reports a machine-readable verdict.

Contract: "the arm's toolchain actually works in its container, offline"
(no AWS credentials, ``--network none``). Exit code 0 iff the in-container
script exited 0; nonzero otherwise, with a JSON report on stdout either way
(success or failure) so callers never have to re-derive what happened from
raw docker output.

This gate does not build images — it assumes ``make build-arms`` (or each
arm's own ``./preflight.sh`` without ``SKIP_BUILD=1``) already produced the
image. A missing image is reported as a failure (``reason: "image-not-found"``),
not silently skipped, matching the RECON.md finding that a degraded/missing
arm must never look like a clean gate pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent

# In-container entry point per arm — must match arms/<arm>/preflight.sh and
# the root Makefile's `preflight` target exactly (see DECISIONS.md "Arm
# build-context contract" / "Agent-container baseline contract"). hcl-raw
# is the odd one out (/opt/preflight/preflight.sh); the other two land at
# /usr/local/bin/preflight.sh.
ARM_ENTRYPOINTS: dict[str, str] = {
    "awscdk": "/usr/local/bin/preflight.sh",
    "hcl-raw": "/opt/preflight/preflight.sh",
    "terraconstructs": "/usr/local/bin/preflight.sh",
}

# Applied uniformly to every arm, matching the root Makefile's `preflight`
# target (it does not special-case terraconstructs's higher memory need —
# see DECISIONS.md "Memory floor for tsc-heavy arms": 4g covers all three).
DEFAULT_MEMORY = "4g"
DEFAULT_NETWORK = "none"
DEFAULT_TIMEOUT_SEC = 300

# Cap how much of stdout/stderr rides in the JSON report so a runaway/verbose
# preflight script can't blow up whatever reads the report.
_OUTPUT_CAP_CHARS = 20_000


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


class _Runner(Protocol):
    def __call__(self, cmd: list[str], **kwargs: Any) -> _CompletedProcessLike: ...


def _tail(text: str, cap: int = _OUTPUT_CAP_CHARS) -> str:
    if text is None:
        return ""
    if len(text) <= cap:
        return text
    return f"...[truncated {len(text) - cap} chars]...\n" + text[-cap:]


def _classify_failure(returncode: int | None, stdout: str, stderr: str) -> str:
    """Best-effort machine-readable failure category from exit code + output.

    Positive-evidence text matching over ``$? == 0`` (RECON.md /
    docs/lex00-bench-diff.md "must_match over exit codes" — the same
    principle applied to *why* something failed, not just *whether*).
    """
    combined = f"{stdout}\n{stderr}"
    lowered = combined.lower()
    if "unable to find image" in lowered or "no such image" in lowered or "pull access denied" in lowered:
        return "image-not-found"
    if "cannot connect to the docker daemon" in lowered or "is the docker daemon running" in lowered:
        return "docker-daemon-unreachable"
    if returncode == 137 or "oomkilled" in lowered or "out of memory" in lowered:
        return "oom-killed"
    if "executable file not found" in lowered or "no such file or directory" in lowered and "entrypoint" in lowered:
        return "entrypoint-not-found"
    if returncode is None:
        return "runner-error"
    return f"preflight-script-failed (exit {returncode})"


def run_preflight(
    arm: str,
    image: str | None = None,
    memory: str | None = DEFAULT_MEMORY,
    network: str | None = DEFAULT_NETWORK,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    runner: _Runner = subprocess.run,
) -> dict[str, Any]:
    """Run one arm's in-container preflight and return a JSON-able report.

    ``runner`` is injectable (defaults to ``subprocess.run``) so tests can
    simulate docker outcomes (missing image, OOM, daemon down, timeout)
    without a real Docker daemon.
    """
    if arm not in ARM_ENTRYPOINTS:
        return {
            "gate": "preflight",
            "arm": arm,
            "ok": False,
            "exit_code": None,
            "reason": f"unknown arm {arm!r} (known: {sorted(ARM_ENTRYPOINTS)})",
        }

    entrypoint = ARM_ENTRYPOINTS[arm]
    image = image or f"cdktn-bench/{arm}:dev"

    cmd = ["docker", "run", "--rm"]
    if network:
        cmd += ["--network", network]
    if memory:
        cmd += ["--memory", memory]
    cmd += ["--entrypoint", entrypoint, image]

    base_report = {
        "gate": "preflight",
        "arm": arm,
        "image": image,
        "entrypoint": entrypoint,
        "cmd": cmd,
    }

    started = time.monotonic()
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return {
            **base_report,
            "ok": False,
            "exit_code": None,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout": "",
            "stderr": "",
            "reason": f"docker binary not found: {exc}",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            **base_report,
            "ok": False,
            "exit_code": None,
            "duration_sec": round(time.monotonic() - started, 3),
            "stdout": _tail(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
            "stderr": _tail(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")),
            "reason": f"preflight timed out after {timeout}s",
        }

    duration = round(time.monotonic() - started, 3)
    ok = proc.returncode == 0
    stdout = _tail(proc.stdout or "")
    stderr = _tail(proc.stderr or "")

    return {
        **base_report,
        "ok": ok,
        "exit_code": proc.returncode,
        "duration_sec": duration,
        "stdout": stdout,
        "stderr": stderr,
        "reason": None if ok else _classify_failure(proc.returncode, stdout, stderr),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate 1: run an arm's real in-container preflight and report a machine-readable verdict."
    )
    parser.add_argument("arm", choices=sorted(ARM_ENTRYPOINTS), help="Arm name.")
    parser.add_argument("--image", default=None, help="Override image tag (default: cdktn-bench/<arm>:dev).")
    parser.add_argument("--memory", default=DEFAULT_MEMORY, help=f"docker run --memory (default: {DEFAULT_MEMORY}; pass '' to omit).")
    parser.add_argument("--network", default=DEFAULT_NETWORK, help=f"docker run --network (default: {DEFAULT_NETWORK}; pass '' to omit).")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SEC, help="Seconds before the preflight run is killed.")
    parser.add_argument("--json-out", default=None, help="Also write the JSON report to this path.")
    args = parser.parse_args(argv)

    report = run_preflight(
        args.arm,
        image=args.image,
        memory=args.memory or None,
        network=args.network or None,
        timeout=args.timeout,
    )

    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n")

    if report["ok"]:
        return 0
    exit_code = report.get("exit_code")
    return exit_code if isinstance(exit_code, int) and exit_code != 0 else 1


if __name__ == "__main__":
    sys.exit(main())
