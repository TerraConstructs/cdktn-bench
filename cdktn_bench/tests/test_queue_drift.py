"""Drift detection for the ONE upstream method cdktn-bench hand-mirrors.

``CdktnTrialQueue._execute_trial_with_retries`` is a deliberate copy of
``AwsBenchTrialQueue._execute_trial_with_retries`` (``aws_bench/task/queue.py``)
with exactly one line changed — upstream reads ``AwsBenchTrial`` as a module
global inside its own loop body and exposes no factory hook, so the retry loop
had to be re-declared to build a ``CdktnTrial`` instead (see
``cdktn_bench/queue.py``'s module docstring for why that beat the alternatives).

A copy with no drift detection is the failure mode this test exists to prevent:
a bump of the pinned aws-bench rev could change upstream's retry/backoff
behaviour — its exception filter, its ``rmtree`` of the failed trial dir, its
attempt accounting — and our copy would keep quietly running the OLD logic, with
every existing test still green because they all exercise OUR method. Same
spirit as ``test_cli_wiring.py::test_upstream_start_still_reads_the_symbol_we_rebind``:
fail loudly at the seam rather than diverge silently.

The comparison is on NORMALIZED source (``ast.unparse`` of the parsed function
with its docstring dropped), so comments, docstrings, line wrapping and
whitespace are all free to differ — only the executable statements are compared.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from aws_bench.task.queue import AwsBenchTrialQueue

from cdktn_bench.queue import CdktnTrialQueue

#: The single permitted edit, applied to upstream before comparing. If a future
#: aws-bench rev renames or restructures this call, the substitution stops
#: applying and ``test_the_one_permitted_edit_still_applies_upstream`` fails.
UPSTREAM_FACTORY_CALL = "trial = await AwsBenchTrial.create(trial_config)"
CDKTN_FACTORY_CALL = "trial = await self.trial_factory.create(trial_config)"


def _normalized_source(func: object) -> str:
    """Executable source of ``func``, with docstring, comments and formatting
    normalized away (``ast.unparse`` re-emits from the parsed tree)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))  # type: ignore[arg-type]
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)), (
        f"inspect.getsource({func!r}) did not yield a function definition "
        f"(got {type(fn).__name__}) — the source file was most likely edited "
        "after it was imported, so the code object's line numbers no longer "
        "match the file on disk. Re-run in a fresh process."
    )
    if (
        fn.body
        and isinstance(fn.body[0], ast.Expr)
        and isinstance(fn.body[0].value, ast.Constant)
        and isinstance(fn.body[0].value.value, str)
    ):
        fn.body = fn.body[1:]
    return ast.unparse(fn)


def _upstream() -> str:
    return _normalized_source(AwsBenchTrialQueue._execute_trial_with_retries)


def _ours() -> str:
    return _normalized_source(CdktnTrialQueue._execute_trial_with_retries)


def test_the_method_is_genuinely_overridden() -> None:
    """Guards the guard: if the override were dropped, both sides would resolve
    to the same function and every comparison below would pass vacuously."""
    assert "_execute_trial_with_retries" in vars(CdktnTrialQueue)
    assert (
        CdktnTrialQueue._execute_trial_with_retries
        is not AwsBenchTrialQueue._execute_trial_with_retries
    )


def test_the_one_permitted_edit_still_applies_upstream() -> None:
    """Upstream must still contain the exact call we substitute — otherwise the
    'modulo one line' comparison below would be comparing against something we
    no longer understand."""
    assert UPSTREAM_FACTORY_CALL in _upstream(), (
        "aws_bench.task.queue.AwsBenchTrialQueue._execute_trial_with_retries no "
        "longer builds its trial via the module-global AwsBenchTrial; "
        "cdktn_bench/queue.py's mirrored loop needs revisiting."
    )
    assert CDKTN_FACTORY_CALL in _ours()


def test_our_retry_loop_matches_upstream_modulo_the_factory_call() -> None:
    """The drift check itself.

    Fails on ANY upstream change to the retry loop's logic — new retry
    condition, changed backoff call, changed cleanup — so a pinned-rev bump
    cannot silently leave cdktn-bench running the previous release's retry
    semantics.
    """
    expected = _upstream().replace(UPSTREAM_FACTORY_CALL, CDKTN_FACTORY_CALL)
    assert _ours() == expected, (
        "CdktnTrialQueue._execute_trial_with_retries has drifted from "
        "AwsBenchTrialQueue._execute_trial_with_retries (or upstream changed). "
        "Re-mirror the loop, changing ONLY the trial-factory call, then update "
        "this test's substitution if the seam itself moved.\n\n"
        f"--- upstream (with the permitted substitution applied) ---\n{expected}\n"
        f"--- cdktn ---\n{_ours()}"
    )


def test_the_substitution_is_the_only_difference_and_is_load_bearing() -> None:
    """Sanity: the two sides are NOT byte-identical without the substitution —
    i.e. the test above is really comparing a changed line, not asserting a
    tautology."""
    assert _ours() != _upstream()
