"""CdktnMultiStepTrial — Harbor's multi-step workload + aws-bench's AWS lifecycle.

Seam A of ``docs/design/multistep-trial-investigation.md``: rather than build a
multi-step engine (Harbor already ships a complete one at
``harbor/trial/multi_step.py``) or vendor aws-bench's ~450 lines of STS /
credential-file / account-reset code, compose the two by multiple inheritance.

    class CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial)

C3 linearises that to::

    CdktnMultiStepTrial -> MultiStepTrial -> AwsBenchSingleStepTrial
                        -> SingleStepTrial -> Trial -> ABC -> object

which resolves each method to the class that should own it (asserted by
``cdktn_bench/tests/test_trial_mro.py``, not merely asserted here):

===============================  ==============================================
Method                           Resolves to
===============================  ==============================================
``_run`` / ``_run_step*``        ``MultiStepTrial`` — the multi-step workload
``run``                          ``AwsBenchSingleStepTrial`` — log context +
                                 post-trial scenario reset
``_prepare``                     ``AwsBenchSingleStepTrial`` — contamination
                                 check, placeholder seed, task-level pre-invoke;
                                 runs **once**, before all steps
``_run_agent_phase``             ``AwsBenchSingleStepTrial`` — placeholder
                                 substitution + staged agent creds, **per step**
``_run_shared_verifier``         ``AwsBenchSingleStepTrial`` — staged verifier
                                 creds, per step
``_stop_agent_environment``      ``AwsBenchSingleStepTrial`` — post-invoke
                                 teardown, once
``_init_logger`` /
``_setup_agent_environment``     ``AwsBenchSingleStepTrial``
===============================  ==============================================

Zero-argument ``super()`` inside the inherited aws-bench methods still resolves
correctly, because it walks the *instance's* MRO, not the defining class's bases.

Three deliberate overrides beyond the MRO:

1. ``__init__`` — both ``SingleStepTrial.__init__`` and ``MultiStepTrial``'s
   parent chain would run guards that contradict each other for a steps task
   (``SingleStepTrial`` raises on ``has_steps``). We set the pre-``super()``
   state both classes establish and then call ``Trial.__init__`` directly.
2. ``_recover_outputs`` — the MRO would give us ``MultiStepTrial``'s, which
   stops the environment inside the *cancel* path (a multi-minute post-invoke
   reset that strands Ctrl-C). aws-bench deliberately defers that to
   ``_finalize``; we re-assert that semantics.
3. ``_prepare_step`` — the credentialed per-step harness hook (see
   ``_run_step_pre_invoke``), which is the concrete answer to the
   "per-step pre/post-invoke credentialing is undefined" objection upstream
   raises when it refuses multi-step AWS tasks.

Plus one scoring override: ``_select_multi_step_reward`` defaults to ``final``
rather than Harbor's ``mean`` (DECISIONS.md Amendment 26 / memo §6.6).
"""

from __future__ import annotations

from aws_bench.account_management.manager import AccountManager
from aws_bench.dataset.models import RoleType, ScriptType
from aws_bench.dataset.task_config import AwsBenchTask
from aws_bench.task.aws_creds import resolve_env_with_creds
from aws_bench.task.aws_trial import (
    PLACEHOLDER_OUTPUT_FILE_NAME,
    AwsBenchSingleStepTrial,
)
from aws_bench.task.script_runner import ScriptRunner
from aws_bench.utils.placeholders import update_placeholder_values
from harbor.models.task.config import MultiStepRewardStrategy, StepConfig
from harbor.models.task.task import Task
from harbor.models.task.verifier_mode import (
    VerifierEnvironmentMode,
    resolve_step_verifier_mode,
)
from harbor.models.trial.config import TrialConfig
from harbor.models.trial.paths import TrialPaths
from harbor.models.trial.result import ExceptionInfo, StepResult
from harbor.models.verifier.result import VerifierResult
from harbor.trial.multi_step import MultiStepTrial
from harbor.trial.trial import Trial
from harbor.utils.scripts import discover_script

__all__ = ["CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY", "CdktnMultiStepTrial", "CdktnTrial"]


# DECISIONS.md Amendment 26 / memo §6.6. Harbor's own default is ``mean``,
# which — combined with the ``min_reward`` abort — scores a trial that failed
# step 1 and never ran step 2 as the mean of the ONE step it ran, potentially
# ABOVE a trial that ran both and failed the second. For a green/not-green
# benchmark the last step's verdict is the trial's verdict.
CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY = MultiStepRewardStrategy.FINAL


class CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial):
    """Multi-step AWS trial: Harbor's step engine under aws-bench's AWS lifecycle."""

    def __init__(self, config: TrialConfig, *, _task: Task | None = None) -> None:
        """Establish both parents' pre-``super()`` state, then bypass both guards.

        ``AwsBenchSingleStepTrial.__init__`` sets four attributes *before*
        calling ``super()`` precisely so teardown paths can read them when setup
        fails early; ``SingleStepTrial.__init__`` sets
        ``_are_artifacts_collected`` after. We set all five, then call
        ``Trial.__init__`` explicitly — skipping ``SingleStepTrial``'s
        "requires a task without [[steps]]" guard (which is exactly backwards
        for us) and ``MultiStepTrial``'s (which we re-assert here instead, so
        the error still fires with our own class name in it).
        """
        # aws_bench/task/aws_trial.py — AwsBenchSingleStepTrial.__init__'s
        # pre-super state.
        self._aws_placeholders: dict[str, dict[str, str]] = {}
        self._aws_post_invoke_done = False
        self._agent_container_started = False
        self._account_manager = AccountManager()
        # harbor/trial/single_step.py — SingleStepTrial.__init__'s post-super
        # state, read by the inherited ``_collect_artifacts``.
        self._are_artifacts_collected = False

        if _task is not None and not _task.has_steps:
            raise ValueError("CdktnMultiStepTrial requires a task with [[steps]].")

        Trial.__init__(self, config, _task=_task)

    # ── scoring ──────────────────────────────────────────────────────────

    def _select_multi_step_reward(self) -> VerifierResult | None:
        """Default the reward strategy to ``final`` instead of Harbor's ``mean``.

        An explicit ``multi_step_reward_strategy`` in ``task.toml`` still wins;
        only the *unset* case changes. See
        ``CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY`` for why.

        Written as an explicit two-branch dispatch rather than defaulting the
        config field and calling ``super()``: ``self.task.config`` outlives this
        method (it is re-read by the oracle agent and by the verifier), so this
        must not mutate it.
        """
        strategy = (
            self.task.config.multi_step_reward_strategy
            or CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY
        )
        if strategy is MultiStepRewardStrategy.FINAL:
            if not self.result.step_results:
                return None
            return self.result.step_results[-1].verifier_result
        return self._aggregate_step_rewards()

    # ── cancellation ─────────────────────────────────────────────────────

    async def _recover_outputs(self) -> None:
        """Salvage agent outputs without stopping the environment.

        Re-asserts ``AwsBenchSingleStepTrial._recover_outputs``'s semantics over
        ``MultiStepTrial``'s: the env stop (and with it a multi-minute
        post-invoke account reset) is deferred to ``_finalize``, which runs
        after ``_emit(CANCEL)``, so Ctrl-C is never stranded behind it.

        Artifacts are NOT collected here — multi-step collects them per step
        (``MultiStepTrial._collect_step_artifacts``), so the single-step
        whole-trial download would write into an already-archived layout.
        """
        await self._sync_agent_output(self.result)

    # ── the per-step harness hook ────────────────────────────────────────

    async def _prepare_step(self, step: StepConfig, step_result: StepResult) -> None:
        """Run this step's credentialed harness action, then Harbor's own prep.

        Ordering: the harness action runs *before* Harbor's workdir upload /
        ``setup.sh`` / healthcheck, because its whole job is to put the account
        into the state this step's prompt assumes — deploy the previous step's
        IaC, inject out-of-band drift, and emit the resulting resource
        identifiers as placeholders that this step's instruction interpolates.
        """
        await self._run_step_pre_invoke(step, step_result)
        if step_result.exception_info is not None:
            # ``MultiStepTrial._run_step`` aborts the step on a recorded
            # exception; don't spend a container upload on a step that is
            # already lost.
            return
        await super()._prepare_step(step, step_result)

    def step_pre_invoke_script_path(self, step_name: str):
        """OS-aware path to ``steps/<name>/pre_invoke/pre_invoke.{sh,bat}``, or None.

        The cdktn extension to Harbor's step layout.
        ``AwsBenchTask.phase_script_path`` cannot serve here: it hardcodes
        ``task_dir / <script_type>``, i.e. only the *task-level* phase script.
        """
        return discover_script(
            self.task.paths.step_dir(step_name) / ScriptType.PRE_INVOKE.value,
            ScriptType.PRE_INVOKE.value,
            task_os=self.task.config.environment.os,
        )

    async def _run_step_pre_invoke(
        self, step: StepConfig, step_result: StepResult
    ) -> None:
        """Run ``steps/<name>/pre_invoke/`` with staged pre-invoke credentials.

        This is the answer to upstream's stated blocker ("per-step pre/post-invoke
        credentialing is undefined"). It reuses aws-bench's own ``ScriptRunner``
        unchanged — that class derives every path from ``script_type.value``
        relative to the ``task_dir`` and ``trial_paths`` it is handed, so
        re-basing both onto the step's directories yields
        ``steps/<name>/pre_invoke/pre_invoke.sh`` on the task side and
        ``<trial>/steps/<name>/pre_invoke/`` on the output side, with no
        upstream change. (aws-bench itself uses the same
        ``TrialPaths(trial_dir=...)`` re-basing trick in ``_run_phase_script``.)

        The *role* is the task-level ``[scenario].pre_invoke_role_name`` and the
        timeout/env come from the task-level ``[pre_invoke]`` section: per-step
        roles are deliberately deferred (memo §7 Q9) — one identity per task,
        for now.

        A failure is recorded on the ``StepResult`` rather than raised, matching
        how ``MultiStepTrial`` treats a failing ``setup.sh``: the step aborts,
        the trial finalizes cleanly, and the harness failure is visible in the
        result rather than as a trial-level crash.
        """
        if self.step_pre_invoke_script_path(step.name) is None:
            return

        self.logger.info("Running step '%s' pre_invoke script", step.name)
        try:
            output = await self._run_step_phase_script(step)
        except Exception as exc:  # recorded on the step; aborts the step, not the trial
            self.logger.exception("Step '%s' pre_invoke failed", step.name)
            step_result.exception_info = ExceptionInfo.from_exception(exc)
            return

        if not output:
            self.logger.debug("No placeholders produced from step '%s' pre-invoke.", step.name)
            return

        # Same reasoning as aws-bench's task-level pre-invoke logging: these are
        # deployed-resource identifiers, never credentials, and logging them
        # makes an unresolved {{...}} visible here rather than as an opaque
        # downstream error.
        self.logger.debug(
            "Got %d placeholder(s) from step '%s' pre-invoke: %s",
            len(output),
            step.name,
            ", ".join(f"{{{{{k}}}}}={v}" for k, v in sorted(output.items())),
        )
        # ``raise_on_override=False`` (upstream's task-level call raises):
        # across steps, re-emitting a key is the EXPECTED pattern — each step's
        # harness action reports the *current* id of a resource it just
        # redeployed or mutated. Later steps win.
        self._aws_placeholders = update_placeholder_values(
            self._aws_placeholders, output, raise_on_override=False
        )

    async def _run_step_phase_script(self, step: StepConfig) -> dict[str, str]:
        """``AwsBenchSingleStepTrial._run_phase_script``, re-based onto one step."""
        phase = self.task.config.pre_invoke
        async with self._staged_credentials(RoleType.PRE_INVOKE) as cred_env:
            override_env = resolve_env_with_creds(
                raw_env=phase.env, placeholders=self._aws_placeholders, creds=cred_env
            )
            runner = ScriptRunner(
                script_type=ScriptType.PRE_INVOKE,
                task_dir=self.task.paths.step_dir(step.name),
                trial_paths=TrialPaths(trial_dir=self.paths.step_dir(step.name)),
                environment=self.agent_environment,
                override_env=override_env,
                timeout_sec=phase.timeout_sec,
                script_logger=self.logger,
            )
            return await runner.run(output_file_name=PLACEHOLDER_OUTPUT_FILE_NAME)


def validate_multi_step_layout(task: AwsBenchTask) -> None:
    """Re-assert aws-bench's separate-verifier ban **per step**.

    ``AwsBenchTask._validate_layout`` bans separate-environment verifiers
    because aws-bench's phase scripts run in the agent container. Multi-step
    resolves the verifier mode per step (``resolve_step_verifier_mode``), so a
    single step declaring ``[steps.verifier].environment`` would tear the agent
    container down mid-trial (``MultiStepTrial._run_step``) and strand every
    later step. Upstream's task-level check cannot see that, so we add it.
    """
    for step in task.config.steps or []:
        if (
            resolve_step_verifier_mode(task.config, step)
            == VerifierEnvironmentMode.SEPARATE
        ):
            raise ValueError(
                f"{task.paths.task_dir}: step {step.name!r} declares a "
                "separate-environment verifier; cdktn-bench multi-step trials "
                "require shared-environment verifiers for every step (aws-bench "
                "phase scripts run in the agent container)."
            )


class CdktnTrial:
    """Factory: dispatch on ``task.has_steps``.

    A stepless task takes the **untouched** upstream path and returns an
    ``AwsBenchSingleStepTrial``; a ``[[steps]]`` task — which upstream's own
    ``AwsBenchTrial.create`` refuses outright with ``NotImplementedError`` —
    returns a ``CdktnMultiStepTrial``.
    """

    @classmethod
    async def create(cls, config: TrialConfig):
        """Build the concrete trial for ``config``."""
        task = await AwsBenchTask.from_config(
            config.task, config.extra_instruction_paths
        )
        if task.has_steps:
            validate_multi_step_layout(task)
            return CdktnMultiStepTrial(config, _task=task)
        return AwsBenchSingleStepTrial(config, _task=task)
