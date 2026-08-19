"""The ``cdktn-bench`` console script — one CLI for both task shapes.

Design decision (memo §7 Q7, answered "route everything through the new CLI"):
``cdktn-bench`` is a **superset** of ``aws-bench``, not a multi-step-only side
door. A stepless task runs through the identical single-step path
(``AwsBenchSingleStepTrial``); a ``[[steps]]`` task runs through
``CdktnMultiStepTrial``. Gates and equipping therefore have exactly one command
to reason about. ``aws-bench`` itself keeps working, unchanged and unaffected —
``scripts/run-bench.sh`` still calls it.

**How the commands are reused.** ``aws_bench.cli.jobs.start`` is ~500 lines of
flag declarations, config-file loading, dataset resolution, preflight, ledger
wiring, verification, and result printing. Forking it would fork all of that.
Instead this module registers *the very same function object* on its own Typer
app, so flag parity is total and permanent by construction.

**The one seam.** ``start`` resolves its job class from the module global
``AwsBenchJob`` in ``aws_bench.cli.jobs``, and neither aws-bench nor Harbor
offers an injection point for it. ``install_job_class`` rebinds that one name
before the app is built. Python resolves module globals at call time, so the
rebind takes effect for every later ``start`` invocation.

This is a rebind of an import binding, not a patched method — but it *is* a
monkeypatch, so it is:

- **guarded** — ``install_job_class`` refuses to run if the symbol is missing or
  is not the class we expect (an upstream rename fails loudly at import instead
  of silently running single-step-only jobs);
- **idempotent** — re-installing the same class is a no-op;
- **process-local** — importing ``aws_bench.cli.main`` never imports
  ``cdktn_bench``, so the ``aws-bench`` console script is untouched;
- **tested** — ``cdktn_bench/tests/test_cli_wiring.py``.
"""

from __future__ import annotations

import types

import aws_bench.cli.jobs as aws_jobs
from aws_bench.cli.env import env_app
from aws_bench.cli.jobs import jobs_app, start
from aws_bench.cli.main import _root
from aws_bench.cli.view import view
from aws_bench.task.job import AwsBenchJob
from typer import Typer

from cdktn_bench.job import CdktnBenchJob

__all__ = ["app", "install_job_class", "main"]

#: The upstream module global ``aws_bench.cli.jobs.start`` reads to build the
#: job (``job = await AwsBenchJob.create(config)``).
_JOB_SYMBOL = "AwsBenchJob"


def install_job_class(
    job_cls: type = CdktnBenchJob, module: types.ModuleType = aws_jobs
) -> type:
    """Point ``aws_bench.cli.jobs``'s job factory at ``job_cls``; return the old one.

    Raises:
        RuntimeError: if ``module`` has no ``AwsBenchJob`` symbol, or it is
            neither upstream's ``AwsBenchJob`` nor already ``job_cls``. Both
            cases mean an upstream change has invalidated this seam, and
            failing here is strictly better than shipping a cdktn-bench run
            that silently refuses every multi-step task.
    """
    current = getattr(module, _JOB_SYMBOL, None)
    if current is None:
        raise RuntimeError(
            f"{module.__name__} has no {_JOB_SYMBOL!r} symbol; the cdktn-bench CLI "
            "seam (see this module's docstring) no longer matches aws-bench. "
            "Re-check aws_bench/cli/jobs.py's job construction."
        )
    if current is not AwsBenchJob and current is not job_cls:
        raise RuntimeError(
            f"{module.__name__}.{_JOB_SYMBOL} is {current!r}, expected "
            f"{AwsBenchJob!r} or {job_cls!r}; refusing to rebind a symbol we do "
            "not recognise."
        )
    if not issubclass(job_cls, AwsBenchJob):
        # RuntimeError, not TypeError (ruff TRY004): all three raises in this
        # guard mean one thing — "the CLI seam is not what it must be" — and a
        # caller should catch them as one.
        raise RuntimeError(f"{job_cls!r} is not an AwsBenchJob subclass.")  # noqa: TRY004
    setattr(module, _JOB_SYMBOL, job_cls)
    return current


install_job_class()


app = Typer(
    name="cdktn-bench",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "cdktn-bench extends aws-bench with multi-step trials (workspace -> "
        "prompt #1 -> agent -> harness deploy/drift -> prompt #2 -> agent -> "
        "final eval). Every aws-bench flag works unchanged; a task whose "
        "task.toml declares a steps array runs as a multi-step trial instead "
        "of being refused."
    ),
)

# The root callback aws-bench installs: SIGINT/SIGTERM handlers plus the
# command ledger (open on entry, finalize on close). Registered here as the
# same function object, so a cdktn-bench invocation leaves the identical
# ledger record shape an aws-bench one does.
app.callback()(_root)

app.add_typer(jobs_app, name="job", help="Manage jobs.")
app.add_typer(env_app, name="env", help="Manage the testing environment.")

app.command(
    name="run",
    help="Run benchmark trials (single- or multi-step). Alias for `cdktn-bench job start`.",
)(start)
app.command(name="view", help="Start web server to browse trajectory files.")(view)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    app()
