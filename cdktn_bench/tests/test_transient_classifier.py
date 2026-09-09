"""The host-side and container-side transient tables must not drift apart.

The classification exists twice on purpose: `cdktn_bench/aws_transient.py`
runs on the host inside the post-trial reset, and the generated
`tests/_live_lib.py` runs inside an arm image that ships python3 without this
package. A marker added to one and not the other means the same AWS failure is
retried in one place and turned into a 0.0 in the other, silently.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from cdktn_bench import aws_transient

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "generator"))
from gen import LIVE_LIB_PY  # noqa: E402


def _live_lib(tmp_path: Path):
    path = tmp_path / "_live_lib.py"
    path.write_text(LIVE_LIB_PY)
    spec = importlib.util.spec_from_file_location("_live_lib_drift", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_two_marker_tables_are_identical(tmp_path: Path) -> None:
    assert aws_transient.TRANSIENT_MARKERS == _live_lib(tmp_path).TRANSIENT_MARKERS


def test_the_two_classifiers_agree_on_every_marker(tmp_path: Path) -> None:
    lib = _live_lib(tmp_path)
    for text in (*aws_transient.TRANSIENT_MARKERS, "AccessDenied", "ValidationException", ""):
        assert aws_transient.classify(text) == lib.classify(text), text


def test_the_class_names_are_shared(tmp_path: Path) -> None:
    lib = _live_lib(tmp_path)
    assert (aws_transient.TRANSIENT, aws_transient.RESOLVED) == (lib.TRANSIENT, lib.RESOLVED)
