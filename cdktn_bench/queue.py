"""CdktnTrialQueue — AwsBenchTrialQueue with the trial factory re-pointed.

``AwsBenchTrialQueue``'s per-scenario admission gate (``_run_trial``) is kept
verbatim by inheritance: it is what guarantees one mutating trial per AWS
account at a time. Only ``_execute_trial_with_retries`` is overridden, and only
to build a ``CdktnTrial`` (which dispatches on ``has_steps``) instead of an
``AwsBenchTrial`` (which refuses ``[[steps]]``).

The loop body below is a deliberate mirror of upstream's, so it is diffed
against upstream's own normalized source by
``cdktn_bench/tests/test_queue_drift.py`` — otherwise an aws-bench bump would
leave this copy quietly running the previous release's retry semantics.

Why an override rather than a factory hook: See docs/runner.md#queue-override.
"""

from __future__ import annotations

import asyncio
import shutil

from aws_bench.task.queue import AwsBenchTrialQueue
from harbor.models.trial.config import TrialConfig
from harbor.models.trial.result import TrialResult

from cdktn_bench.trial import CdktnTrial

__all__ = ["CdktnTrialQueue"]


class CdktnTrialQueue(AwsBenchTrialQueue):
    """aws-bench's scenario-gated queue, building cdktn trials."""

    #: The factory each retry attempt builds its trial from. Exposed as a class
    #: attribute so a test can assert the dispatch without running a trial.
    trial_factory = CdktnTrial

    async def _execute_trial_with_retries(
        self, trial_config: TrialConfig
    ) -> TrialResult:
        """Run the retry loop, rebuilding ``CdktnTrial`` for each attempt.

        Mirrors ``AwsBenchTrialQueue._execute_trial_with_retries`` exactly apart
        from the factory. A retry re-runs the *whole* trial, so for a multi-step
        task it repeats every agent invocation **and** every per-step
        ``pre_invoke`` deploy — retry cost scales with step count.
        """
        for attempt in range(self._retry_config.max_retries + 1):
            trial = await self.trial_factory.create(trial_config)
            self._setup_hooks(trial)
            result = await trial.run()

            if result.exception_info is None:
                return result

            if not self._should_retry_exception(result.exception_info.exception_type):
                self._logger.debug(
                    "Not retrying trial because the exception is not in "
                    "include_exceptions or the maximum number of retries has been reached"
                )
                return result
            if attempt == self._retry_config.max_retries:
                self._logger.debug(
                    "Not retrying trial because the maximum number of retries has been reached"
                )
                return result

            shutil.rmtree(trial.paths.trial_dir, ignore_errors=True)
            delay_sec = self._calculate_backoff_delay_sec(attempt)
            self._logger.debug(
                f"Trial {trial_config.trial_name} failed with exception "
                f"{result.exception_info.exception_type}. Retrying in {delay_sec:.2f} seconds..."
            )
            await asyncio.sleep(delay_sec)

        raise RuntimeError(
            f"Trial {trial_config.trial_name} produced no result. This should never happen."
        )
