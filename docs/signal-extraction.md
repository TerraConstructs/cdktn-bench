# Extracting signals from a job dir — deterministic recipes

Every number in `ROADMAP.md` §3 came from these commands. They are **post-hoc
and judgement-free**: they read artifacts a completed trial already wrote, so
they cost nothing to re-run and never require a new trial.

---

## 0. Where the data lives

```
jobs/<model>/<YYYY-MM-DD__HH-MM-SS>/          # one job
├── result.json                                # job-level rollup
└── <task>__<id>/                              # one trial
    ├── result.json                            # reward, tokens, cost, exception_info
    ├── trial.log
    ├── agent/
    │   ├── trajectory.json                    # ATIF summary: step_id, source, message
    │   ├── agent-output.txt                   # the agent's final answer
    │   └── sessions/projects/*/<uuid>.jsonl   # FULL transcript: tool inputs + per-message usage
    ├── verifier/
    │   ├── test-stdout.txt                    # per-assert PASS/FAIL lines
    │   ├── reward.txt
    │   └── live_check-result.json             # live scenarios only
    └── steps/<NN-name>/{agent,verifier}/      # multi-step: the above, per step
```

**The session `jsonl` is the high-resolution source** — `trajectory.json` is a
summary and does not carry tool inputs. Anything about *what the agent actually
did* comes from the jsonl.

---

## 1. The one tool: `metrics/extract_signals.py`

```bash
# one job, or several (multi-step trials emit one row per step)
python3 metrics/extract_signals.py jobs/claude-sonnet-5/2026-08-20__17-16-22

# machine-readable rows alongside the table
SIGNALS_OUT=/tmp/signals.json python3 metrics/extract_signals.py jobs/*/2026-*
```

Emits per trial (and per step): `reward`, `out_tok`, `msgs`, `calls`,
`rbw_tok`, `rbw%`, `escape`, `cost` — then a per-arm rollup. Infra failures are
printed as `INFRA-FAIL: <ExceptionType>` and **excluded from the rollup**: they
are invalid rows, not zeros.

**read-before-write (`rbw`)** — output tokens emitted before the first mutation
of the arm's own entry file (`lib/scenario-stack.ts` / `main.ts` / `main.tf`),
counting `Write`/`Edit`/`MultiEdit` and `Bash` redirects into that file. The
share (`rbw%`) is the comparable figure; the absolute scales with trial size.

**escape-hatch** — did the solution ever leave the L2: `Cfn*`,
`addPropertyOverride`, `addOverride`, `defaultChild` (awscdk); provider-level
raw resources (terraconstructs); `n/a` for hcl-raw, which has no abstraction to
escape. It is an *ever-used* flag scanned across all writes to the entry file,
not a final-state check.

### The token-accounting gotcha — read this before trusting any hand-rolled sum

A session `jsonl` repeats a message's `usage` block **on every content block of
that message**. Summing `output_tokens` naively double-counts (2.0× on
`sfn-jsonata-awscdk`: 27,998 vs the true 15,533). **Deduplicate by
`message.id`.** The correctness check is that your sum equals
`result.json`'s `n_output_tokens` exactly:

```bash
python3 -c "
import json,glob
f=glob.glob('jobs/*/*/<trial>/agent/sessions/projects/*/*.jsonl')[0]
rows=[json.loads(l) for l in open(f)]
seen={}
for r in rows:
    if r.get('type')=='assistant':
        seen[r['message'].get('id')] = r['message'].get('usage',{}).get('output_tokens') or 0
print('deduped:', sum(seen.values()))"
```

---

## 2. Quick recipes

### Reward / cost table for a job (works for single- and multi-step)

```bash
for d in jobs/claude-sonnet-5/<job>/*/result.json; do python3 -c "
import json,sys
p='$d'; d=json.load(open(p))
r=(d.get('verifier_result') or {}).get('rewards',{}).get('reward')
e=(d.get('exception_info') or {}).get('exception_type')
sr=d.get('step_results') or []
out=sum((s.get('agent_result') or {}).get('n_output_tokens') or 0 for s in sr) if sr \
    else (d.get('agent_result') or {}).get('n_output_tokens')
print(f\"{p.split('/')[-2]:46s} reward={r} out={out} {e or ''}\")"; done
```

### Per-step accounting for one multi-step trial

```bash
python3 -c "
import json
d=json.load(open('jobs/<...>/<trial>/result.json'))
for s in d['step_results']:
    ar=s['agent_result']; vr=(s.get('verifier_result') or {}).get('rewards',{})
    print(f\"{s['step_name']}: reward={vr.get('reward')} out={ar['n_output_tokens']} \"
          f\"in={ar['n_input_tokens']} cache={ar['n_cache_tokens']} cost=\${ar['cost_usd']:.2f}\")"
```

`step_results[].verifier_result.rewards.reward` is the per-step reward;
the trial-level reward reflects the configured strategy (`final` for
cdktn-bench, per Amdt 26).

### Which assert failed

```bash
grep -E '^\s*(PASS|FAIL)' jobs/<...>/<trial>/verifier/test-stdout.txt
# multi-step:
grep -E '^\s*(PASS|FAIL)' jobs/<...>/<trial>/steps/*/verifier/test-stdout.txt
```

### Triage a non-green trial: agent failure or infra failure?

```bash
python3 -c "
import json
d=json.load(open('jobs/<...>/<trial>/result.json'))
e=d.get('exception_info') or {}
print('TYPE:', e.get('exception_type')); print('MSG:', str(e.get('exception_message'))[:300])"
```

`AgentSetupTimeoutError`, container/build errors and framework resets are
**infra failures — invalid rows, never zeros.** Only a completed agent phase
that fails the oracle is a real 0.0. (In the 2026-08-20 battery, four trials
hit `AgentSetupTimeoutError` after scenario-authoring agents were run
concurrently with a 4-way battery — do not run heavy background work during a
measurement battery.)

### What did the agent spend its turns on?

```bash
python3 -c "
import json
d=json.load(open('jobs/<...>/<trial>/agent/trajectory.json'))
for s in d['steps'][:40]:
    print(f\"{s['step_id']:3d} {str(s.get('source'))[:9]:9s} \"
          f\"{str(s.get('message') or '')[:100].replace(chr(10),' ')}\")"
```

Reading `.d.ts` / provider-doc spelunking before the first `Write` is the
read-before-write phase made visible — this is how the `sfn-jsonata` finding
(ROADMAP §3.2) was first spotted, before it was mechanized.

### Was a spec's identity leaked into agent-visible surfaces?

```bash
grep -rn '<spec-id>' tasks/anchor/<spec-id>-*/environment/ tasks/anchor/<spec-id>-*/instruction.md
```

Expect **zero hits** — agent-visible identity is `workspace_id` (Amdt 28 §10),
and `generator/tests/test_scenario_identity.py` enforces this at build time.

---

## 3. Not yet mechanized

- **blast radius** (`replace` vs `update` counts for a change) — needs the
  plan/changeset persisted as a trial artifact first; see ROADMAP M1.
- `metrics/extract_signals.py` is **not** wired into `make check` and has no
  tests yet; treat its output as analysis, not as a gate, until it does.
