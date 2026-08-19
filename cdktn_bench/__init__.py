"""cdktn_bench — the cdktn-bench extension of ``aws_bench``.

This package adds exactly one capability that upstream ``aws_bench`` refuses
(``aws_bench/task/aws_trial.py``'s ``AwsBenchTrial.create``: *"multi-step AWS
tasks are not yet supported (per-step pre/post-invoke credentialing is
undefined)"*): **multi-step trials**. Everything else — credential staging,
placeholder substitution, scenario admission gating, account reset, CLI flag
parsing, export collection, contamination checks — is *inherited by import*,
never vendored or copied.

Layout:

- ``cdktn_bench.trial``  — ``CdktnMultiStepTrial`` (Harbor's ``MultiStepTrial``
  workload + aws-bench's AWS lifecycle, composed by MRO) and ``CdktnTrial``,
  the factory that dispatches on ``task.has_steps``.
- ``cdktn_bench.queue``  — ``CdktnTrialQueue``, ``AwsBenchTrialQueue`` with the
  trial factory re-pointed at ``CdktnTrial``.
- ``cdktn_bench.job``    — ``CdktnBenchJob``, ``AwsBenchJob`` with the queue
  re-pointed at ``CdktnTrialQueue``.
- ``cdktn_bench.cli``    — the ``cdktn-bench`` console script: aws-bench's own
  Typer commands, wired to ``CdktnBenchJob``.

Design record: ``docs/design/multistep-trial-investigation.md`` (Seam A) and
``DECISIONS.md`` Amendment 26.

Nothing in this package may modify ``aws_bench`` or ``harbor`` source. The one
deliberate rebind (``aws_bench.cli.jobs.AwsBenchJob``) is documented, guarded,
and confined to ``cdktn_bench.cli`` — see that module.
"""

from __future__ import annotations

__all__ = [
    "CdktnBenchJob",
    "CdktnMultiStepTrial",
    "CdktnTrial",
    "CdktnTrialQueue",
]


def __getattr__(name: str):
    """Lazily re-export the public classes.

    Kept lazy so ``import cdktn_bench`` does not drag in boto3/docker/Typer for
    a caller that only wants the package metadata.
    """
    if name in ("CdktnMultiStepTrial", "CdktnTrial"):
        from cdktn_bench import trial

        return getattr(trial, name)
    if name == "CdktnTrialQueue":
        from cdktn_bench.queue import CdktnTrialQueue

        return CdktnTrialQueue
    if name == "CdktnBenchJob":
        from cdktn_bench.job import CdktnBenchJob

        return CdktnBenchJob
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
