"""Collect the graded artifact of every reference and broken fixture that a
Rego policy grades, for the M10 two-engine comparison
(docs/design/m10-one-rego-engine.md section 2).

Read-only with respect to the repo: it drives
gates/oracle_falsifiability.py::_run_solve under gates/aws_stub.py's
credential-free environment, exactly as `make falsifiability` does, and copies
each run's artifact into an output tree plus a manifest.

Fixture enumeration and the kept working copies come from
gates/artifact_collector.py, which is the one implementation of that; what is
here is the tier-1 half -- reading the `opa eval` queries out of the generated
tests/verify.py and preferring the merged document over the plan.

Usage:
    uv run python scripts/spike/collect_artifacts.py --out <dir> --work-dir <dir>
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import oracle_falsifiability as of  # noqa: E402
from artifact_collector import KeptTempDir, fixtures, install, prune, tests_dir  # noqa: E402
from aws_stub import running_stub  # noqa: E402
from gen import ARM_DIRNAME, task_dir  # noqa: E402
from spec_model import load_spec  # noqa: E402

ARMS = ("hcl_raw", "terraconstructs", "awscdk")

def parse_queries(verify_py: Path) -> list[dict]:
    """The tier-1 evaluations this arm's generated verifier performs, as
    `{query, data_vars}` in evaluation order (deny first, then not_verifiable).

    Read from the emitted configuration rather than reconstructed, so the spike
    runs the queries the verifier really runs, shared library included.
    """
    for node in ast.parse(verify_py.read_text()).body:
        if not (isinstance(node, ast.Assign) and node.targets[0].id == "CONFIG"):
            continue
        tier1 = ast.literal_eval(node.value)["tier1"]
        if tier1["engine"] != "opa" or not tier1["has_asserts"]:
            return []
        data_vars = ["POLICY"] + (["HCL_LIB"] if tier1["hcl"] else [])
        return [
            {"query": tier1[key], "data_vars": data_vars}
            for key in ("query", "not_verifiable_query")
        ]
    return []


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--only", default=None, help="restrict to one spec id")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    keep = install(args.work_dir)

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
                    verify_py, policy = tdir / "verify.py", tdir / "policy.rego"
                    if not verify_py.exists() or not policy.exists():
                        continue
                    queries = parse_queries(verify_py)
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
