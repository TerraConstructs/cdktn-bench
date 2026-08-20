#!/usr/bin/env python3
"""Deterministic per-trial signal extraction from cdktn-bench job dirs.

Metrics (all mechanical, no judgement):
  reward, out_tokens, cost          -- from result.json
  assistant_msgs                    -- LLM turns actually taken
  rbw_tokens / rbw_msgs / rbw_pct   -- READ-BEFORE-WRITE: output tokens (and msgs)
                                       emitted before the first mutation of the
                                       arm's entry file. Comprehension cost proxy.
  tool_calls                        -- total tool_use blocks
  escape_hatch                      -- did the solution ever leave the L2?
                                       (awscdk: Cfn*/addPropertyOverride/addOverride/
                                        defaultChild; tcons: provider-level raw
                                        resources; hcl-raw: n/a by construction)
"""
import json, glob, os, re, sys
from collections import Counter

ENTRY = {  # arm -> substrings identifying the agent-owned entry file
    "awscdk": ("lib/scenario-stack.ts",),
    "terraconstructs": ("lib/scenario-stack.ts", "main.ts"),
    "hcl-raw": ("main.tf",),
}
ESCAPE = {
    "awscdk": re.compile(r"\bCfn[A-Z]\w+|addPropertyOverride|addOverride|defaultChild|escapeHatch", re.I),
    "terraconstructs": re.compile(r"from\s+['\"][^'\"]*provider/aws|new\s+(?:DataAws|Aws)\w+\s*\(|addOverride", re.I),
    "hcl-raw": None,
}
MUTATORS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def arm_of(name):
    for a in ("terraconstructs", "hcl-raw", "awscdk"):
        if a in name or (a == "terraconstructs" and "terracon" in name):
            return a
    return "?"


def sessions_for(d):
    """Session jsonl(s) for a trial dir; multi-step trials have one per step."""
    out = []
    for p in sorted(glob.glob(os.path.join(d, "**", "sessions", "projects", "*", "*.jsonl"), recursive=True)):
        step = "-"
        m = re.search(r"/steps/([^/]+)/", p)
        if m:
            step = m.group(1)
        out.append((step, p))
    return out


def scan_session(path, arm):
    rows = []
    for line in open(path):
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    out_tok = msgs = calls = 0
    rbw_tok = rbw_msgs = None
    wrote = []
    seen = set()   # a message id repeats across its content blocks; usage is per-message
    for r in rows:
        if r.get("type") != "assistant":
            continue
        m = r.get("message", {})
        mid = m.get("id")
        if mid not in seen:
            seen.add(mid)
            u = m.get("usage", {}) or {}
            out_tok += u.get("output_tokens") or 0
            msgs += 1
        for c in m.get("content", []) or []:
            if c.get("type") != "tool_use":
                continue
            calls += 1
            name = c.get("name")
            inp = c.get("input", {}) or {}
            fp = str(inp.get("file_path", ""))
            body = str(inp.get("content", "")) + str(inp.get("new_string", ""))
            is_entry = any(e in fp for e in ENTRY.get(arm, ()))
            if name in MUTATORS and is_entry:
                if rbw_tok is None:          # first mutation of the owned file
                    rbw_tok, rbw_msgs = out_tok, msgs
                wrote.append(body)
            # bash heredoc/redirect into the entry file also counts as a mutation
            elif name == "Bash":
                cmd = str(inp.get("command", ""))
                if any(e in cmd for e in ENTRY.get(arm, ())) and re.search(r">|tee|cat\s*<<", cmd):
                    if rbw_tok is None:
                        rbw_tok, rbw_msgs = out_tok, msgs
                    wrote.append(cmd)
    pat = ESCAPE.get(arm)
    esc = "n/a" if pat is None else ("YES" if pat.search("\n".join(wrote)) else "no")
    return dict(out_tok=out_tok, msgs=msgs, calls=calls, rbw_tok=rbw_tok,
                rbw_msgs=rbw_msgs, escape=esc)


def main(job_dirs):
    print(f"{'trial':44s} {'step':18s} {'rw':>4s} {'out_tok':>8s} {'msgs':>5s} "
          f"{'calls':>6s} {'rbw_tok':>8s} {'rbw%':>5s} {'esc':>4s} {'cost':>7s}")
    print("-" * 120)
    agg = []
    for jd in job_dirs:
        for d in sorted(glob.glob(os.path.join(jd, "*"))):
            rj = os.path.join(d, "result.json")
            if not os.path.isdir(d) or not os.path.exists(rj):
                continue
            name = os.path.basename(d)
            if name.endswith("scenario-reset"):
                continue
            arm = arm_of(name)
            res = json.load(open(rj))
            reward = (res.get("verifier_result") or {}).get("rewards", {}).get("reward")
            exc = (res.get("exception_info") or {}).get("exception_type")
            if exc:
                print(f"{name[:44]:44s} {'-':18s} {'INFRA-FAIL: ' + exc[:40]}")
                continue
            steps_meta = {st.get("step_name"): st for st in (res.get("step_results") or [])}
            for step, sp in sessions_for(d):
                s = scan_session(sp, arm)
                meta = steps_meta.get(step) or {}
                s["cost"] = ((meta.get("agent_result") or {}).get("cost_usd")
                             if meta else (res.get("agent_result") or {}).get("cost_usd")) or 0.0
                if meta:
                    reward = (meta.get("verifier_result") or {}).get("rewards", {}).get("reward")
                pct = (100.0 * s["rbw_tok"] / s["out_tok"]) if s["rbw_tok"] and s["out_tok"] else None
                print(f"{name[:44]:44s} {step[:18]:18s} {str(reward):>4s} {s['out_tok']:8d} "
                      f"{s['msgs']:5d} {s['calls']:6d} {str(s['rbw_tok'] if s['rbw_tok'] is not None else '-'):>8s} "
                      f"{(f'{pct:.0f}%' if pct else '-'):>5s} {s['escape']:>4s} {s['cost']:7.2f}")
                agg.append(dict(trial=name, arm=arm, step=step, reward=reward, **s, rbw_pct=pct))
    if agg:
        print()
        print(f"{'PER-ARM ROLLUP (valid rows only)':44s} {'n':>3s} {'out_tok':>8s} "
              f"{'rbw%':>6s} {'green':>6s} {'esc':>4s}")
        print("-" * 80)
        for arm in ("awscdk", "terraconstructs", "hcl-raw"):
            rows = [r for r in agg if r["arm"] == arm and r["reward"] is not None]
            if not rows:
                continue
            pcts = [r["rbw_pct"] for r in rows if r["rbw_pct"] is not None]
            green = sum(1 for r in rows if r["reward"] == 1.0)
            esc = sum(1 for r in rows if r["escape"] == "YES")
            print(f"{arm:44s} {len(rows):3d} {sum(r['out_tok'] for r in rows) / len(rows):8.0f} "
                  f"{(sum(pcts) / len(pcts) if pcts else 0):5.0f}% {green:3d}/{len(rows):<2d} {esc:4d}")
    out = os.environ.get("SIGNALS_OUT", "signals.json")
    json.dump(agg, open(out, "w"), indent=1)
    print(f"\n[rows written to {out}]")
    return agg


if __name__ == "__main__":
    main(sys.argv[1:])
