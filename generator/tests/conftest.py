"""Pytest bootstrap for generator/tests.

Ensures both the repo root AND generator/ itself are on sys.path, matching
generator/gen.py's own self-inserting convention (its top-of-file
``sys.path.insert(0, .../generator)`` + ``sys.path.insert(0, REPO_ROOT)``)
and gates/tests/conftest.py's precedent for the same "no [build-system] in
pyproject.toml, so this is a plain sys.path shim" reason: generator/ has no
``__init__.py`` (it is content + scripts, not an importable package), so
without this, ``from generator.split import ...`` / bare ``import gen``
would only work by accident of import order (whichever module happens to
be imported first and does its own sys.path surgery, e.g.
gates.oracle_falsifiability importing gen.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR_DIR = REPO_ROOT / "generator"

for _p in (GENERATOR_DIR, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
