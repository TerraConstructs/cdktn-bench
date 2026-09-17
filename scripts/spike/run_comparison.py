"""Drive the two-engine comparison for M10
(docs/design/m10-one-rego-engine.md section 2).

Reads the manifest scripts/spike/collect_artifacts.py wrote, expands it into
one row per (policy, artifact, query) pair, and runs them all inside a single
container of the spike image so opa 1.19.0 and regorus 0.12.0 see identical
bytes. Writes results.jsonl and a summary.

Usage:
    uv run python scripts/spike/run_comparison.py \
        --artifacts <dir> --out <dir> [--image cdktn-bench-spike/rego-engines:0.12.0]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def rows(manifest: list[dict]) -> list[tuple[str, str, str, str, str]]:
    out = []
    for e in manifest:
        if not e["artifact"]:
            continue
        for q in e["queries"]:
            policy = f"/repo/{e['policy']}"
            lib = f"/repo/{e['hcl_lib']}" if "HCL_LIB" in q["data_vars"] and e["hcl_lib"] else "-"
            rule = q["query"].rsplit(".", 1)[1]
            out.append((f"{e['label']}::{rule}", policy, lib, q["query"], f"/artifacts/{e['artifact']}"))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--image", default="cdktn-bench-spike/rego-engines:0.12.0")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.artifacts / "manifest.json").read_text())
    tsv = "\n".join("\t".join(r) for r in rows(manifest)) + "\n"
    (args.out / "pairs.tsv").write_text(tsv)

    # The artifacts live under the session scratch dir, which colima does not
    # share into the VM; `docker cp` goes through the CLI and does. The repo
    # itself is under $HOME and mounts normally.
    cid = subprocess.run(
        ["docker", "run", "-d", "--platform", "linux/arm64",
         "-v", f"{REPO_ROOT}:/repo:ro", args.image, "sleep", "infinity"],
        capture_output=True, text=True, check=True).stdout.strip()
    try:
        subprocess.run(["docker", "exec", cid, "mkdir", "-p", "/artifacts"], check=True)
        subprocess.run(["docker", "cp", f"{args.artifacts.resolve()}/.", f"{cid}:/artifacts"], check=True)
        proc = subprocess.run(
            ["docker", "exec", "-i", cid, "bash", "/repo/scripts/spike/compare_engines.sh"],
            input=tsv, capture_output=True, text=True,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)
    (args.out / "results.jsonl").write_text(proc.stdout)
    (args.out / "compare.stderr").write_text(proc.stderr)

    results = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    diverge = [r for r in results if not r["agree"] or r["opa"]["rc"] != r["regorus"]["rc"]]
    summary = {
        "pairs": len(results),
        "value_divergences": sum(1 for r in results if not r["agree"]),
        "exit_code_divergences": sum(1 for r in results if r["opa"]["rc"] != r["regorus"]["rc"]),
        "value_divergences_non_strict": sum(1 for r in results if not r["agree_non_strict"]),
        "exit_code_divergences_non_strict": sum(
            1 for r in results if r["opa"]["rc"] != r["regorus_non_strict"]["rc"]),
        "opa_ms_total": sum(r["opa"]["ms"] for r in results),
        "regorus_ms_total": sum(r["regorus"]["ms"] for r in results),
        "opa_ms_median": statistics.median([r["opa"]["ms"] for r in results]) if results else None,
        "regorus_ms_median": statistics.median([r["regorus"]["ms"] for r in results]) if results else None,
        "diverging_ids": [r["id"] for r in diverge],
        "diverging_ids_non_strict": [
            r["id"] for r in results
            if not r["agree_non_strict"] or r["opa"]["rc"] != r["regorus_non_strict"]["rc"]],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
