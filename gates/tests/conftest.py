"""Pytest bootstrap for gates/tests.

Ensures the repo root is on sys.path so tests can ``import gates.audit`` /
``gates.emit_result`` / ``gates.preflight`` regardless of how pytest was
invoked (repo root has no ``[build-system]`` — see pyproject.toml "No
importable Python package of our own (yet)" — so this is a plain sys.path
shim, not a package install).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
ARMS = ("awscdk", "hcl-raw", "terraconstructs")
SCENARIOS = ("genuine", "bypass", "infra-failure")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def task_dir() -> Path:
    """A minimal task_dir (has instruction.md) for equipping-hash tests."""
    return FIXTURES_DIR / "task-dir"


def trial_dir(arm: str, scenario: str) -> Path:
    """Path to gates/tests/fixtures/<arm>/<scenario>/ (a synthetic trial dir)."""
    assert arm in ARMS, arm
    assert scenario in SCENARIOS, scenario
    return FIXTURES_DIR / arm / scenario
