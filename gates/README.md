# gates

The three-gate integrity pattern borrowed from lex00 (build plan Phase 0, the "single
most valuable thing in the fork"):

1. **preflight** — the arm's toolchain actually works in its container
   (`tsc --version`, `cdk --version`, `terraform version`, provider mirror warm).
   Driven by `make preflight` at the repo root.
2. **audit** — the trial *actually ran the substrate's toolchain*, not a shortcut.
   Parses `agent/trajectory.json` for `tsc`/`cdk synth` / `terraform validate|plan`
   invocations by shell-tokenized argv position (not a substring/mention match — a
   `#`-comment or an `echo`/`grep`/`cat` argument that merely mentions the tool never
   counts), and cross-checks each matched call's own `observation` text for
   command-not-found/SIGKILL signals so a positionally-matched-but-never-actually-ran
   call is flagged as a degraded arm rather than credited as evidence; a green trial
   that never ran the arm's toolchain is invalid, not scored. Rationale: lex00's first
   round scored CDK 11/15 while 0-2 of 24 trials ever ran `cdk`.
3. **emit-result** — refuses to emit a result record for an invalid run (validity is a
   separate class from a low score; e.g. a `cdk synth` OOM is infrastructure-invalid,
   never a scored CDK failure).

Also owns the **equipping hash** (SHA of instruction.md + skill/MCP config + Docker
image digest) written into every result record, so results can never be silently
pooled across different equippings.

## Status: implemented (Slice B)

| File | Role |
| --- | --- |
| `preflight.py` | Gate 1 CLI + `run_preflight(arm, ...)`. Runs `docker run --rm --network none --memory 4g --entrypoint <arm's in-container preflight.sh> <image>` (the same invocation `make preflight` / each arm's own `./preflight.sh` use) and returns/prints a JSON report (`ok`, `exit_code`, `reason`, `stdout`/`stderr` tails). `reason` is a machine-readable failure category (`image-not-found`, `docker-daemon-unreachable`, `oom-killed`, `entrypoint-not-found`, `preflight-script-failed (exit N)`, `docker binary not found: ...`, `preflight timed out after Ns`) derived from exit code + positive-evidence text matching, not `$? == 0` alone. The docker call is injectable (`runner=`) for testing without a daemon. Wired into the make surface via `make gate-preflight` (mk/rails.mk; not part of `check` — needs the arm images already built, same reasoning as the root Makefile's own `preflight` target). Gate 1 is a **pre-job** check ("does this arm's toolchain work at all, offline"), not a per-trial verdict — it has no `validity_class` of its own in `metrics/result_schema.json` (see that field's description) and is deliberately out of the per-row taxonomy Gates 2+3 populate. |
| `audit.py` | Gate 2 CLI + `audit_trajectory()`/`audit_trial()`. Reads Harbor's ATIF `trajectory.json` (`agent/trajectory.json` under a trial dir), walks `steps[].tool_calls[]` for `function_name == "Bash"`, shell-tokenizes each `&&`/`;`/`|`-delimited segment of `arguments.command` (comments stripped, wrapper prefixes like `npx`/`sudo`/env-assignments peeled), and credits a match only when the arm's tool is the resulting **argv[0]** (by basename), with the required subcommand present in the later argv tokens: `awscdk` → `tsc` or `cdk ... synth`; `hcl-raw` → `terraform ... validate` or `terraform ... plan`; `terraconstructs` → `cdktn ... synth`. This positional check (not a substring/regex mention match) is what keeps `echo 'cdk synth'`, a `#`-comment, `cat cdk-synth-notes.txt`, `grep -r 'cdk synth' .`, `which tsc`, etc. from counting — they all put a *different* tool in argv[0]. Word-exact so e.g. `cdktn synth` never satisfies `awscdk`'s `cdk synth` pattern. Each matched call is additionally joined to its own `observation` (`source_call_id`) and classified `ok`/`failed`/`missing`/`sigkill`/`unknown`; a call whose observation shows `command not found`/exit 127 or SIGKILL/exit 137 is NOT credited as valid evidence (`degraded: true` instead — see `emit_result.py`) but a call that genuinely ran and failed still is. Returns `{valid, evidence: [...], degraded, degraded_kind, reason, arm, bash_call_count}`. A trial whose trajectory never ran the arm's tool is `valid: false`, `reason` prefixed `invalid-bypass:` — this is the lex00 "CDK 2/24, Alchemy 0/24" finding's detector. |
| `emit_result.py` | Gate 3 CLI + `build_result_record()`. Runs the audit gate, scans the trial dir's **harness-owned** logs only (`trial.log`, `exception.txt`, `result.json` — never `agent/agent-output.txt`/`agent/claude-code.txt`, which are the agent's own output and would let an agent or task instruction self-void a genuine trial by typing an infra phrase) for infra-failure signals (OOM/`exit 137`, Docker-daemon-unreachable, auth/env-credential errors) via `classify_infra_failure()`, and classifies the trial into `valid` / `invalid-bypass` / `invalid-infra` (infra takes priority — a container OOM-killed before it could invoke the toolchain didn't "choose" to bypass it; so does a trial the audit gate found `degraded` — toolchain invoked but never actually available). Calls `equipping.compute_equipping_hash(task_dir, image_ref, extra_cfg)` (real implementation, owned by a companion module) and attaches `equipping_hash` to every record, including refused ones. **Refuses to emit score/reward fields for any non-`valid` trial** (`score_emitted: false`, no `reward`/`cost_usd`/token keys at all) — best-effort score extraction from the harbor-level `result.json` only happens for `valid` trials. `to_result_row()` maps a record + run config (model/harness/oracle_version/...) into a `metrics/result_schema.json`-shaped row — the schema's actual producer (see `metrics/emit_fixture_rows.py`). |
| `equipping.py` | `compute_equipping_hash(task_dir, image_ref, extra_cfg) -> str` (64-hex-char sha256). Owned by a companion module (not authored in this pass) — imported as-is by `emit_result.py`. |
| `tests/` | pytest suite (`uv run pytest gates/tests -v`). `tests/fixtures/<arm>/{genuine,bypass,infra-failure}/` are synthetic per-arm trial dirs (one `agent/trajectory.json` each, plus a `result.json` for `genuine` and a `trial.log`/`exception.txt` carrying an infra signal for `infra-failure`) proving all three gates' verdicts end-to-end without Docker, a real trial, or network access. `test_preflight.py` injects a fake docker runner instead. |

Run everything: `uv run pytest gates/tests -v` (or `make gates-test`, see `mk/rails.mk`).

No package build step needed — `gates/` has no `__init__.py` by design (see
`gates/tests/conftest.py`): every module resolves as a PEP 420 implicit
namespace package once the repo root is on `sys.path` (which `conftest.py`
adds), so this stays compatible regardless of which directory a given test
file imports its siblings from.
