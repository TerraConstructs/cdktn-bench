#!/usr/bin/env python3
"""generator/check_parity.py — independent re-verification of prompt parity
(prereg §6, SCHEMA.md §8.2 point 2) across a generated scenario's arms.

Unlike gen.py's own in-process self_check_parity (which runs immediately
after writing files, in the same run that wrote them), this script re-reads
the generated instruction.md files from disk on a *separate* invocation --
it is the standalone CI-shaped check: run any time, against whatever is
currently on disk, independent of whether gen.py was just run. It re-derives
each arm's language_line from the spec (not from the file) to find the split
point, then diffs the shared prefixes byte-for-byte.

Usage:
    uv run python generator/check_parity.py specs/_toy/toy-ssm-parameter.yaml
    make parity SPEC=specs/_toy/toy-ssm-parameter.yaml

Exit 0 + "PARITY OK" iff every enabled arm's instruction.md shares an
identical prefix (everything before its own per-arm language line). Exit 1
with a unified diff otherwise.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import (  # noqa: E402
    REPO_ROOT,
    build_instruction_md,
    shared_prefix,
    substitute_literals,
    task_dir,
)
from spec_model import Arm, load_spec  # noqa: E402


def check(spec_path: Path) -> int:
    spec = load_spec(spec_path)
    arms: list[Arm] = spec.arms.enabled_arms()

    # --- full-file re-derivation check -----------------------------------
    # This is the load-bearing check: it re-renders each arm's
    # instruction.md from the spec (build_instruction_md -- the exact same
    # function gen.py used to write it) and requires the on-disk file to
    # match BYTE-FOR-BYTE. Comparing only the shared prefix (below) leaves
    # everything from the language line onward -- the language line itself,
    # the trailer, any per-arm output_contract fence -- completely
    # unchecked, which is exactly the gap a hand-inserted, arm-advantaging
    # paragraph after the language line exploited (append an "AWS CDK HINT:
    # use ssm.StringParameter..." paragraph to one arm's instruction.md and
    # the old prefix-only check still reported "PARITY OK"). Since
    # build_instruction_md is a pure function of (spec, arm) with no
    # arm-specific free text ever entering it outside the declared
    # shared_body/per_arm.language_line/output_contract.json_fields fields,
    # "file on disk == re-derived from spec" is a stronger, structural
    # guarantee than "arms agree with each other": it also catches a
    # generated file that drifted from ITS OWN spec (e.g. a stale
    # regeneration), not just cross-arm divergence.
    missing: list[Arm] = []
    mismatched: list[Arm] = []
    on_disk: dict[Arm, str] = {}
    for arm in arms:
        instr_path = task_dir(spec, arm) / "instruction.md"
        if not instr_path.exists():
            missing.append(arm)
            continue
        on_disk[arm] = instr_path.read_text()
        expected = build_instruction_md(spec, arm)
        if on_disk[arm] != expected:
            mismatched.append(arm)
            diff = "\n".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    on_disk[arm].splitlines(keepends=True),
                    fromfile=f"{arm}/instruction.md (re-derived from spec)",
                    tofile=f"{arm}/instruction.md (on disk)",
                )
            )
            print(f"PARITY VIOLATION: {arm!r}'s instruction.md does not match its spec:\n{diff}")

    if missing:
        print(
            f"PARITY CHECK ERROR: instruction.md missing for arm(s) {missing} "
            f"-- run `make gen SPEC={spec_path}` first",
            file=sys.stderr,
        )
        return 1
    if mismatched:
        print(f"\nPARITY FAILED for {spec.id!r}: on-disk instruction.md != spec-derived render "
              f"for arm(s) {mismatched}", file=sys.stderr)
        return 1

    # --- cross-arm shared-prefix check -------------------------------------
    # Secondary/redundant given the full-file check above (since every
    # on_disk[arm] is now known to equal build_instruction_md(spec, arm),
    # and shared_body_resolved is arm-independent by construction), but
    # kept as an explicit, human-readable assertion of prereg §6's actual
    # requirement ("identical natural-language instruction body across
    # arms") and as a second, independent code path against a future
    # refactor of build_instruction_md that could silently break that
    # invariant while still being self-consistent per-arm.
    prefixes: dict[Arm, str] = {}
    for arm in arms:
        per_arm = getattr(spec.instruction.per_arm, arm)
        lang_line = substitute_literals(per_arm.language_line.strip(), spec)
        try:
            prefixes[arm] = shared_prefix(on_disk[arm], lang_line)
        except ValueError as e:
            print(f"PARITY CHECK ERROR [{arm}]: {e}", file=sys.stderr)
            return 1

    baseline_arm = arms[0]
    baseline = prefixes[baseline_arm]
    ok = True
    for arm in arms[1:]:
        if prefixes[arm] != baseline:
            ok = False
            diff = "\n".join(
                difflib.unified_diff(
                    baseline.splitlines(keepends=True),
                    prefixes[arm].splitlines(keepends=True),
                    fromfile=f"{baseline_arm}/instruction.md (shared prefix)",
                    tofile=f"{arm}/instruction.md (shared prefix)",
                )
            )
            print(f"PARITY VIOLATION between {baseline_arm!r} and {arm!r}:\n{diff}")

    if not ok:
        print(f"\nPARITY FAILED for {spec.id!r}", file=sys.stderr)
        return 1

    print(
        f"PARITY OK for {spec.id!r}: instruction.md matches its spec-derived render, "
        f"and the shared prefix is identical, across {len(arms)} arm(s): {arms}"
    )
    for arm in arms:
        rel = (task_dir(spec, arm) / "instruction.md").relative_to(REPO_ROOT)
        print(f"  checked: {rel}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <spec.yaml>", file=sys.stderr)
        return 2
    return check(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
