# TS runtime spike 2 — entrypoints, typestripping, and d.ts pruning (2026-08-13)

> ## ⚠ HISTORICAL EVIDENCE — measurements, not current configuration
>
> This is the **measurement record** behind a decision that has since landed.
> Read it for the evidence and the rejected alternatives; do **not** read it as
> a description of how the repo is configured today.
>
> **What landed:** `DECISIONS.md` **Amendment 25** adopted this doc's
> consolidated verdict as a single package — `tsc` (emitting) → `node`
> everywhere, the compile **chained into the synth app command** on both graded
> arms, `skipLibCheck: true` on the terraconstructs tsconfig, an unconditional
> build-gate injection in the generator, and a precompiled `dist/` in the
> harness `cdk_app` (which pays its compile once at image build, deliberately
> *not* chained, because no agent ever edits that tree). Every alternative
> venue below — bun, tsx, node type-stripping / cdk-terrain #198, deep-import
> d.ts pruning — was **rejected**, and remains rejected. **`ts-node` is off
> every execution path.**
>
> Amendment 25 is the authority on what shipped and on the exact per-file
> changes; this doc is why.

Follow-up to `docs/ts7-spike-results.md`, operator-directed. Five parallel
agents (2 Sonnet confirm/recon, 3 Opus measurement), strictly offline in
scratch copies. Operator's consolidation rule: **no mixing venues — one
strategy across all three TS trees.** Operator's frame: the compile/type-check
is never droppable on graded arms (the typed interfaces are the thesis); only
the synth *execution* step is on the table, preferring "re-use what was
compiled."

## The consolidated verdict

**One uniform shape everywhere: `tsc` (the gate, emitting) → `node` on the
emitted JS — with the compile chained into the synth command on graded arms so
the agent can never run stale JS.** No new runtimes. Two riders:
`skipLibCheck: true` on the terraconstructs tsconfig, and an unconditional
build-gate injection in the generator. Every alternative venue was measured
and rejected on evidence:

| venue (uniform) | verdict | why |
|---|---|---|
| **A. tsc-emit → node** | **ADOPT** | wins or ties memory everywhere once the mandatory gate is counted; zero new deps; awscdk already has this shape |
| B. bun | REJECT | awscdk: memory *worse* (+5% tree), bun-on-emitted-JS hard-crashes (source-map-support × inlineSourceMap), template no longer byte-identical (spoofed node version in CDKMetadata). tcons: best raw synth (746 MB tree) **but** the arm peak = max(gate, synth) = the gate, so bun's synth win cannot move the peak; silently deletes the compile gate (proven: `retention: 10` escaped); +92 MB second runtime to pin; JSC heap sizing makes numbers least transferable to a cgroup |
| C. tsx | REJECT (legit 2nd) | zero source changes needed, but precompile beats it on memory in both trees (870 vs 942 MB; 1093 vs 1369 MB), adds esbuild + postinstall scripts, and lets compile-only traps escape silently (proven live) |
| D. node type-stripping / cdk-terrain #198 | REJECT | #198 is a regression *test*, not a feature — `app: "node main.ts"` relying on Node's built-in stripping (zero type-checking, by documented design). Doubly blocked here (cdktn 0.23.0 predates `importExtension`; image node 20.20.2 has no stripping). Worse: it demands a non-idiomatic TS dialect (`.ts` import extensions, `import type` everywhere, no enums/decorators/param-properties — terraconstructs@0.2.13 ships no `exports` map so deep imports die as ESM dir-imports; `"type":"module"` breaks mock-sts.js). Forcing agents into that dialect would **confound the arm comparison** |
| E. d.ts pruning via deep imports | REJECT — hypothesis dead **structurally** | the 2,341-namespace `@cdktn/provider-aws` barrel is pulled by `terraconstructs/lib/aws/aws-stack.d.ts:2` (the mandatory base class), not by agent imports — deep-importing changed the measured Program by ~0 files. There is **no agent-side lever**; this permanently retires any "hint agents to deep-import" idea |

## The two proven hazards (why the shape must be exactly this)

1. **Stale-JS gate loss** (operator's concern, reproduced): with
   `app = "node main.js"` and a stale good JS, editing the `.ts` to a
   type-broken state still synths **exit 0 with the old code** — a broken
   solution scores as correct, and an agent's edit silently "does nothing"
   (phantom-debug tokens = harness artifact corrupting tokens-to-green).
   `noEmitOnError: true` means a failing build never overwrites good JS, so
   **the build step's exit code is the load-bearing gate** — it must be
   impossible to skip. Hence: *chain it into the app string* on graded arms —
   `"app": "npx tsc -p tsconfig.json && node main.js"` — every synth
   recompiles fresh by construction; `&&` short-circuits a type error into a
   synth failure exactly like ts-node's UX; sequential execution means peak =
   **max**(gate, synth), not the concurrent sum ts-node pays. Warm incremental
   re-check is ~1.8 s / ~998 MB (tcons) and 0.13 s / 385 MB (awscdk) — a cheap
   per-iteration tax. (The awscdk arm's current unchained
   `app = "node bin/app.js"` carries the same desync hazard today; the
   uniform chained shape fixes it there too.)
2. **Transpile-only runners invert the instrument** (proven live, both trees):
   under tsx and strip-types, a compile-only trap (excess property TS2561;
   typed-value trap TS2322) synthesized **byte-identical templates, exit 0**
   — the catch escapes silently. ts-node holds those gates today. Any venue
   that removes type-checking from the loop also removes the *steering* the
   benchmark exists to measure — type errors must stay in the agent's
   iteration loop, not only at final grading.

## Measured outcomes of the adopted shape (tree RSS, warm)

| tree | today (ts-node) | adopted shape | peak vs 4096 MB |
|---|---|---|---|
| awscdk workspace | — (already this shape) | 775 MB / 2.2 s | 19% (unchanged) |
| terraconstructs app | 2,221–2,385 MB / 5.5–7.3 s | **~1,092 MB / ~2.9 s** synth; gate 989 MB / 1.9 s with skipLibCheck | **27% (from 54–58%)** |
| scenario cdk_app | 1,719–1,818 MB / 3.1–3.4 s | **~870 MB / ~1.9 s** | ~21% of deploy budget (from ~42%) |

Output equivalence: `cdk.tf.json` / templates byte-identical across ts-node vs
precompiled-node in every cell (modulo scratch-dir state paths and metadata
construct-trace line numbers).

`skipLibCheck: true` (tcons): type-check 1,416 → 989 MB and 4.36 → 1.89 s
(−30% RSS, −57% wall), **catch-preserving** — all five typed-value traps
(TS2322/TS2561 family) still fire, verified. It does nothing for the ts-node
synth path, so it only pays off *with* the precompile flip — the changes are a
package. The hard floor: the provider runtime `require` graph is ~1.4 GB at
synth; sub-1 GB terraconstructs synth needs upstream `@cdktn/provider-aws`
repackaging (out of scope). The one "true" pruning fix (a hand-slimmed
provider shim, 382 MB) is **fairness-fatal** and rejected.

## Landing plan (one package, between runs)

1. **terraconstructs (graded — needs falsifiability + grading-proof re-run):**
   - `arms/terraconstructs/environment/app/cdktf.json:3` (the single
     authoritative source; verified byte-identical in all 5 tasks, propagated
     verbatim by `gen.py::write_environment`'s copytree):
     `"app": "npx ts-node main.ts"` → `"npx tsc -p tsconfig.json && node main.js"`
     (tsconfig has no outDir — emits in place next to sources).
   - `arms/terraconstructs/environment/app/tsconfig.json`: + `"skipLibCheck": true`.
   - `generator/gen.py`: unconditionally inject an explicit build/type-check
     toolchain step (own nonzero-exit → reward 0.0 branch) for every
     `arm == "terraconstructs"` spec — same unconditional pattern as its
     tf-plan step — rather than relying on per-spec `build_command` YAML
     discipline. (The `build_command` machinery already exists and is what
     awscdk uses.)
   - Sync `arms/terraconstructs/README.md:52-57,179` prose; `make gen-all`;
     re-run falsifiability + grading-proof.
2. **awscdk (consistency, low risk):** chain the gate into
   `cdk.json` app (`"npx tsc -p tsconfig.json && node bin/app.js"`) via its
   arm template, closing the same desync hazard; `build_command` step stays.
3. **cdk_app (plumbing, no agent — no chaining needed):** the spike-1 flip
   unchanged — `cdk.json` app → `"node dist/lib/app.js"`, Dockerfile bakes
   `dist/` after `npm ci`, tsconfig + `"types": ["node"]`. Requires env-setup
   re-run.
4. Optional rider: bake a warm `.tsbuildinfo` into the tcons image at build
   time so the agent's first in-trial compile pays the warm (1.8 s) cost, not
   the cold (4.4 s) one.

**Rejected permanently** (with evidence on file): bun, tsx,
`--experimental-strip-types` / `--experimental-transform-types`, the
cdk-terrain #198 pattern at current pins, deep-import hints, slim provider
shims, and any transpile-only runner on a graded arm.

Full agent reports: workflow `ts-runtime-spike-2` (wf_15564bfe-047),
2026-08-13; scratch measurements under the session scratchpad `ts-spike2/`.
