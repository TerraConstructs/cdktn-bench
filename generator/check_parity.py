#!/usr/bin/env python3
"""Independent re-verification of prompt parity across a scenario's arms.

Parity rule (preregistration §6, SCHEMA.md §8.2 point 2): every enabled arm's
prompt must be byte-identical up to its own per-arm language line, or one arm's
agent is being told something another's is not.

Unlike gen.py's in-process ``self_check_parity``, this re-reads the generated
instruction.md files from disk on a separate invocation, so it can run any time
against whatever is on disk. It re-derives each arm's language_line from the
spec to find the split point.

Multi-step (SCHEMA.md §2.6): a spec with ``steps:`` has no root instruction.md;
it has one prompt per step at ``steps/<name>/instruction.md``, and every check
runs once per step. Parity is a WITHIN-step property — arms may carry different
per-step language lines.

Usage: ``make parity SPEC=specs/foo.yaml``. Exit 0 + "PARITY OK", or exit 1
with a unified diff.
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
    # The load-bearing check: requiring the whole file to equal
    # build_instruction_md(spec, arm, step) also covers everything FROM the
    # language line onward, where an arm-advantaging paragraph would hide and
    # the shared-prefix check below cannot see.
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
    # Redundant given the full-file check, and kept as an independent code
    # path: a build_instruction_md refactor can stay self-consistent per-arm
    # while breaking preregistration §6's actual requirement, an identical
    # natural-language instruction body across arms.
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
