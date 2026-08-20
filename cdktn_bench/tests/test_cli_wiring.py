"""The CLI seam, and the guard that makes it safe to keep.

``cdktn_bench.cli`` rebinds one module global — ``aws_bench.cli.jobs.AwsBenchJob``
— so aws-bench's own ~500-line ``start`` command builds a ``CdktnBenchJob``.
That buys total, permanent flag parity for one line, but it is a monkeypatch,
so the memo (§2, sub-option A1) asks for exactly what is tested here: that the
symbol exists, that it is what we think it is, and that the rebind happened.
"""

from __future__ import annotations

import types

import aws_bench.cli.jobs as aws_jobs
import aws_bench.cli.main as aws_main
import pytest
from aws_bench.task.job import AwsBenchJob
from typer.main import get_command

from cdktn_bench import cli as cdktn_cli
from cdktn_bench.job import CdktnBenchJob
from cdktn_bench.queue import CdktnTrialQueue


def test_upstream_start_still_reads_the_symbol_we_rebind() -> None:
    """If aws-bench stops resolving its job class from this module global, the
    seam is dead and this test is the thing that says so."""
    assert hasattr(aws_jobs, "AwsBenchJob")
    source = __import__("inspect").getsource(aws_jobs.start)
    assert "AwsBenchJob.create(config)" in source, (
        "aws_bench.cli.jobs.start no longer builds its job via the module-global "
        "AwsBenchJob; cdktn_bench.cli's rebind seam needs revisiting."
    )


def test_importing_the_cli_installs_the_cdktn_job() -> None:
    assert aws_jobs.AwsBenchJob is CdktnBenchJob


def test_install_is_idempotent() -> None:
    cdktn_cli.install_job_class()
    cdktn_cli.install_job_class()
    assert aws_jobs.AwsBenchJob is CdktnBenchJob


def test_install_refuses_an_unrecognised_symbol() -> None:
    module = types.ModuleType("fake_jobs")
    module.AwsBenchJob = object  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="refusing to rebind"):
        cdktn_cli.install_job_class(module=module)


def test_install_refuses_a_missing_symbol() -> None:
    module = types.ModuleType("fake_jobs")
    with pytest.raises(RuntimeError, match="no 'AwsBenchJob' symbol"):
        cdktn_cli.install_job_class(module=module)


def test_install_refuses_a_non_aws_bench_job_class() -> None:
    module = types.ModuleType("fake_jobs")
    module.AwsBenchJob = AwsBenchJob  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="not an AwsBenchJob subclass"):
        cdktn_cli.install_job_class(job_cls=int, module=module)  # type: ignore[arg-type]


def test_the_aws_bench_console_script_is_not_affected() -> None:
    """``aws-bench`` stays installed and importable, its own CLI unchanged.

    ``scripts/run-bench.sh`` execs ``cdktn-bench`` as of DECISIONS.md Amendment
    27 §7, so this is no longer about protecting the runner's own entrypoint —
    it is about keeping the rebind process-local. Importing
    ``aws_bench.cli.main`` never imports ``cdktn_bench``, so an ``aws-bench``
    process (anything else on this machine, `aws-bench env init/setup/cleanup`
    included) never sees it.
    """
    source = __import__("inspect").getsource(aws_main)
    assert "cdktn" not in source.lower()


def test_commands_are_the_same_function_objects_as_aws_bench() -> None:
    """Reuse, not a fork: same callables, therefore identical flags forever."""
    assert cdktn_cli.start is aws_jobs.start
    assert cdktn_cli.view is __import__(
        "aws_bench.cli.view", fromlist=["view"]
    ).view
    assert cdktn_cli.jobs_app is aws_jobs.jobs_app


def test_app_exposes_the_expected_commands() -> None:
    command = get_command(cdktn_cli.app)
    names = set(command.commands)  # type: ignore[attr-defined]
    assert {"run", "view", "job", "env"} <= names


def test_job_installs_the_cdktn_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CdktnBenchJob.__init__`` swaps in ``CdktnTrialQueue``, carrying hooks.

    ``AwsBenchJob.__init__`` is stubbed because the real one runs Harbor's
    whole ``Job.__init__`` (resolved datasets, metrics, trial configs); what is
    under test is only our override, and it must (a) call super, (b) replace
    the queue, (c) preserve the hooks the base wired.
    """
    sentinel_hooks = {"marker": []}

    class _BaseQueue:
        _hooks = sentinel_hooks

    def _fake_init(self, config, **kwargs):
        self.config = config
        self._trial_queue = _BaseQueue()

    monkeypatch.setattr(AwsBenchJob, "__init__", _fake_init)

    class _Config:
        n_concurrent_trials = 3
        retry = None

    job = CdktnBenchJob(_Config())  # type: ignore[arg-type]
    assert isinstance(job._trial_queue, CdktnTrialQueue)
    assert job._trial_queue._n_concurrent == 3
    assert job._trial_queue._hooks["marker"] is sentinel_hooks["marker"]
