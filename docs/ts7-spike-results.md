# TS7-native (`tsgo`) spike — results (2026-08-13)

Three parallel Opus agents, one per TypeScript toolchain, strictly offline in
scratch copies (no repo mutation, no AWS). Question: task #9's "adopt TS7
native tsc to cut synth memory/OOM risk" — is the OOM risk still live, and is
TS7 the fix? Measurements: `/usr/bin/time -l` peak RSS, warm (2nd) runs, judged
against the real container budgets (TS-arm trials 1 cpu / 4096 MB; scenario
deploy 2 cpu / 4096 MB).

## Headline answers

**Is OOM still a risk?** Not at today's 4096 MB budgets — but it is retired by
*headroom*, not by fixing the shape. The fragile shape (ts-node running a full
in-process type-check inside the synth process) is still present in 2 of the 3
toolchains. Measured peak utilization: awscdk arm **478 MB (12%)**,
terraconstructs arm **2385 MB (58%)**, scenario `cdk_app` deploy **1724 MB
(42%)**.

**The historical exit-137 is now fully explained.** It was `cdk_app`'s
ts-node synthesis: 1719–1724 MB tree peak, which against the pre-raise 2048 MB
limit — plus the CDK CLI's CloudFormation clients on top — lands at or over
the cgroup. Not `npm ci` (that peaks 234–389 MB and runs at image-build time).
Correction to a prior belief: `cdk deploy --all` synthesizes **once** per CLI
invocation, not per stack.

**Is TS7 the fix?** Mostly no — **removing ts-node is the fix**. TS7 is
already done where it could be done, blocked where it can't, and nearly
irrelevant to memory where the provider typings dominate.

## Per-toolchain verdict

### awscdk arm — TS7 adoption is ALREADY DONE (task #9's premise was stale)

- `typescript@7.0.2` in the workspace **is the native Go compiler**: 3.5 MB
  meta-package whose `lib/tsc.js` is a 609-byte execve shim onto a 23.6 MB
  arm64 Mach-O under `@typescript/typescript-darwin-arm64`; all 20 platform
  packages (incl. linux-x64/arm64) are in the committed lockfile, so `npm ci`
  works on both image architectures.
- ts-node is deliberately absent (`cdk.json` app = `node bin/app.js`;
  README "Why not ts-node": ts-node@10 crashes against TS7 internals).
- Measured on identical config+code: TS5.7.3 → TS7.0.2 = **4.6× faster
  (1.33 s → 0.29 s), −41% peak RSS (632.7 → 373.7 MB)**. Emitted JS is
  byte-identical, so nothing downstream changes.
- **Catch-equivalence PROVEN** (the task #9 adoption gate):
  - compile-level typed-value trap (`retention: 10` vs `RetentionDays`):
    identical file, line **and column** (22,7), identical `TS2322`,
    byte-identical message, exit 2 under both compilers;
  - swappiness structural catch: compiler-independent by construction —
    TS5/TS7 emit byte-identical JS and byte-identical templates. (Also
    corrected: `swappiness-requires-maxswap` is a **silent-drop caught by the
    tier-0 structural assert**, not a synth ValidationError; the
    ValidationError-adjacent path is the `-cfn-override` fixture.)
- `tsconfig.json` is **load-bearing TS7-only**: `moduleResolution: "bundler"`
  + `module: "commonjs"` is rejected by TS5 (TS5095) and the old `node10` is
  rejected by TS7 (TS5108) — the pin and the tsconfig must move together, in
  both directions.
- **Do NOT add `@typescript/native-preview`** anywhere: measured identical to
  `typescript@7.0.2` (same Go engine, 372.8 vs 373.7 MB) — it would only add
  a second dev-tagged compiler and ~26 MB of binaries.

### terraconstructs arm — TS7 HARD BLOCKED; the real lever is precompile

- `typescript@7` **removes the JS compiler API** (`require('typescript')`
  exports only `{version, versionMajorMinor}`), which kills ts-node@10 —
  and ts-node IS the graded synth path (`cdktf.json` app =
  `npx ts-node main.ts`). Reproduced end-to-end: with typescript@7 installed,
  `cdktn synth` exits 1 (`TypeError: … reading 'fileExists'` at
  ts-node/dist/configuration.js:91) → reward 0.0 unconditionally. `tsgo` has
  no require-hook mode, so it cannot substitute either.
- Even standalone, TS7 barely helps here: at the 1-cpu container shape
  (GOMAXPROCS=1) tsgo measures 2.47 s / 1402 MB vs tsc 5.7.3's 3.26 s /
  1478 MB — **~5% memory, ~24% wall** — because peak RSS is dominated by
  parsing ~2,915 `.d.ts` files from `@cdktn/provider-aws`, not by compiler
  implementation. Peak is structural: `--max-old-space-size` changes it by
  0.0 MB.
- **The real lever (no TS upgrade needed):** precompile and set
  `cdktf.json` app = `node dist/main.js`. Measured: synth 5.51 s / 2385 MB →
  ~3.0 s / **~1205 MB (−50%)** with the pinned tsc 5.7.3 (identical number
  under tsgo). **Preconditions before adopting:** `gen.py`'s
  `build_static_tiers_sh` must emit `rm -rf dist` + an explicit build step
  with its own nonzero-exit → reward-0.0 branch, or agents get graded against
  stale `dist/` and the compile gate silently vanishes.
- Catch-equivalence under the TS7 candidate: all shipped fixtures verdict-
  identical (diagnostics equivalence exact) — moot while blocked, on record
  for a future re-evaluation. Revisit TS7 only when a ts-node successor
  supports `typescript/unstable/*`.
- Caveat noted by the agent: terraform init/plan was not run (no offline
  mirror for hashicorp/aws 6.52.0); tier-0 asserts were checked against the
  synthesized `cdk.tf.json` literals — sound for these asserts.

### scenario `cdk_app` (deploy toolchain, the OOM site) — LAND THE PRECOMPILE FLIP

- Today: typescript 5.9.3 + ts-node 10.9.2; `deploy.sh` **already runs
  `npm run build`, emits `dist/`, then throws it away** and recompiles the
  same source in-process via ts-node at synth. The compile is being paid for
  twice.
- Measured: ts-node synth path **1719 MB / 3.11 s**; precompiled-node synth
  **835 MB / 1.66 s** — dropping ts-node removes **884 MB (−51%)** and 47% of
  wall. The full TS7 loop (native build + precompiled synth) is 832 MB /
  2.07 s, but TS7 is optional garnish: the zero-risk tsc-5.9.3 precompile
  flip captures nearly all of it.
- **Recommended commit (3 edits, zero new deps):**
  1. `cdk_app/cdk.json`: `"app": "npx ts-node lib/app.ts"` → `"node dist/lib/app.js"`;
  2. `scenario/Dockerfile`: `RUN cd /app/cdk_app && npm run build` after the
     existing `npm ci` (bakes `dist/` into the image — required, or
     cleanup.sh paths without a prior build break);
  3. `cdk_app/tsconfig.json`: add `"types": ["node"]` (harmless under 5.9.3,
     prerequisite that makes a later TS7 bump a one-liner).
  Output-equivalence verified: templates synthesized via ts-node, via
  precompiled 5.9.3, and via TS7-emitted JS are identical.
- Hard coupling recorded: a TS7 bump while `cdk.json` still says ts-node is a
  **hard break** (same `fileExists` crash) — the precompile flip must land
  first or in the same commit.

## Decisions this implies

1. Task #9 rescoped: the awscdk half is **done and now proven** (this spike is
   the catch-equivalence evidence); remaining work is **ts-node removal** in
   `cdk_app` (land now) and terraconstructs (land with the gen.py static-tiers
   precondition), not a TypeScript upgrade.
2. Keep `memory_mb = 4096` everywhere — for awscdk it is cross-arm parity of
   the trial environment (a confound otherwise), and the floor's real
   justification is terraconstructs + `cdk_app`, now with measured numbers.
3. Never regenerate the awscdk lockfile with `--omit=optional` or on a
   restricted platform — it must keep all 20 `@typescript/typescript-*`
   entries or the Linux image build breaks at `npm ci`.

Full agent reports: workflow `ts7-native-tsc-spike` (wf_d48fb98a-2ca),
2026-08-13; scratch measurements under the session scratchpad `ts7-spike/`.
