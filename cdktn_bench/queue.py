"""CdktnTrialQueue — AwsBenchTrialQueue with the trial factory re-pointed.

``AwsBenchTrialQueue`` owns two things: the per-scenario readers-writer
admission gate (``_run_trial``) and the retry loop (``_execute_trial_with_retries``).
We keep the gate verbatim by inheritance — it is the piece that guarantees one
mutating trial per AWS account at a time, and nothing about multi-step changes
it — and override only the retry loop, whose single cdktn-relevant line is
which factory builds the trial:

    upstream:  trial = await AwsBenchTrial.create(trial_config)   # refuses [[steps]]
    here:      trial = await CdktnTrial.create(trial_config)      # dispatches on has_steps

Why an override rather than reuse: upstream reads ``AwsBenchTrial`` as a module
global inside its own loop body (``aws_bench/task/queue.py``), and neither
Harbor's ``TrialQueue`` nor ``AwsBenchTrialQueue`` exposes a factory hook. The
alternatives were rebinding ``aws_bench.task.queue.AwsBenchTrial`` (a
process-global mutation of upstream, invisible at the call site) or copying the
whole queue. This override is the smallest honest seam; the loop body below is
a deliberate mirror of upstream's and is covered by
``cdktn_bench/tests/test_queue_dispatch.py``.
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
        from the factory. NOTE (memo §6.8): a retry re-runs the *whole* trial,
        which for a multi-step task means every agent invocation **and** every
        per-step ``pre_invoke`` deploy — retry cost scales with step count.
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
