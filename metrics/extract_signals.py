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
                                       (awscdk: L1 Cfn* resources, addOverride,
                                        defaultChild; tcons: provider-level raw
                                        resources; hcl-modules: a resource block
                                        beside the module calls; hcl-raw: n/a by
                                        construction)

`trial_signals(trial_dir, arm)` is the importable entry point: gates/emit_result.py
calls it so rbw and escape-hatch reach the published row at gate time. The CLI
below is the exploratory table, and resolves the arm from the trial dir NAME,
which harbor truncates -- pass the arm explicitly for anything reportable.
"""
import json, glob, os, re, sys
from collections import Counter

ENTRY = {  # arm -> substrings identifying the agent-owned entry file
    "awscdk": ("lib/scenario-stack.ts",),
    "terraconstructs": ("lib/scenario-stack.ts", "main.ts"),
    "hcl-raw": ("main.tf",),
    "hcl-modules": ("main.tf",),
}
# `Cfn*` names that are NOT an escape from an L2: template plumbing with no L2
# equivalent to leave. Excluded because the field is published -- a bare
# `\bCfn[A-Z]\w+` lit up on `new cdk.CfnOutput(...)` and produced the only
# "escape hatch required" reading the benchmark ever had.
L1_NOT_AN_ESCAPE = (
    "CfnOutput", "CfnParameter", "CfnCondition", "CfnMapping",
    "CfnRule", "CfnTag", "CfnDynamicReference", "CfnJson",
)
ESCAPE = {
    "awscdk": re.compile(
        r"\bCfn(?!%s)[A-Z]\w+|addPropertyOverride|addOverride|defaultChild|escapeHatch"
        % "|".join(n[len("Cfn"):] + r"\b" for n in L1_NOT_AN_ESCAPE),
        re.I,
    ),
    "terraconstructs": re.compile(r"from\s+['\"][^'\"]*provider/aws|new\s+(?:DataAws|Aws)\w+\s*\(|addOverride", re.I),
    # The hcl_modules escape is authoring a provider resource beside the module
    # calls; `n/a` for hcl-raw, which is provider resources by construction and
    # so has no abstraction to leave.
    "hcl-modules": re.compile(r"^\s*resource\s+\"aws_", re.M),
    "hcl-raw": None,
}
MUTATORS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Post-trial reset artifacts sit beside the agent trials and are not trials:
# cdktn_bench.trial names them `scenario-reset` and, per retry,
# `scenario-reset-retry-N` (RESET_TRIAL_NAME_PREFIX there). Match the prefix,
# not the bare name -- walking one prints a row with no arm and reports the
# reset's own exception as an INFRA-FAIL against a task that never failed.
RESET_DIR_PREFIX = "scenario-reset"


ARMS = ("terraconstructs", "hcl-modules", "hcl-raw", "awscdk")


def arm_of(name):
    """Arm for a trial dir name, tolerating a TRUNCATED arm suffix.

    Harbor caps the task-name portion of a trial dir, so a long scenario
    name eats the arm: `named-resource-replacement` yields
    `...-awscd__H8AcBrb`, `...-hcl-r__FXNwjAy`, `...-terra__x2vFoyx`.
    The old substring test needed the WHOLE arm name, so all three
    returned "?" and every row silently dropped out of the per-arm
    rollup -- an empty rollup that looks exactly like "no trials ran".
    Same failure class as the verifier-region bug: wrong output, no error.

    Matched against the stem (before `__`) and anchored at the END, so a
    scenario whose own name contains an arm word cannot steal the match.
    """
    stem = name.split("__", 1)[0]
    for a in ARMS:
        if stem.endswith(a):
            return a
    # Truncated: accept the longest arm PREFIX the stem ends with. The
    # three arms start with distinct letters, so this cannot be
    # ambiguous; the 3-char floor is what stops it matching noise.
    best = None
    for a in ARMS:
        for n in range(len(a) - 1, 2, -1):
            if stem.endswith("-" + a[:n]) and (best is None or n > best[1]):
                best = (a, n)
    return best[0] if best else "?"


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


ESCAPE_YES, ESCAPE_NO, ESCAPE_NA = "yes", "no", "n/a"


def _pct(rbw_tok, out_tok):
    return round(100.0 * rbw_tok / out_tok, 2) if rbw_tok and out_tok else None


def trial_signals(trial_dir, arm):
    """`{"rbw": {...}, "escape_hatch": ...}` for one trial dir, or None when the
    trial left no session transcript to read.

    The importable half of this module: gates/emit_result.py calls it so rbw and
    escape-hatch are emitted as first-class row fields at gate time, rather than
    re-derived from the job dir afterwards by the CLI below.

    **Multi-step.** rbw is a SHARE, so summing it across steps is meaningless --
    each step is its own read-then-write episode. The trial-level numbers are the
    FINAL step's (the step the row's reward is attributed to, Amendment 26's
    `final` strategy) and every step's own numbers are carried under `steps`.
    escape_hatch is the opposite: an ever-used flag over every step's writes.
    """
    per_step = [(step, scan_session(path, arm)) for step, path in sessions_for(trial_dir)]
    if not per_step:
        return None
    escapes = {s["escape"] for _, s in per_step}
    if escapes == {ESCAPE_NA}:
        escape = ESCAPE_NA
    else:
        escape = ESCAPE_YES if "YES" in escapes else ESCAPE_NO
    _, last = per_step[-1]
    rbw = {
        "tokens": last["rbw_tok"],
        "msgs": last["rbw_msgs"],
        "output_tokens": last["out_tok"],
        "pct": _pct(last["rbw_tok"], last["out_tok"]),
    }
    if len(per_step) > 1 or per_step[0][0] != "-":
        rbw["steps"] = {
            step: {
                "tokens": s["rbw_tok"],
                "msgs": s["rbw_msgs"],
                "output_tokens": s["out_tok"],
                "pct": _pct(s["rbw_tok"], s["out_tok"]),
            }
            for step, s in per_step
        }
    return {"rbw": rbw, "escape_hatch": escape}


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
            if name.startswith(RESET_DIR_PREFIX) or name.endswith(RESET_DIR_PREFIX):
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
                pct = _pct(s["rbw_tok"], s["out_tok"])
                print(f"{name[:44]:44s} {step[:18]:18s} {str(reward):>4s} {s['out_tok']:8d} "
                      f"{s['msgs']:5d} {s['calls']:6d} {str(s['rbw_tok'] if s['rbw_tok'] is not None else '-'):>8s} "
                      f"{(f'{pct:.0f}%' if pct else '-'):>5s} {s['escape']:>4s} {s['cost']:7.2f}")
                agg.append(dict(trial=name, arm=arm, step=step, reward=reward, **s, rbw_pct=pct))
    if agg:
        print()
        print(f"{'PER-ARM ROLLUP (valid rows only)':44s} {'n':>3s} {'out_tok':>8s} "
              f"{'rbw%':>6s} {'green':>6s} {'esc':>4s}")
        print("-" * 80)
        # An unresolved arm must be LOUD. Silently skipping these rows is
        # how the truncation bug above stayed invisible: the rollup simply
        # printed nothing and read as "no trials ran".
        unknown = [r for r in agg if r["arm"] == "?"]
        if unknown:
            print(f"{'!! UNRESOLVED ARM -- NOT IN ANY ROLLUP ROW BELOW':44s} {len(unknown):3d}")
            for r in unknown:
                print(f"   {r['trial']}")
        for arm in ARMS:
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
