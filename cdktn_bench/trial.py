"""CdktnMultiStepTrial — Harbor's multi-step workload + aws-bench's AWS lifecycle.

Composed by multiple inheritance rather than by building a second multi-step
engine or vendoring aws-bench's AWS lifecycle code::

    class CdktnMultiStepTrial(MultiStepTrial, AwsBenchSingleStepTrial)

The MRO resolves the step engine to Harbor and every credentialed AWS phase to
aws-bench. That resolution is a contract, asserted by
``cdktn_bench/tests/test_trial_mro.py`` rather than assumed here.

Beyond the MRO there are three deliberate overrides (``__init__``,
``_recover_outputs``, ``_prepare_step``) and one scoring override
(``_select_multi_step_reward``, defaulting to ``final`` rather than Harbor's
``mean`` — DECISIONS.md Amendment 26). Each carries its own docstring below.

Full method-ownership table and the reason for each override:
See docs/runner.md#trial-composition-mro.
"""

from __future__ import annotations

import asyncio
import logging
import time

from aws_bench.account_management.manager import AccountManager
from aws_bench.dataset.models import RoleType, ScriptType
from aws_bench.dataset.task_config import AwsBenchTask
from aws_bench.exceptions import OperationCancelled
from aws_bench.scenario.events import ScenarioPhase
from aws_bench.scenario.job_config import ScenarioTrialConfig
from aws_bench.scenario.trial import ScenarioTrial
from aws_bench.task.aws_creds import resolve_env_with_creds
from aws_bench.task.aws_trial import (
    PLACEHOLDER_OUTPUT_FILE_NAME,
    AwsBenchSingleStepTrial,
)
from aws_bench.task.script_runner import ScriptRunner
from aws_bench.utils.credentials_provider import CredentialProvider
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

from cdktn_bench.aws_transient import (
    MAX_RESET_ATTEMPTS,
    MAX_RESET_RETRY_WALL_S,
    TRANSIENT,
    classify,
    reset_backoff_delays,
)

__all__ = [
    "CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY",
    "RESET_TRIAL_NAME_PREFIX",
    "CdktnMultiStepTrial",
    "CdktnSingleStepTrial",
    "CdktnTrial",
    "TransientResetRetryMixin",
]


# For a green/not-green benchmark the last step's verdict is the trial's
# verdict (DECISIONS.md Amendment 26). Harbor's ``mean`` default, combined with
# the ``min_reward`` abort, would score a trial that failed step 1 and never
# ran step 2 as the mean of the ONE step it ran — potentially ABOVE a trial
# that ran both and failed the second.
CDKTN_DEFAULT_MULTI_STEP_REWARD_STRATEGY = MultiStepRewardStrategy.FINAL


# Every post-trial reset artifact directory starts with this; a retry appends
# its attempt number. Tools that must tell reset artifacts apart from agent
# trials (metrics/extract_signals.py) match the prefix, not the bare name.
RESET_TRIAL_NAME_PREFIX = "scenario-reset"

# Which of upstream's two failure endings one reset pass reached. Only a
# reported failure flags the account; a pass that raised may not have.
RESET_RAISED = "raised"
RESET_REPORTED = "reported"


class TransientResetRetryMixin:
    """Retry a post-trial account reset that AWS never actually answered.

    A reset whose failure text carries a transient signature — a read/connect
    timeout, a connection reset, throttling, a 5xx — is re-run with bounded
    backoff before the outcome is accepted. A resolved failure (AccessDenied, a
    stack that cannot be deleted, anything the service answered) is never
    retried: re-asking holds the scenario's exclusive gate for minutes to reach
    the same answer.

    Contamination semantics are upstream's, untouched. aws-bench flags the
    account inside each reset pass (``ScenarioTrial._apply_contamination_tags``
    marks on failure and clears on success), so a retry that succeeds clears
    the flag its predecessor set, and a reset that genuinely fails leaves the
    account flagged exactly as it does today.

    Mixed in ahead of ``AwsBenchSingleStepTrial`` so its
    ``_reset_scenario_account`` is the one ``run()`` reaches.
    """

    async def _reset_scenario_account(self) -> None:
        """aws-bench's post-trial reset, wrapped in a transient-only retry.

        The budget is attempts and wall clock measured across whole attempts:
        a reset pass is minutes long, so a clock that counted only the sleeps
        between attempts would bound nothing an operator waits on.

        Never raises: a reset must not fail a finished benchmark. Only
        cancellation propagates, out of the attempt itself.
        """
        delays = reset_backoff_delays()
        started = time.monotonic()
        kind, failure = RESET_REPORTED, "no reset attempt was made"
        for attempt in range(1, MAX_RESET_ATTEMPTS + 1):
            outcome = await self._attempt_scenario_reset(attempt)
            if outcome is None:
                return
            kind, failure = outcome
            verdict = classify(failure)
            delay = next(delays, None)
            final = (
                verdict != TRANSIENT
                or delay is None
                or (time.monotonic() - started) + delay > MAX_RESET_RETRY_WALL_S
            )
            # The last attempt's reason is the only account of the failure an
            # operator running at WARNING sees, so it is logged at ERROR.
            self.logger.log(
                logging.ERROR if final else logging.INFO,
                "Post-trial reset attempt %d/%d for %s failed, classified %s: %s",
                attempt,
                MAX_RESET_ATTEMPTS,
                self.config.scenario_id,
                verdict,
                failure,
            )
            if final:
                break
            await asyncio.sleep(delay)

        # Upstream's two distinct endings, kept distinct. Contamination tags are
        # applied inside a reset pass, so a pass that raised before that point
        # left the account unflagged: telling the operator it is flagged would
        # be false, and the exception text would be the only thing that says so.
        if kind == RESET_RAISED:
            self.logger.error(
                "Post-trial reset raised for %s: %s", self.config.scenario_id, failure
            )
            return
        self.logger.error(
            "Post-trial reset did not restore %s; the account is flagged "
            "contaminated and later trials will be refused. Run "
            "'aws-bench env cleanup' to clean it and clear the flag.",
            self.config.scenario_id,
        )

    async def _attempt_scenario_reset(self, attempt: int) -> tuple[str, str] | None:
        """One reset pass: ``None`` on success, else ``(kind, failure text)``.

        ``kind`` separates a pass that raised from one that reported failure,
        because only the second flags the account.

        Attempt 1 keeps upstream's ``scenario-reset`` trial name, so the
        artifacts land in the ``<trial_dir>/scenario-reset/`` directory every
        existing tool reads; a retry gets its own name rather than overwriting
        the evidence of why the first attempt failed. Both start with
        ``RESET_TRIAL_NAME_PREFIX``.
        """
        reset_config = ScenarioTrialConfig(
            scenario=self.config.scenario,
            output_dir=self.paths.trial_dir,
            trial_name=(
                RESET_TRIAL_NAME_PREFIX
                if attempt == 1
                else f"{RESET_TRIAL_NAME_PREFIX}-retry-{attempt}"
            ),
            account_mapping=self.config.account_mapping,
            timeout_multiplier=self.config.timeout_multiplier,
        )
        try:
            trial = await ScenarioTrial.create(reset_config, CredentialProvider.get())
            reset_result = await trial.run(ScenarioPhase.RESET)
        except (asyncio.CancelledError, OperationCancelled):
            raise
        except Exception as exc:  # noqa: BLE001 — reset must not fail a finished benchmark
            return RESET_RAISED, f"{type(exc).__name__}: {exc}"
        if reset_result.success:
            return None
        info = reset_result.exception_info
        if info is None:
            return RESET_REPORTED, f"reset reported failure with exit code {reset_result.exit_code}"
        return RESET_REPORTED, f"{info.exception_type}: {info.exception_message}"


class CdktnSingleStepTrial(TransientResetRetryMixin, AwsBenchSingleStepTrial):
    """Upstream's single-step AWS trial with the reset retry, and nothing else."""


class CdktnMultiStepTrial(TransientResetRetryMixin, MultiStepTrial, AwsBenchSingleStepTrial):
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
        roles are deliberately deferred — one identity per task, for now.

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

    A stepless task returns a ``CdktnSingleStepTrial`` — upstream's own
    single-step trial plus the transient reset retry, and nothing else; a
    ``[[steps]]`` task — which upstream's own ``AwsBenchTrial.create`` refuses
    outright with ``NotImplementedError`` — returns a ``CdktnMultiStepTrial``.
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
        return CdktnSingleStepTrial(config, _task=task)
