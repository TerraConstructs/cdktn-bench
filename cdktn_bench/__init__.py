"""cdktn_bench — the cdktn-bench extension of ``aws_bench``.

Adds exactly one capability upstream ``aws_bench`` refuses: multi-step trials.
Everything else — credential staging, placeholder substitution, scenario
admission gating, account reset, CLI flag parsing, export collection,
contamination checks — is inherited by import, never vendored or copied.

Nothing in this package may modify ``aws_bench`` or ``harbor`` source. The one
deliberate rebind (``aws_bench.cli.jobs.AwsBenchJob``) is documented, guarded,
and confined to ``cdktn_bench.cli``.

Package layout and design record: See docs/runner.md#package-layout.
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
