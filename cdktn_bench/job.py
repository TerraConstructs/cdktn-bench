"""CdktnBenchJob — AwsBenchJob with the cdktn trial queue installed.

``AwsBenchJob`` resolves tasks, scenarios, accounts and CloudFormation exports
in ``create``, then swaps Harbor's queue for its own in ``__init__``. All of
that is inherited untouched; the single override re-swaps the queue for
``CdktnTrialQueue`` so ``[[steps]]`` tasks reach ``CdktnMultiStepTrial``.

``AwsBenchJob.create`` is a ``classmethod`` that ends in ``cls(...)``, so
``CdktnBenchJob.create(config)`` already returns a ``CdktnBenchJob`` with no
override needed — verified by ``cdktn_bench/tests/test_job_wiring.py``.
"""

from __future__ import annotations

from aws_bench.cli.job_config import AwsBenchJobConfig
from aws_bench.task.job import AwsBenchJob

from cdktn_bench.queue import CdktnTrialQueue

__all__ = ["CdktnBenchJob"]


class CdktnBenchJob(AwsBenchJob):
    """aws-bench's run-side Job, building cdktn trials."""

    def __init__(self, config: AwsBenchJobConfig, **kwargs) -> None:
        """Install ``CdktnTrialQueue``, preserving the hooks the base wired.

        ``super().__init__`` runs Harbor's ``Job.__init__`` (which builds the
        base queue and registers the progress hooks) and then aws-bench's own
        swap to ``AwsBenchTrialQueue``. We replace that queue in turn, carrying
        its ``_hooks`` across exactly as aws-bench carries Harbor's — so the
        progress UI, ledger, and result plumbing stay wired.
        """
        super().__init__(config, **kwargs)
        self._trial_queue = CdktnTrialQueue(
            n_concurrent=self.config.n_concurrent_trials,
            retry_config=self.config.retry,
            hooks=self._trial_queue._hooks,
        )
