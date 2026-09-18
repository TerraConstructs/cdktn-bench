# Shell inventory — what would move if the repo carried only Python, Rego and Go

Owner aim (2026-09-11): the static-oracle toolchain and the repo's own
tooling should be Python, Rego and Go; shell stays only where it is the thing
being measured. This is the inventory that a later cleanup works from,
lowest-priority item on the M10 track. Nothing here is scheduled.

## Classes

| class | what | verdict |
|---|---|---|
| 1 | hand-written repo scripts | rewrite candidates, mostly glue over Python gates |
| 2 | generator-emitted shell that runs in the agent/verifier container | the largest surface; a Python verifier entry point replaces it |
| 3 | build-time shell (Dockerfile `RUN`, Makefile recipes) | standard Docker/Make idiom; leave, only the sha256-verify ordering is load-bearing |
| 4 | hand-authored `solution/**/solve.sh` fixtures | stay shell: they emulate an agent's bash tool calls, and `gates/audit.py` credits `bash -c 'cdk synth'` shapes because real trials run that way |
| 5 | Python subprocess calls | already argv lists, no `shell=True`; two call `bash` on generated scripts and go away with class 2 |

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
| `ASSERT_LIB_SH` (gen.py ~1754) | `tests/_assert_lib.sh`, copied to `pre_invoke/_assert_lib.sh` | ~178 lines |
| `build_static_tiers_sh` with `build_hcl_merge_block` | `tests/static_tiers.sh` | ~126 lines; calls `terraform`, `npx`, `opa`, `cfn-guard`, `jq`, `hcl2json`, `aws`. The ~160-line HCL pre-parser is `build_hcl_merge_py()` -> `tests/hcl_merge.py`, which the script invokes; the shell block is the toolchain check and the invocation only. |
| `build_test_sh` (~3868) with `build_idempotence_block` (~3460) and `build_teardown_block` (~3698) folded in | `tests/test.sh` | ~192 lines; calls `bash`, `python3` |
| `build_seed_pre_invoke_sh` (~4426), `build_step_pre_invoke_sh` (~4143), `build_seed_movement_guard` (~3355) | `pre_invoke/*.sh` | ~268 lines on a brownfield task |
| `build_solve_sh_stub` (~4832), `build_seed_unchanged_solve_sh` (~4857) | `solution/solve.sh` scaffold, the generator-owned negative | small |

About 1,200 lines of embedded bash, re-emitted into every task directory.

## Class 5 — Python shelling out

`generator/check_reference_paths.py` (`npm ci`; `bash tests/static_tiers.sh`;
one `bash -c` probe), `generator/shards.py` (`git ls-files`),
`generator/gen.py` (`hcl2json`, `terraform` at authoring time),
`gates/oracle_falsifiability.py` (`docker create/cp/rm`; `npm ci`;
`bash solution/**/solve.sh`), `gates/equipping.py` (`docker inspect`),
`gates/preflight.py` (`docker run … preflight.sh`), `gates/aws_stub.py`
(spawns itself with `sys.executable`).

## Rewrite order, largest first

1. The gen.py shell templates: one Python verifier entry point per task
   (`tests/verify.py`), keeping the same reward channel
   (`/logs/verifier/reward.txt`, bare float) and the same `== summary:` line
   the gates parse.
2. `ci/run-ci.sh` and `scripts/run-bench.sh` into a Python CLI; the make loops
   collapse into it.
3. `arms/*/environment/preflight.sh` as Python wrappers over the same tools.
4. `scenarios/anchor/{deploy,cleanup}` and the spike scripts.
5. Dockerfile `RUN` blocks stay.

## Where shell semantics are load-bearing

* `tests/test.sh` and `tests/static_tiers.sh` run under `set -uo pipefail`
  without `-e` on purpose: every tier runs and the verdicts combine; a Python
  port must not short-circuit on the first failure.
* `pre_invoke/*.sh` and the solve stubs run under `set -euo pipefail` on
  purpose: the seed deploy is fail-closed, so a port must abort on the first
  error.
* Gates read the generated scripts' exit codes and the reward file
  (`gates/oracle_falsifiability.py`, `generator/check_reference_paths.py`);
  the row format downstream (`metrics/result_schema.json`,
  `metrics/tokens_to_green.py`) depends on that channel, not on bash.
* `gates/audit.py` recognises `bash -c` / `sh -c` invocations in agent
  transcripts because agents work in a shell; that stays regardless.
* Dockerfile `sha256sum -c` before install is the supply-chain check; any
  tooling that replaces it keeps verify-then-install and fails loudly.
