#!/usr/bin/env python3
"""Byte gate on the HCL pre-parser's delivery.

The Python that merges an arm's parsed .tf documents into the plan JSON is a
generated file (generator/gen.py::build_hcl_merge_py -> tests/hcl_merge.py)
rather than a heredoc inside every generated tests/static_tiers.sh. That is
only safe while the document it writes to /logs/verifier/oracle-input.json --
the real tier-1 input for a spec with `oracle.hcl_traversal` -- is unchanged,
so this compares that document BYTE-FOR-BYTE against the output of a baseline
copy of the program taken from a git revision, for the spec's reference fixture
and every broken fixture it ships.

The program reads only its two arguments (the plan JSON in, the merged document
out) and the `*.tf`/`*.tf.json` files in its working directory, so a baseline
run needs the fixture's kept working copy and nothing else -- which is why
`--reuse` can grade a tree gates/tier0_parity.py already collected.

Exit 0 = every fixture's document is identical. 1 = a difference, or no fixture
was comparable. docs/gates.md#hcl-merge-bytes has the rest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import artifact_collector as ac  # noqa: E402
from aws_stub import running_stub  # noqa: E402
from gen import task_dir  # noqa: E402
from spec_model import load_spec  # noqa: E402

HEREDOC_TAG = "CDKTN_HCL_MERGE_PY"


def baseline_program(spec_path: Path, rev: str) -> str:
    """The merge program as `rev` shipped it: the body between the heredoc tag
    in that revision's generated static_tiers.sh for the hcl_raw arm."""
    spec = load_spec(spec_path)
    rel = (task_dir(spec, "hcl_raw") / "tests" / "static_tiers.sh").relative_to(REPO_ROOT)
    text = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    body: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        if inside and line.rstrip("\n") == HEREDOC_TAG:
            return "".join(body)
        if inside:
            body.append(line)
        elif f"<<'{HEREDOC_TAG}'" in line:
            inside = True
    raise SystemExit(f"{rev}:{rel} carries no {HEREDOC_TAG} heredoc to compare against")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_input(plan: Path) -> Path:
    """The document the generated merge actually read: the verifier writes
    `plan.normalised.json` beside `plan.json` (module resources hoisted; a
    module-free plan is byte-identical) and merges that, so the baseline must
    read the same bytes or a module-shaped fixture differs for that reason
    alone. gates/plan_normaliser_parity.py owns raw-vs-normalised."""
    normalised = plan.with_name(plan.stem + ".normalised.json")
    return normalised if normalised.is_file() else plan


def compare(program: Path, workdir: Path, plan: Path, merged: Path) -> tuple[str, str]:
    """(sha256 of the generated file's document, sha256 of the baseline's)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "oracle-input.json"
        proc = subprocess.run(
            ["python3", str(program), str(merge_input(plan)), str(out)],
            cwd=workdir, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0 or not out.is_file():
            raise RuntimeError(f"the baseline program failed: {proc.stdout}{proc.stderr}")
        return sha256(merged), sha256(out)


def reuse_rows(tree: Path):
    """Every kept working copy in a gates/tier0_parity.py `--out` tree that
    has a merged document, labelled from the manifest by its artifact bytes --
    the manifest names each fixture's artifact, not its working copy."""
    by_artifact = {
        sha256(tree / row["artifact"]): row["label"]
        for row in json.loads((tree / "manifest.json").read_text())
    }
    for merged in sorted(tree.glob("work/*/logs/verifier/oracle-input.json")):
        work = merged.parent.parent.parent
        plan = work / "project" / "plan.json"
        if not plan.is_file():
            continue
        yield by_artifact.get(sha256(plan), work.name), work / "project", plan, merged


def collect_rows(spec_path: Path, work: Path):
    spec = load_spec(spec_path)
    keep = ac.install(work)
    with running_stub() as env:
        env["TF_IN_AUTOMATION"] = "1"
        env.pop("NODE_OPTIONS", None)
        for c in ac.collect(spec, env, keep, arms=("hcl_raw",),
                            require_tests=("hcl_merge.py",)):
            if c.merged is None or c.plan is None:
                print(f"  [SKIP] {c.label}: no merged document", flush=True)
                continue
            yield c.label, c.workdir / "project", c.plan, c.merged


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", nargs="?", type=Path)
    # Only a revision PREDATING the lift carries the heredoc: the parent of
    # the commit that moved it into tests/hcl_merge.py is the last one that
    # does, so HEAD can never be the baseline.
    ap.add_argument("--baseline-rev", default="ee93231~1",
                    help="revision whose static_tiers.sh heredoc is the baseline "
                         "(default: the parent of the lift commit)")
    ap.add_argument("--reuse", type=Path,
                    help="grade a tree gates/tier0_parity.py --out wrote")
    ap.add_argument("--work-dir", type=Path, help="keep each fixture's working copy here")
    args = ap.parse_args(argv)
    if not args.spec and not args.reuse:
        ap.error("pass a spec path or --reuse DIR")

    spec_path = args.spec or next(
        p for p in sorted(REPO_ROOT.glob("specs/*.yaml"))
        if load_spec(p).oracle.hcl_traversal
    )
    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "baseline_hcl_merge.py"
        program.write_text(baseline_program(spec_path, args.baseline_rev))
        rows = (
            reuse_rows(args.reuse) if args.reuse
            else collect_rows(spec_path, args.work_dir or Path("/tmp/hcl-merge-bytes-work"))
        )
        compared = differing = 0
        for label, workdir, plan, merged in rows:
            try:
                mine, base = compare(program, workdir, plan, merged)
            except (RuntimeError, OSError) as exc:
                print(f"[FAIL] {label}: {exc}", flush=True)
                differing += 1
                continue
            compared += 1
            same = mine == base
            differing += not same
            print(f"[{'IDENTICAL' if same else 'DIFFERS'}] {mine} {label}", flush=True)

    print("")
    print(f"hcl-merge-bytes: compared {compared} fixture(s) against "
          f"{args.baseline_rev}, {differing} differing")
    if differing or not compared:
        print("hcl-merge-bytes: FAILED", file=sys.stderr)
        return 1
    print("hcl-merge-bytes: OK -- the lifted pre-parser writes the same bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
