# Shell inventory — what would move if the repo carried only Python, Rego and Go

Owner aim (2026-09-11): the static-oracle toolchain and the repo's own
tooling should be Python, Rego and Go; shell stays only where it is the thing
being measured. This is the inventory that a later cleanup works from,
lowest-priority item on the M10 track. Nothing here is scheduled.

## Classes

| class | what | verdict |
|---|---|---|
| 1 | hand-written repo scripts | rewrite candidates, mostly glue over Python gates |
| 2 | generator-emitted shell that runs in the agent/verifier container | was the largest surface; the verifier moved to Python (Amendment 44) and the brownfield seed deploy is what is left |
| 3 | build-time shell (Dockerfile `RUN`, Makefile recipes) | standard Docker/Make idiom; leave, only the sha256-verify ordering is load-bearing |
| 4 | hand-authored `solution/**/solve.sh` fixtures | stay shell: they emulate an agent's bash tool calls, and `gates/audit.py` credits `bash -c 'cdk synth'` shapes because real trials run that way |
| 5 | Python subprocess calls | already argv lists, no `shell=True`; the two that call `bash` on a generated script now reach a shim |

## Class 1 — hand-written

| path | lines | calls |
|---|---|---|
| `scripts/run-bench.sh` | 421 | `uv`, sources the token resolver |
| `scripts/lib/resolve-claude-token.sh` | 95 | pure bash |
| `ci/run-ci.sh` | 275 | `make`, `uv`, optional `docker` |
| `ci/check-scenario-artifacts.sh`, `ci/check-shard-drift.sh`, `ci/check-smoke-drift.sh` | 37, 18, 41 | `find`, `git`, `diff` |
| `Makefile` `build-arms`/`preflight` loops; `mk/*.mk` `gen-all`/`parity-all`/`gate-preflight` loops | ~70 + ~260 | `docker`, `uv` |
| `scenarios/anchor/deploy/deploy.sh`, `cleanup/cleanup.sh` | 29, 24 | `npm`, `cdk` |
| `arms/{awscdk,hcl-raw,terraconstructs}/environment/preflight.sh` | 103, 62, 94 | `tsc`, `cdk`, `terraform`, `jq`, `cdktn` |
| `scripts/spike/compare_engines.sh`, `probes.sh` | 66, 56 | `opa`, `regorus` (spike only) |

## Class 2 — emitted by `generator/gen.py`

| emitter | lands as | size |
|---|---|---|
| ~~`ASSERT_LIB_SH`~~ | **DONE** (DECISIONS.md Amendment 43): ~178 lines of bash became `generator/tier0_py.py`'s `OPS_PY` (`tests/ops.py`, copied to `pre_invoke/ops.py`) plus a generated `tests/tier0.py` assert table. The jq filters are unchanged; the op table, the three-valued outcome and the regex flavour moved to Python. `is_stub_policy` is now `tests/tiers.py`'s. |
| ~~`build_static_tiers_sh`~~, ~~`build_test_sh`~~ | **DONE** (DECISIONS.md Amendment 44): the verifier is Python. `tests/tiers.py` is the mechanism (the toolchain runner and its `== label:` / `LABEL FAILED` lines, the `aws sts get-caller-identity` preflight and its VOID, tier 0, the HCL pre-parse, tier 1 and every status, the summary line, the reward gate, the seed-receipt guard, the live check, and one shared `live_tier` both live tiers configure), byte-identical in every task; `tests/verify.py` is this task's configuration. `tests/test.sh` and `tests/static_tiers.sh` remain as ~14-line shims, because harbor executes the first path and every hand-authored `solution/**/solve.sh` ends by running the second — and because the two in-container paths are exported there, which is how a host-side gate repoints the whole chain with one text patch. |
| `build_seed_pre_invoke_sh` (~4426), `build_step_pre_invoke_sh` (~4143), `build_seed_movement_guard` (~3355) | `pre_invoke/*.sh` | ~268 lines on a brownfield task |
| `build_solve_sh_stub` (~4832), `build_seed_unchanged_solve_sh` (~4857) | `solution/solve.sh` scaffold, the generator-owned negative | small |

About 300 lines of embedded bash left, all of it the brownfield seed deploy
and the solve-stub scaffold (1,200 before the tier-0 library moved, ~1,000
before the verifier did).

## Class 5 — Python shelling out

`generator/check_reference_paths.py` (`npm ci`; `bash tests/static_tiers.sh`),
`generator/shards.py` (`git ls-files`),
`generator/gen.py` (`hcl2json`, `terraform` at authoring time),
`gates/oracle_falsifiability.py` (`docker create/cp/rm`; `npm ci`;
`bash solution/**/solve.sh`), `gates/verifier_parity.py` (the same),
`gates/equipping.py` (`docker inspect`),
`gates/preflight.py` (`docker run … preflight.sh`), `gates/aws_stub.py`
(spawns itself with `sys.executable`).

## Rewrite order, largest first

1. ~~The gen.py shell templates~~ — DONE, Amendment 44. What is left of class
   2 is the brownfield `pre_invoke/*.sh` family, which runs fail-closed under
   `set -euo pipefail` and is a different port.
2. `ci/run-ci.sh` and `scripts/run-bench.sh` into a Python CLI; the make loops
   collapse into it.
3. `arms/*/environment/preflight.sh` as Python wrappers over the same tools.
4. `scenarios/anchor/{deploy,cleanup}` and the spike scripts.
5. Dockerfile `RUN` blocks stay.

## Where shell semantics are load-bearing

* The verifier runs every tier and combines the verdicts, which is what
  `set -uo pipefail` without `-e` bought: `tests/tiers.py` must not
  short-circuit on the first failure, and `tests/tier0.py` honours the same
  rule inside tier 0 -- every assert's own verdict, returning the worst.
* `pre_invoke/*.sh` and the solve stubs run under `set -euo pipefail` on
  purpose: the seed deploy is fail-closed, so a port must abort on the first
  error.
* Gates read the generated verifier's exit code and the reward file
  (`gates/oracle_falsifiability.py`, `generator/check_reference_paths.py`), and
  repoint it at a sandbox by text-patching the `static_tiers.sh` shim's exports;
  the row format downstream (`metrics/result_schema.json`,
  `metrics/tokens_to_green.py`) depends on that channel, not on bash.
* `gates/audit.py` recognises `bash -c` / `sh -c` invocations in agent
  transcripts because agents work in a shell; that stays regardless.
* Dockerfile `sha256sum -c` before install is the supply-chain check; any
  tooling that replaces it keeps verify-then-install and fails loudly.
