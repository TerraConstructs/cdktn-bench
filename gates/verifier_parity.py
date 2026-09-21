"""Byte gate on the verifier's graded channel: the Python verifier must decide
every fixture exactly as the bash verifier did.

That channel is a CONTRACT, not a log -- `gates/emit_result.py`,
`gates/oracle_falsifiability.py` and harbor each parse part of it -- so this
gate records it for every fixture of every arm and compares two recordings:
`reward.txt`'s bytes, the set of files the run left under its logs dir with
each one's sha256, and the stdout lines those gates parse. Toolchain chatter is
not compared: it is the arm's own output, identical by construction.

Two surfaces are normalised, or a recording would diverge from itself: the
sandbox path, which is per-run and which jq quotes back in a message, and
`oracle-input.json`, compared by PRESENCE because the plan document it is built
from carries a `timestamp` and reorders its `references` arrays -- its bytes are
gated per fixture by `gates/hcl_merge_bytes.py` instead.

Usage:
    python gates/verifier_parity.py specs/foo.yaml [...] --out FILE.json
    python gates/verifier_parity.py --baseline HEAD.json --out NEW.json specs/...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import artifact_collector as ac  # noqa: E402
import oracle_falsifiability as of  # noqa: E402
from aws_stub import running_stub  # noqa: E402
from gen import ARM_DIRNAME  # noqa: E402
from spec_model import Arm, Spec  # noqa: E402
from spec_model import load_spec  # noqa: E402

# The stdout lines downstream parses. Everything else a run prints is the arm's
# own toolchain output.
_GRADED_LINE = re.compile(
    r"^(?:== .*==|\s*(?:PASS|FAIL)\s*\[.*|[A-Z][A-Z0-9_ ]* FAILED|MISSING ARTIFACT: .*)$"
)


# A sandbox path: every run gets its own, and several graded lines quote one
# (`MISSING ARTIFACT:`, and jq's own error text for an unresolvable assert).
_SCRATCH_PATH = re.compile(r"/[^\s\"']*/(?:falsifiability|parity)-[^\s\"']*")


def scrub(text: str) -> str:
    return _SCRATCH_PATH.sub("<scratch>", text)


def graded_lines(stdout: str) -> list[str]:
    return [scrub(line) for line in stdout.splitlines() if _GRADED_LINE.match(line)]


# The merged tier-1 input: recorded as present-or-absent, because the plan it is
# built from is not byte-reproducible across runs. See this module's docstring.
PRESENCE_ONLY = "oracle-input.json"


def logs_fingerprint(logs: Path) -> dict[str, str]:
    """Every file the run left under its logs dir, by sha256 of its text.

    Paths the sandbox makes run-specific are normalised out before hashing: a
    marker naming the scratch project dir would otherwise never match across two
    recordings.
    """
    fp: dict[str, str] = {}
    if not logs.is_dir():
        return fp
    for f in sorted(logs.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(logs))
        if rel == PRESENCE_ONLY:
            fp[rel] = "<present>"
            continue
        text = scrub(f.read_text(errors="replace"))
        fp[rel] = hashlib.sha256(text.encode()).hexdigest()[:16]
    return fp


def record(spec: Spec, env: dict[str, str], keep: ac.KeptTempDir,
           arms: tuple[Arm, ...]) -> dict[str, dict]:
    cells: dict[str, dict] = {}
    for arm in arms:
        for step, name, solve in ac.plan_runs(spec, arm):
            tdir = ac.tests_dir(ac.task_dir(spec, arm), step)
            if not (tdir / "test.sh").exists():
                continue
            key = f"{spec.id}/{ARM_DIRNAME[arm]}/{name}"
            run = of._run_solve(ac.task_dir(spec, arm), arm, solve, key,
                                step=step, env=env)
            work = keep.last
            logs = (work / "logs" / "verifier") if work else Path("/nonexistent")
            reward = logs / "reward.txt"
            cells[key] = {
                "reward_bytes": reward.read_text() if reward.is_file() else None,
                "logs": logs_fingerprint(logs),
                "graded": graded_lines(run.detail or ""),
            }
            ac.prune(work)
            print(f"  {key}: reward={cells[key]['reward_bytes']!r} "
                  f"logs={len(cells[key]['logs'])} lines={len(cells[key]['graded'])}",
                  flush=True)
    return cells


def compare(baseline: dict, new: dict) -> list[str]:
    problems = []
    for key in sorted(set(baseline) | set(new)):
        if key not in baseline:
            problems.append(f"{key}: present only in the new recording")
            continue
        if key not in new:
            problems.append(f"{key}: present only in the baseline")
            continue
        b, n = baseline[key], new[key]
        if b["reward_bytes"] != n["reward_bytes"]:
            problems.append(
                f"{key}: reward.txt {b['reward_bytes']!r} -> {n['reward_bytes']!r}")
        if b["logs"] != n["logs"]:
            for f in sorted(set(b["logs"]) | set(n["logs"])):
                if b["logs"].get(f) != n["logs"].get(f):
                    problems.append(
                        f"{key}: logs/{f} {b['logs'].get(f)} -> {n['logs'].get(f)}")
        if b["graded"] != n["graded"]:
            problems.append(f"{key}: graded stdout lines differ\n"
                            f"    baseline: {b['graded']}\n    new:      {n['graded']}")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="*", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--work", type=Path, help="where kept working copies land")
    ap.add_argument("--arm", action="append", dest="arms",
                    choices=list(ac.ARMS), help="restrict to one arm (repeatable)")
    args = ap.parse_args(argv)

    arms = tuple(args.arms) if args.arms else ac.ARMS
    work = args.work or (args.out.parent / (args.out.stem + "-work"))
    keep = ac.install(work)
    cells: dict[str, dict] = {}
    with running_stub() as env:
        for spec_path in args.specs:
            spec = load_spec(spec_path)
            print(f"==> {spec.id}", flush=True)
            cells.update(record(spec, env, keep, arms))
    args.out.write_text(json.dumps(cells, indent=2, sort_keys=True))
    print(f"wrote {args.out} ({len(cells)} fixtures)")

    if args.baseline is None:
        return 0
    problems = compare(json.loads(args.baseline.read_text()), cells)
    for p in problems:
        print(f"[DIVERGENT] {p}")
    print("verifier parity OK" if not problems
          else f"{len(problems)} divergence(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
