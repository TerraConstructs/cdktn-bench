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

Multi-step (SCHEMA.md §2.6, 2026-08-20): a spec with `steps:` has no root
instruction.md -- it has one prompt PER STEP, at
`steps/<name>/instruction.md`. Every check below then runs once per step,
over that step's own file. Parity is a WITHIN-step property: arms may carry
different per-step language lines, but everything before the language line
must be byte-identical across arms for the same step, or one arm's agent is
being told something another's is not.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import (  # noqa: E402
    REPO_ROOT,
    build_instruction_md,
    instruction_rel_paths,
    shared_prefix,
    step_language_line,
    substitute_literals,
    task_dir,
)
from spec_model import Arm, load_spec  # noqa: E402


def check_one_prompt(spec, arms, rel: str, step) -> int:
    """Both parity checks for ONE prompt file (`rel`, relative to a task dir).

    `step` is None for the single-step shape and a `Step` for a multi-step
    one; it only selects which language line is expected at the split point.
    """
    # --- full-file re-derivation check -----------------------------------
    # This is the load-bearing check: it re-renders each arm's prompt from
    # the spec (build_instruction_md -- the exact same function gen.py used
    # to write it) and requires the on-disk file to match BYTE-FOR-BYTE.
    # Comparing only the shared prefix (below) leaves everything from the
    # language line onward -- the language line itself, the trailer, any
    # per-arm output_contract fence -- completely unchecked, which is exactly
    # the gap a hand-inserted, arm-advantaging paragraph after the language
    # line exploited (append an "AWS CDK HINT: use ssm.StringParameter..."
    # paragraph to one arm's instruction.md and the old prefix-only check
    # still reported "PARITY OK"). Since build_instruction_md is a pure
    # function of (spec, arm, step) with no arm-specific free text ever
    # entering it outside the declared shared_body/language_line/
    # output_contract.json_fields fields, "file on disk == re-derived from
    # spec" is a stronger, structural guarantee than "arms agree with each
    # other": it also catches a generated file that drifted from ITS OWN spec
    # (e.g. a stale regeneration), not just cross-arm divergence.
    missing: list[Arm] = []
    mismatched: list[Arm] = []
    on_disk: dict[Arm, str] = {}
    for arm in arms:
        instr_path = task_dir(spec, arm) / rel
        if not instr_path.exists():
            missing.append(arm)
            continue
        on_disk[arm] = instr_path.read_text()
        expected = build_instruction_md(spec, arm, step)
        if on_disk[arm] != expected:
            mismatched.append(arm)
            diff = "\n".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    on_disk[arm].splitlines(keepends=True),
                    fromfile=f"{arm}/{rel} (re-derived from spec)",
                    tofile=f"{arm}/{rel} (on disk)",
                )
            )
            print(f"PARITY VIOLATION: {arm!r}'s {rel} does not match its spec:\n{diff}")

    if missing:
        print(
            f"PARITY CHECK ERROR: {rel} missing for arm(s) {missing} "
            f"-- run `make gen SPEC=specs/{spec.id}.yaml` first",
            file=sys.stderr,
        )
        return 1
    if mismatched:
        print(f"\nPARITY FAILED for {spec.id!r}: on-disk {rel} != spec-derived render "
              f"for arm(s) {mismatched}", file=sys.stderr)
        return 1

    # --- cross-arm shared-prefix check -------------------------------------
    # Secondary/redundant given the full-file check above (since every
    # on_disk[arm] is now known to equal build_instruction_md(spec, arm, step),
    # and shared_body_resolved is arm-independent by construction), but
    # kept as an explicit, human-readable assertion of prereg §6's actual
    # requirement ("identical natural-language instruction body across
    # arms") and as a second, independent code path against a future
    # refactor of build_instruction_md that could silently break that
    # invariant while still being self-consistent per-arm.
    prefixes: dict[Arm, str] = {}
    for arm in arms:
        lang_line = substitute_literals(step_language_line(spec, arm, step).strip(), spec)
        try:
            prefixes[arm] = shared_prefix(on_disk[arm], lang_line)
        except ValueError as e:
            print(f"PARITY CHECK ERROR [{arm}/{rel}]: {e}", file=sys.stderr)
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
                    fromfile=f"{baseline_arm}/{rel} (shared prefix)",
                    tofile=f"{arm}/{rel} (shared prefix)",
                )
            )
            print(f"PARITY VIOLATION between {baseline_arm!r} and {arm!r} on {rel}:\n{diff}")

    if not ok:
        print(f"\nPARITY FAILED for {spec.id!r} ({rel})", file=sys.stderr)
        return 1
    return 0


def check(spec_path: Path) -> int:
    spec = load_spec(spec_path)
    arms: list[Arm] = spec.arms.enabled_arms()

    prompts = instruction_rel_paths(spec)
    for rel, step in prompts:
        rc = check_one_prompt(spec, arms, rel, step)
        if rc != 0:
            return rc

    shape = "single-step" if len(prompts) == 1 else f"{len(prompts)}-step"
    print(
        f"PARITY OK for {spec.id!r} ({shape}): every prompt matches its "
        f"spec-derived render, and the shared prefix is identical, across "
        f"{len(arms)} arm(s): {arms}"
    )
    for rel, _step in prompts:
        for arm in arms:
            path = (task_dir(spec, arm) / rel).relative_to(REPO_ROOT)
            print(f"  checked: {path}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <spec.yaml>", file=sys.stderr)
        return 2
    return check(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
