# cdktn-bench runner — reference

Long-form material that would otherwise sit in a file header under
`cdktn_bench/`. Each section is referenced from the file it describes.

## Package layout

`cdktn_bench` extends `aws_bench` with one capability upstream refuses:
multi-step trials. `aws_bench/task/aws_trial.py`'s `AwsBenchTrial.create`
raises *"multi-step AWS tasks are not yet supported (per-step pre/post-invoke
credentialing is undefined)"*. Everything else — credential staging,
placeholder substitution, scenario admission gating, account reset, CLI flag
parsing, export collection, contamination checks — is inherited by import,
never vendored or copied.

- `cdktn_bench.trial` — `CdktnMultiStepTrial` (Harbor's `MultiStepTrial`
  workload plus aws-bench's AWS lifecycle, composed by MRO), the
  `TransientResetRetryMixin` both concrete trials carry, and `CdktnTrial`, the
  factory that dispatches on `task.has_steps`.
- `cdktn_bench.aws_transient` — the TRANSIENT/RESOLVED classification and the
  reset backoff bounds.
- `cdktn_bench.queue` — `CdktnTrialQueue`, `AwsBenchTrialQueue` with the trial
  factory re-pointed at `CdktnTrial`.
- `cdktn_bench.job` — `CdktnBenchJob`, `AwsBenchJob` with the queue re-pointed
  at `CdktnTrialQueue`.
- `cdktn_bench.cli` — the `cdktn-bench` console script: aws-bench's own Typer
  commands, wired to `CdktnBenchJob`.

Design record: `docs/design/multistep-trial-investigation.md` (the composition
seam) and `DECISIONS.md` Amendment 26.

## CLI seam

`cdktn-bench` is a superset of `aws-bench`, not a multi-step-only side door: a
stepless task runs the identical single-step path (`CdktnSingleStepTrial`,
which is `AwsBenchSingleStepTrial` plus the reset retry below and nothing
else), a `[[steps]]` task runs `CdktnMultiStepTrial`. Gates and equipping therefore
have exactly one command to reason about. `aws-bench` stays installed,
importable, and unchanged; `scripts/run-bench.sh` execs `cdktn-bench`
(DECISIONS.md Amendment 27 §7).

`aws_bench.cli.jobs.start` is ~500 lines of flag declarations, config-file
loading, dataset resolution, preflight, ledger wiring, verification and result
printing. `cdktn_bench.cli` registers *the same function object* on its own
Typer app, so flag parity is total by construction rather than by maintenance.

`start` resolves its job class from the module global `AwsBenchJob` in
`aws_bench.cli.jobs`, and neither aws-bench nor Harbor offers an injection
point. `install_job_class` rebinds that one name before the app is built;
Python resolves module globals at call time, so the rebind takes effect for
every later `start`. That is a monkeypatch, so it is kept guarded (it refuses
to run if the symbol is missing or is not the class expected — an upstream
rename fails loudly at import instead of silently running single-step-only
jobs), idempotent, process-local (importing `aws_bench.cli.main` never imports
`cdktn_bench`, so the `aws-bench` console script is untouched), and tested by
`cdktn_bench/tests/test_cli_wiring.py`.

Nothing in this package may modify `aws_bench` or `harbor` source; this rebind
is the one deliberate exception and is confined to `cdktn_bench.cli`.

## Trial composition (MRO)

Rather than build a multi-step engine (Harbor ships one at
`harbor/trial/multi_step.py`) or vendor aws-bench's ~450 lines of STS /
credential-file / account-reset code, the two are composed by multiple
inheritance:

    class CdktnMultiStepTrial(
        TransientResetRetryMixin, MultiStepTrial, AwsBenchSingleStepTrial
    )

C3 linearises that to:

    CdktnMultiStepTrial -> TransientResetRetryMixin -> MultiStepTrial
                        -> AwsBenchSingleStepTrial -> SingleStepTrial
                        -> Trial -> ABC -> object

which resolves each method to the class that should own it. The table is
asserted by `cdktn_bench/tests/test_trial_mro.py`, not merely documented here:

| Method | Resolves to |
| --- | --- |
| `_run` / `_run_step*` | `MultiStepTrial` — the multi-step workload |
| `run` | `AwsBenchSingleStepTrial` — log context plus post-trial scenario reset |
| `_prepare` | `AwsBenchSingleStepTrial` — contamination check, placeholder seed, task-level pre-invoke; runs **once**, before all steps |
| `_run_agent_phase` | `AwsBenchSingleStepTrial` — placeholder substitution plus staged agent creds, **per step** |
| `_run_shared_verifier` | `AwsBenchSingleStepTrial` — staged verifier creds, per step |
| `_stop_agent_environment` | `AwsBenchSingleStepTrial` — post-invoke teardown, once |
| `_init_logger` / `_setup_agent_environment` | `AwsBenchSingleStepTrial` |
| `_reset_scenario_account` | `TransientResetRetryMixin` — the reset retry below |

Zero-argument `super()` inside the inherited aws-bench methods still resolves
correctly, because it walks the *instance's* MRO, not the defining class's
bases.

Three deliberate overrides beyond the MRO:

1. `__init__` — both `SingleStepTrial.__init__` and `MultiStepTrial`'s parent
   chain would run guards that contradict each other for a steps task
   (`SingleStepTrial` raises on `has_steps`). The override sets the pre-`super()`
   state both classes establish and then calls `Trial.__init__` directly.
2. `_recover_outputs` — the MRO would give `MultiStepTrial`'s, which stops the
   environment inside the *cancel* path (a multi-minute post-invoke reset that
   strands Ctrl-C). aws-bench defers that to `_finalize`; the override
   re-asserts those semantics.
3. `_prepare_step` — the credentialed per-step harness hook
   (`_run_step_pre_invoke`), which is the concrete answer to the "per-step
   pre/post-invoke credentialing is undefined" objection upstream raises when
   it refuses multi-step AWS tasks.

Plus one scoring override: `_select_multi_step_reward` defaults to `final`
rather than Harbor's `mean` (DECISIONS.md Amendment 26).

## Post-trial reset retry

`TransientResetRetryMixin` is mixed in ahead of `AwsBenchSingleStepTrial` on
both concrete trials — `CdktnSingleStepTrial` (a stepless task) and
`CdktnMultiStepTrial` — so a stepless task now runs upstream's single-step
path plus this one override and nothing else.

The rule: **a reset that AWS never answered is re-run; a reset AWS refused is
not.** The failure text is classified by `cdktn_bench/aws_transient.py` —
TRANSIENT (read/connect timeout, connection reset, throttling, 5xx) or RESOLVED
(`AccessDenied`, a stack that cannot be deleted, anything the service actually
answered). A timeout the HARNESS imposed — `PhaseTimeoutError` for a reset
phase, a stack-deletion deadline — is RESOLVED, matched on the exception type:
it is a deterministic verdict, and re-running it spends another 7-13 minute
reset pass to earn the identical answer.

Only TRANSIENT is retried, at most `MAX_RESET_ATTEMPTS` times and only while
`MAX_RESET_RETRY_WALL_S` of budget is left — a clock that starts before attempt
1 and counts each attempt's own duration, because a reset pass is minutes long
and counting only the sleeps between attempts would bound nothing an operator
waits on. The honest bound on added delay is therefore one budget plus the pass
already running when it runs out.

Every attempt logs its classification: INFO while retrying, ERROR for the last
one, so an operator at the default level still learns why the reset was given
up on. A pass that RAISED ends at upstream's `Post-trial reset raised` error,
not at the contamination message — tags are applied inside a pass, so a pass
that raised before that point left the account unflagged and claiming otherwise
would be false.

Contamination is upstream's and is not re-implemented: aws-bench flags the
account inside each reset pass (`ScenarioTrial._apply_contamination_tags` marks
on failure, clears on success), so a retry that succeeds clears the flag its
predecessor set, and a reset that reports failure ends at the same
operator-facing error as before. Attempt 1 keeps upstream's `scenario-reset`
trial name so its artifacts land where every existing tool reads them; a retry
appends its attempt number rather than overwriting the evidence. Both names
start with `RESET_TRIAL_NAME_PREFIX`, which is what `metrics/extract_signals.py`
matches to keep reset artifacts out of the per-trial rows.

Asserted by `cdktn_bench/tests/test_reset_retry.py`; the classifier is held
identical to the container-side `tests/_live_lib.py` table by
`cdktn_bench/tests/test_transient_classifier.py`.

## Queue override

`AwsBenchTrialQueue` owns two things: the per-scenario readers-writer admission
gate (`_run_trial`) and the retry loop (`_execute_trial_with_retries`). The
gate is kept verbatim by inheritance — it is what guarantees one mutating trial
per AWS account at a time, and multi-step changes nothing about it. Only the
retry loop is overridden, and its single cdktn-relevant line is which factory
builds the trial:

    upstream:  trial = await AwsBenchTrial.create(trial_config)   # refuses [[steps]]
    here:      trial = await CdktnTrial.create(trial_config)      # dispatches on has_steps

Upstream reads `AwsBenchTrial` as a module global inside its own loop body
(`aws_bench/task/queue.py`), and neither Harbor's `TrialQueue` nor
`AwsBenchTrialQueue` exposes a factory hook. The alternatives were rebinding
`aws_bench.task.queue.AwsBenchTrial` (a process-global mutation of upstream,
invisible at the call site) or copying the whole queue. The override is the
smallest honest seam. Because a hand-mirrored copy that nothing compares
against would silently keep running the previous release's retry semantics
after an aws-bench bump, `cdktn_bench/tests/test_queue_drift.py` diffs it
against upstream's own normalized source, and
`cdktn_bench/tests/test_dispatch.py` exercises the dispatch.
