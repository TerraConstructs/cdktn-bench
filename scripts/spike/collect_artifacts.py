"""Collect the graded artifact of every reference and broken fixture that a
Rego policy grades, for the M10 two-engine comparison
(docs/design/m10-one-rego-engine.md section 2).

Read-only with respect to the repo: it drives
gates/oracle_falsifiability.py::_run_solve under gates/aws_stub.py's
credential-free environment, exactly as `make falsifiability` does, and copies
each run's artifact into an output tree plus a manifest.

The one behaviour change over the gate is that each run's working copy is kept
(under --work-dir) instead of being deleted, because an `oracle.hcl_traversal`
scenario's real tier-1 input is the merged document static_tiers.sh writes into
the run's logs dir, not the plan.json under the project dir.

Usage:
    uv run python scripts/spike/collect_artifacts.py --out <dir> --work-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import types
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import oracle_falsifiability as of  # noqa: E402
from aws_stub import running_stub  # noqa: E402
from gen import ARM_DIRNAME, task_dir  # noqa: E402
from spec_model import load_spec  # noqa: E402

ARMS = ("hcl_raw", "terraconstructs", "awscdk")

# `opa eval -f raw -I -d <policy> [-d <lib>] "data.cdktn_bench.<pkg>.<rule>"`
# as generator/gen.py emits it. Parsed rather than reconstructed so the spike
# runs the queries the verifier really runs, library files included.
_OPA_EVAL_RE = re.compile(
    r"opa eval -f raw -I((?: -d \"\$[A-Z_]+\")+) \"(data\.cdktn_bench\.[a-z0-9_]+\.\w+)\""
)


class KeptTempDir:
    """`tempfile.TemporaryDirectory` shape that does not delete on exit."""

    def __init__(self, root: Path):
        self._root = root
        self._n = 0
        self.last: Path | None = None

    def __call__(self, prefix: str = "", dir: str | None = None):  # noqa: A002
        self._n += 1
        path = self._root / f"{prefix}{self._n:04d}"
        path.mkdir(parents=True, exist_ok=True)
        self.last = path
        return _Kept(path)


class _Kept:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, *exc) -> bool:
        return False


def parse_queries(static_tiers: Path) -> list[dict]:
    """The tier-1 evaluations this arm's generated verifier performs, as
    `{query, data_vars}` in emission order (deny first, then not_verifiable)."""
    text = static_tiers.read_text()
    out = []
    for m in _OPA_EVAL_RE.finditer(text):
        data_vars = re.findall(r"\$([A-Z_]+)", m.group(1))
        out.append({"query": m.group(2), "data_vars": data_vars})
    return out


def tests_dir(task: Path, step) -> Path:
    """A multi-step task's oracle lives under its step, never at the task root
    (the shared root `tests/` must stay oracle-free)."""
    return task / "steps" / step.name / "tests" if step is not None else task / "tests"


def fixtures(task: Path) -> list[tuple[str, Path]]:
    out = [("reference", task / "solution" / "solve.sh")]
    broken = task / "solution" / "broken"
    if broken.is_dir():
        for d in sorted(broken.iterdir()):
            if (d / "solve.sh").exists():
                out.append((f"broken/{d.name}", d / "solve.sh"))
    return [(name, p) for name, p in out if p.exists()]


# Kept working copies are for reproducing a divergence by hand; the installed
# dependency trees are ~600 MB per run and reproducible from the lockfiles.
PRUNE = ("node_modules", ".terraform", ".git")


def prune(work: Path | None) -> None:
    if work is None:
        return
    for sub in work.rglob("*"):
        if sub.is_dir() and sub.name in PRUNE:
            shutil.rmtree(sub, ignore_errors=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--only", default=None, help="restrict to one spec id")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    keep = KeptTempDir(args.work_dir)
    # Only this module's view of `tempfile` is swapped; the real module keeps
    # its deleting behaviour for every other caller in the process.
    of.tempfile = types.SimpleNamespace(TemporaryDirectory=keep)

    spec_paths = sorted(REPO_ROOT.glob("specs/*.yaml")) + sorted(REPO_ROOT.glob("specs/_toy/*.yaml"))
    manifest: list[dict] = []
    tf_cache = args.work_dir / "tf-plugin-cache"
    tf_cache.mkdir(exist_ok=True)
    with running_stub() as env:
        # Host-side only, and purely a speed knob: the arm images resolve
        # providers from their own offline mirror, never from this cache.
        env["TF_PLUGIN_CACHE_DIR"] = str(tf_cache)
        env["TF_IN_AUTOMATION"] = "1"
        env.pop("NODE_OPTIONS", None)
        for spec_path in spec_paths:
            try:
                spec = load_spec(spec_path)
            except Exception:
                continue
            if args.only and spec.id != args.only:
                continue
            for arm in ARMS:
                try:
                    task = task_dir(spec, arm)
                except Exception:
                    continue
                if not task.is_dir():
                    continue
                artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path
                steps = spec.steps or []
                final_step = steps[-1] if spec.is_multi_step() else None
                # Task-root fixtures are graded by the FINAL step's oracle; each
                # non-final step contributes its own reference under its own.
                plan = [(final_step, name, solve) for name, solve in fixtures(task)]
                for st in steps[:-1]:
                    solve = task / "steps" / st.name / "solution" / "solve.sh"
                    if solve.exists():
                        plan.append((st, f"steps/{st.name}/reference", solve))
                for step, name, solve in plan:
                    tdir = tests_dir(task, step)
                    static_tiers, policy = tdir / "static_tiers.sh", tdir / "policy.rego"
                    if not static_tiers.exists() or not policy.exists():
                        continue
                    queries = parse_queries(static_tiers)
                    if not queries:
                        continue  # cfn-guard arm, or no tier-1 asserts
                    label = f"{spec.id}/{ARM_DIRNAME[arm]}/{name}"
                    t0 = time.time()
                    run = of._run_solve(
                        task, arm, solve, label,
                        artifact_rel=artifact_rel, step=step, env=env,
                    )
                    work = keep.last
                    merged = work / "logs" / "verifier" / "oracle-input.json"
                    plain = work / "project" / artifact_rel
                    src = merged if merged.exists() else plain
                    slug = label.replace("/", "__")
                    dest = args.out / f"{slug}.json"
                    if src.exists() and src.stat().st_size > 0:
                        shutil.copyfile(src, dest)
                        art = dest.name
                    else:
                        art = None
                    manifest.append({
                        "label": label, "spec": spec.id, "arm": arm, "fixture": name,
                        "artifact": art, "merged_input": src is merged and src.exists(),
                        "reward": run.reward, "queries": queries,
                        "policy": str(policy.relative_to(REPO_ROOT)),
                        "hcl_lib": str((tdir / "hcl_traversal.rego").relative_to(REPO_ROOT))
                                   if (tdir / "hcl_traversal.rego").exists() else None,
                        "seconds": round(time.time() - t0, 1),
                        "workdir": str(work),
                    })
                    prune(work)
                    print(f"{label}: reward={run.reward} artifact={art} "
                          f"{manifest[-1]['seconds']}s", flush=True)
                    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
