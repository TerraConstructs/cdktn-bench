# Harbor upstream review: judge proposals + 0.9.0→latest diff

Read: `docs/design/model-as-oracle-spike.md`, `docs/upstream/harbor-trajectory-step-id-gap.md`,
`cdktn_bench/trial.py`, `scripts/run-bench.sh`, `gates/emit_result.py`, `generator/gen.py`
(task.toml emission), `docs/asset-mirror.md`, `docs/runner.md`, `CLAUDE.md`, `pyproject.toml`,
`uv.lock`. No `docs/aws-bench-guide.md` / `docs/harness*.md` exist in this repo. Web/GitHub
research 2026-09-24 (`gh api`/`gh search` against the live repos, no local writes besides this
file, no AWS calls).

**Repo identity, confirmed live:** the upstream project moved from `laude-institute/harbor`
(direct API calls now 403) to **`harbor-framework/harbor`** (same repo: created 2025-08-04,
5,555 stars, topics `evals`/`rl-environments`/`terminal-bench`). `laude-institute` now holds only
`terminal-bench-*` companion repos; `harbor-framework` holds `harbor`, `terminal-bench*`,
`harbor-datasets`, `adapters`, `skills`. **pip package `harbor` 0.9.0** = tag `v0.9.0`
(`1b1dbc4`, released 2026-05-28), confirmed against the installed
`.venv/…/harbor-0.9.0.dist-info/METADATA`. **`aws-bench` pins `harbor==0.9.0` as an exact
equality**, in both the rev cdktn-bench uses (`6450cb5`, 2026-08-05) and current `aws-bench` main
(41 commits ahead, still `harbor==0.9.0` today) — confirmed by fetching `pyproject.toml` at both
revisions.

## 1. Upstream proposals for LLM-as-judge / small-model verifiers

**Searches run** (`gh search issues|prs --repo harbor-framework/harbor`, plus repo code search):
`"system 1"`, `"system-1"`, `TypeSafe`, `"Jev judge"`, `"Kev model"`, `"Laya model"`,
`non-autoregressive`, `"reward model verifier"`, `"small model judge"`, `PhaseNetworkPolicyConfig`,
`"separate verifier"`, plus the `rfcs/` directory listing.

**Finding: this already exists and shipped, under the name RewardKit, not "System 1."**
Harbor has an LLM-judge verifier package, `harbor-rewardkit` (`packages/rewardkit/`), first
merged **pre-0.9.0** (PR #1398, "Reward Kit package," ~v0.6.0) as a bare judge-flag CLI. Every
maturation happened **after** 0.9.0 and continues on `main` as of days ago:

| Capability | PR | Landed | Status |
|---|---|---|---|
| `[judge]` TOML: LiteLLM model, `claude-code`/`codex`/`fx` agent, or `jev` | judge-criteria.mdx (current) | ongoing | merged |
| Individual mode, Claude-subscription auth, `REWARDKIT_MODEL`/`REWARDKIT_JUDGE` override | #1793, #1770, #1778, #2009 | v0.13.2–v0.15.0 | merged |
| MCP servers for agent judges (`[[judge.mcp_servers]]`) | #2008, #472(#2008) | v0.16.0 | merged |
| Rubric criterion type, signed/weighted aggregation, negated criteria | #2879 ("signed weighted aggregation and validated judge TOMLs") | v0.23.0 | merged |
| Send trajectory (`atif-trajectory`) + media to the judge model | #3047 | main (post‑v0.23.0) | merged |
| **JEV judge — TypeSafe's model, wired in as a first‑class RewardKit backend** | **#3325**, "feat(rewardkit): add JEV judge and rubric criteria" | **main, merged 2026‑09‑21** (3 days before this review; not yet in a tagged release) | merged |
| Judge request-concurrency bug (JEV + LiteLLM both fan out past the configured limit) | #3373 | open (2026‑09‑23) | **open** |

**PR #3325's own words, verbatim from the body:** "New JEV judge that grades through the
TypeSafe SDK, since LiteLLM cannot call JEV… Binary criteria pass at a probability of 0.5 or
higher, and the raw probability is kept in the details file." The shipped docs
(`docs-mintlify/core-concepts/rewardkit/judge-criteria.mdx`) describe JEV as "a new type of
language model from TypeSafe. It returns a probability or a rubric score per criterion and no
reasoning, so it is fast and cheap," requires the `jev` extra + `TYPESAFE_API_KEY`, grades text
files only, and caps at 32k tokens. **No occurrence anywhere in the Harbor repo of "System 1,"
"System One," "Kev," "Laya," or "non-autoregressive"** — those terms are entirely
`docs/design/model-as-oracle-spike.md`'s own vocabulary (TypeSafe's marketing term, and two
*unrelated* open-source look-alikes), not upstream Harbor's. Upstream never proposed a
pluggable-verifier *architecture* debate around this — RewardKit shipped as a general scoring
package (programmatic + judge criteria coexist, weighted/aggregated) and JEV is just one more
`judge = "..."` string value alongside LiteLLM models and agent names.

**`[verifier] environment_mode = "separate"` history:** predates 0.9.0 (PR #1655, "Add separate
verifier environments," v0.7.0, 2026‑05‑15) — the spike's citation of `single_step.py:35-42`'s
agent-torn-down-before-verifier-starts ordering is unchanged in 0.9.0 and still true on main.
Since 0.9.0 it has only been *hardened*, never redesigned: a network-mode-matrix demo (#1995,
v0.15.0), "explain separate verifier environment variables" docs (#2970, v0.23.0), and — still
**open** as of this review — a cluster of separate-verifier bugs/features (image precedence
fallback #3258, runtime config preservation #2528, shared volumes for separate verifiers #2603,
private read-only mounts #3203, artifact-transfer-drop handling #3380, per-mode
`skip_tests_upload` #3155). No RFC formalizes verifier isolation as its own design (`rfcs/`
holds only 0001-trajectory-format and 0002-simulated-users).

**The one directly relevant new primitive: per-phase network policy.** `allow_internet` is now
**deprecated** (`src/harbor/models/task/config.py`, `handle_deprecated_environment_allow_internet`
back-compat shim, kept only for migration). In its place: `[environment].network_mode`
(`public`/`allowlist`/`no_network`, `BaselineNetworkPolicyConfig`) **plus** a genuinely new
`PhaseNetworkPolicyConfig` mixed into **both** `AgentConfig` and `VerifierConfig`, letting
`[agent].network_mode` and `[verifier].network_mode` override the baseline independently, with
CIDR/wildcard/IPv6 allowlists (PR #1799 "Network mode support for docker environment," v0.16.0,
plus #1455 v0.13.0 for the base concept). This is exactly the missing piece the spike's
recommendation-item-1 wanted ("agent's environment carrying `allow_internet: false`… while the
verifier's own separate environment stays able to reach its sidecar") — it is now a native
per-phase TOML field, not something that must be inferred from `environment_mode=separate`
alone. It does not change the spike's core verdict (a judge is still not gating-fit on
determinism/injection/pinning grounds), but it removes one item from "what a future amendment
would have to build" (§ Recommendation item 1 of the spike).

**Implication for cdktn-bench:** the spike's recommendation — no model in a gating role; model
as authoring aid / red-team / advisory annotator only — is **strengthened, not undercut**, by
what shipped. RewardKit's own JEV integration inherits every fitness gap the spike catalogued:
binary criteria pass at p≥0.5 with the *raw probability* kept only in a details file (not
gating semantics harbor enforces — a task author decides how to weight it), no determinism
guarantee is claimed anywhere in the docs, and the concurrency bug (#3373, open) shows this
subsystem is still finding its own race conditions three days after the TypeSafe integration
landed. Nothing here reads as "upstream solved verifier trustworthiness" — it reads as "upstream
added a fast/cheap judge option with the same probabilistic-verdict shape the spike already
rejected for gating."

## 2. Harbor changes since 0.9.0 (14 tagged releases: v0.13.0 → v0.23.0, plus `main` ahead)

Full release notes diffed via `gh api repos/harbor-framework/harbor/releases`
(`v0.9.0` 2026-05-28 → `v0.23.0` 2026-09-12, pushed `main` 2026-09-24). Grouped by area; ✕ = no
cdktn-bench file touches this; a cited file means it would need review at upgrade time.

| # | Change | Landed | Bench impact |
|---|---|---|---|
| 1 | **Trajectory step-id gap — fixed.** PR #1741 dedupes session events by `uuid`, tracks `completed_call_ids`, and **assigns `step_id` from `len(steps) + 1` at emission time instead of the raw event index** — exactly the workaround's own "suggested fix." Confirmed on current `claude_code.py:1561`: `self._convert_event_to_step(norm_event, len(steps) + 1)`. | v0.13.0 (2026‑05‑30) | Directly obsoletes `docs/upstream/harbor-trajectory-step-id-gap.md` and the fallback path it documents in `gates/audit.py`/`gates/emit_result.py` (the `docs/upstream/harbor-trajectory-step-id-gap.md`-cited transcript fallback, `emit_result.py` lines ~458-462). Needs live re-verification post-upgrade, not just code deletion — the two documented affected trials should be replayed against the new converter before the doc is retired. |
| 2 | **Claude-code trajectory shape rewrite (RFC‑0001).** PR #1760 bundles one LLM turn (text + reasoning + *every* tool_use sharing a `message.id`) into a single ATIF step, replacing one-step-per-content-block. Step count on a real 37-tool-call session: 59→39. | v0.13.1 (2026‑06‑01) | `gates/emit_result.py`'s per-step/tool-call counting (`_count_llm_calls_from_trajectory` and friends, lines ~380-530) assumes today's fragmented one-tool-per-step shape; re-derive those counts against the bundled shape before trusting any tokens/turn ratio post-upgrade. |
| 3 | **Per-phase network policy.** `allow_internet` deprecated; `[agent]`/`[verifier].network_mode` (`PhaseNetworkPolicyConfig`) plus richer `[environment].network_mode` (allowlist/CIDR/wildcard/IPv6). | v0.13.0–v0.16.0 | `specs/SCHEMA.md §0.2`, `generator/gen.py`'s `[environment]`/`[agent]`/`[verifier]` emission, and `model-as-oracle-spike.md §2` (any future judge-sidecar amendment). Backward-compatible shim exists but is a deprecation warning surface worth silencing deliberately, not by accident. |
| 4 | **RewardKit maturation** (§1 table). | v0.13.x–main | Not used by cdktn-bench today (oracle is generated Python + jq/OPA, Amendments 43-45) — pure optionality, but the JEV/`jev` extra path is the concrete implementation the model-as-oracle spike would prototype against if that recommendation is ever revisited. |
| 5 | **`harbor job/trial regrade` for multi-step trials.** PR #2907: replays each completed step's recorded agent artifacts into a fresh **separate** verifier environment and re-scores, without rerunning the agent; rejects shared-mode steps, missing manifests, reordered/incomplete step records. | v0.23.0 (2026‑09‑11) | Directly relevant to `cdktn_bench/trial.py`'s `CdktnMultiStepTrial` (multi-step AWS trials) — a verifier-only oracle-fix pass without a re-deploy is exactly the kind of AWS-cost-avoidance this bench cares about, **but** it requires shared-mode-verifier rejection to not apply, and cdktn-bench's own `validate_multi_step_layout` (`trial.py:389-409`) **bans separate-mode verifiers on every step** ("aws-bench phase scripts run in the agent container"). Regrade would need that constraint revisited or a bench-side equivalent built; not free to adopt. |
| 6 | **Agent options declared via Pydantic, not module-level `CLI_FLAGS`/`ENV_VARS`.** PR #3049: `ClaudeCodeOptions(InstalledAgentOptions)` with `Annotated[int \| None, Cli("--max-turns", fallback="CLAUDE_CODE_MAX_TURNS")]` replaces the old `CLI_FLAGS` list; **unknown `--ak` kwargs now fail at preflight** for migrated agents (claude-code included). | v0.23.0 (2026‑09‑03) | `scripts/run-bench.sh`'s header cites `CLI_FLAGS: CliFlag("max_turns", cli="--max-turns", ...)` as its verified evidence for the `--ak max_turns=N` mapping — that citation is now stale (the class is gone) though **the behavior is unchanged**: `max_turns` still maps to `--max-turns` via `Cli(...)` on `ClaudeCodeOptions`, confirmed read directly off `main`. Low-risk doc-only drift, but the new preflight-fails-on-unknown-kwarg behavior is worth a smoke test before upgrading, since run-bench.sh passes `--ak` and `--ae` pairs that were previously tolerant. |
| 7 | **`SingleStepTrial.__init__` now requires `_task_download_result`** (harbor 0.22.0, per aws-bench#74 item 3: "0.22.0 records it in the trial lock… `AwsBenchTrial.create` resolves it with the same `TaskClient.download_tasks` call harbor's `Trial._load_task` makes"). | somewhere v0.14.0–v0.22.0 | **Direct hit on `cdktn_bench/trial.py`'s `CdktnMultiStepTrial.__init__`**, which hand-copies both parents' pre-`super()` state fields specifically to bypass `SingleStepTrial`'s/`MultiStepTrial`'s incompatible guards (`trial.py:214-239`, "sets all five, then calls `Trial.__init__` explicitly"). A new required pre-`super()` field means that hand-copied list goes stale silently — no test would catch it except `cdktn_bench/tests/test_trial_mro.py`, which only asserts *method* resolution, not `__init__`'s field list. |
| 8 | **`BaseInstalledAgent._exec` no longer merges an agent's `_extra_env`** into commands (0.22.0, aws-bench#74 item 4) — `Trial` now snapshots `extra_env` before `run()` and applies it via `environment.scoped_exec_env`. | v0.16.0–v0.22.0 (exact PR not isolated; confirmed only via aws-bench's own upgrade-PR changelog) | Not directly touched by cdktn-bench (no custom `_extra_env` agent), but confirms the installed-agent env-injection contract changed shape — worth re-checking `scripts/run-bench.sh`'s `--ae CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` / `BASH_DEFAULT_TIMEOUT_MS` forwarding still lands the same way. |
| 9 | **`AgentFactory._AGENT_MAP` resolves lazily; no `_AGENTS` list** (0.22.0, aws-bench#74 item 1). | v0.14.0–v0.22.0 | aws-bench's own agent-registration override breaks here, not cdktn-bench's (`cdktn_bench.cli.install_job_class` only rebinds `AwsBenchJob`, never touches agent registration) — but it is evidence the agent-registry surface is not stable across this range, worth a targeted check if cdktn-bench ever registers a custom agent. |
| 10 | **`environment_content_hash` replaces `environment_template_hash`/`environment_dir_hash`** (dirhash-based → content-based; hash suffix 8→12 chars for several cloud sandbox providers). PR #2190. | v0.18.0 (2026‑07‑07) | ✕ — this is Harbor's own internal snapshot-naming hash for cloud sandbox providers (E2B/Novita/Blaxel/Daytona), unrelated to `gates/equipping.py`'s `compose_sha256`/`harbor_equipping`, which reads task-directory bytes directly and never calls into this. No collision risk, just worth knowing the field it might be tempting to reuse was renamed. |
| 11 | **`docker_image` tasks can omit `environment/Dockerfile`.** PR #1729 (v0.9.0-adjacent, merged 2026-05-27 — one day before the 0.9.0 tag, so **not** in the installed 0.9.0 wheel; confirm on upgrade). | any future arm using a prebuilt image instead of a Dockerfile | ✕ today (every arm ships a Dockerfile per `docs/asset-mirror.md`), but relevant if a future arm wants to skip the asset-mirror Dockerfile pattern entirely. |
| 12 | **`build_timeout_sec` default unchanged: `600.0`.** Confirmed directly against `src/harbor/models/task/config.py` on current `main` — no PR found changing it. | n/a | The `docs/asset-mirror.md` 600s cold-build workaround is **still needed**; nothing upstream raised or made configurable-by-default here since 0.9.0 (it is a `task.toml`-settable field already, unchanged). |
| 13 | **No compose sidecar merge-order change found.** Searched for overlay/merge-order PRs; the only compose-adjacent changes since 0.9.0 are cloud-sandbox-specific (GKE multi-container DinD, `#1773`/`#1843`, Modal/Daytona network toggling) — none touch the local Docker Compose provider's file-merge order `arms/hcl-modules/environment/docker-compose.yaml` relies on. | n/a | ✕ — no action needed. |
| 14 | **CLI/registry surface grew substantially**: `harbor job/trial regrade`, `harbor job/trial init`, `harbor hub` (publish/leaderboard/share/copy/rename/ownership), `--repo` git-dataset registries, canonical published task config, package version metadata, org-first auth. | v0.13.0–v0.23.0 | ✕ for cdktn-bench's own `local-registry.json`/`generator/gen.py` flow (file-based, not Hub-based) — but `cdktn-bench`'s CLI wiring (`cdktn_bench/cli.py`, re-registering aws-bench's `start` function) inherits whatever Typer-app shape `harbor.cli` exposes only *through* `aws_bench.cli.jobs`; not directly through Harbor's CLI, so this is lower risk than it looks. |

**Breaking-change summary:** items 6, 7, 8, 9 are all surfaced by **aws-bench's own in-flight
upgrade PR**, `aws-bench/aws-bench#74` ("chore(deps): upgrade harbor to 0.22.0" — one release
behind current `v0.23.0`), open since 2026‑09‑17, still answering review comments as of
2026‑09‑22 (`mergeable: UNKNOWN`). Its body is the single best primary source for what actually
breaks: 15 files changed (+173/‑66 production, the rest tests/lockfile), touching
`agents/__init__.py`, `agents/codex.py`, `agents/opencode.py`, `agents/mini_swe_agent.py`,
`cli/job_config.py`, `cli/jobs.py`, and **`task/aws_trial.py`** — the exact module
`cdktn_bench/trial.py` subclasses (`AwsBenchSingleStepTrial`). No corresponding PR exists yet for
0.9.0→0.23.0 in one jump; #74 only gets to 0.22.0 and is unmerged.

## Recommendation: **not yet — revisit after aws-bench#74 merges, before/alongside M3**

1. **Upstream aws-bench, the layer cdktn-bench explicitly refuses to vendor or fork
   (`CLAUDE.md`: "Nothing in this package may modify `aws_bench` or `harbor` source"), has not
   itself finished qualifying a jump past 0.9.0.** Its own upgrade PR is open, unmerged, one
   release behind latest, and already needed five substantive adaptations
   (`task/aws_trial.py`, two agent adapters, CLI config typing, an installed-agent env-resolution
   order fix) plus 650+ lines of new/changed tests to pass `make check`. Pulling harbor forward
   in cdktn-bench alone — bypassing aws-bench's pin — would mean re-deriving all of that
   adaptation work independently, against a dependency cdktn-bench does not own.
2. **The one upgrade-blocking bug this bench built a whole doc + workaround around
   (`docs/upstream/harbor-trajectory-step-id-gap.md`) is fixed as of v0.13.0**, four releases
   before aws-bench's own target of 0.22.0. That is real pull toward upgrading, but the fix
   landed alongside a full trajectory-shape rewrite (RFC‑0001, item 2) that changes what
   `gates/emit_result.py`'s step/tool-call counters are counting — the workaround doc can't just
   be deleted, it needs replacing with a verification that the new converter's output matches
   this bench's own token/turn accounting assumptions.
3. **`CdktnMultiStepTrial.__init__`'s hand-copied pre-`super()` state is the highest-risk single
   spot.** It exists precisely because it bypasses two upstream `__init__` guards by hand; a new
   required field (`_task_download_result`, confirmed needed by 0.22.0 per aws-bench#74) is
   exactly the kind of upstream-internal-state change that hand-copy is structurally blind to
   until a live trial fails. `cdktn_bench/tests/test_trial_mro.py` does not cover `__init__`
   fields, only method resolution — an upgrade would need that test extended before it could
   catch this class of drift again.
4. **Timing: wait for aws-bench#74 to merge (or close as superseded), then re-run this diff
   against whatever harbor version aws-bench actually lands on** — likely not 0.23.0 either,
   since #74 targets 0.22.0. Do this as a dedicated slice, not folded into M3: it touches
   `cdktn_bench/trial.py`, `cdktn_bench/tests/test_trial_mro.py`,
   `cdktn_bench/tests/test_queue_drift.py`, `scripts/run-bench.sh`'s stale `CLI_FLAGS` citation,
   and both `docs/upstream/harbor-trajectory-step-id-gap.md` and `gates/emit_result.py`'s
   trajectory counters — a strictly larger footprint than M3's own scope (`docs/design/tf-modules-arm.md`).
   Track it as its own amendment candidate once aws-bench#74 lands, with a live smoke run
   (Amendment-pattern: harness-changing → re-enters DRAFT until its own first live run) before
   any promotion.
