"""A live check does not imply a mutating trial.

`[concurrency] mode` describes what a trial does TO the account; a live check
describes what the VERIFIER reads back out of it. A live check built only from
evaluating APIs -- `stepfunctions test-state`, which creates no resource --
leaves the account exactly as it found it, so `read-only` is correct for it and
nothing in the spec model may couple the two (specs/SCHEMA.md §5; DECISIONS.md
Amendment 34). Only `workspace_seed.deploy` forces `"mutating"`, and that rule
is tested next to the seed it belongs to, in test_seed_deploy.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gen import build_task_toml
from spec_model import Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
SFN_JSONATA = REPO_ROOT / "specs" / "sfn-jsonata.yaml"


def test_a_gating_live_check_is_legal_with_read_only_concurrency() -> None:
    spec = load_spec(SFN_JSONATA)
    live = spec.verifier.live_check
    assert (live.enabled, live.gating, live.hand_authored) == (True, True, True)
    assert live.concurrency_mode is None, (
        "sfn-jsonata's live check evaluates via TestState and creates nothing, "
        "so it must stay on the read-only default"
    )


def test_the_emitted_task_toml_stays_read_only_and_still_gates(tmp_path: Path) -> None:
    """The rule as SHIPPED BYTES, not as a model attribute: a read-only task
    that nonetheless hands tests/test.sh the gating switch."""
    spec = load_spec(SFN_JSONATA)
    toml = build_task_toml(spec, "hcl_raw", "00000000-0000-0000-0000-000000000000")
    assert 'mode = "read-only"' in toml
    assert 'SPEC_LIVE_CHECK_ENABLED = "true"' in toml
    assert 'SPEC_LIVE_CHECK_GATING = "true"' in toml


def test_the_read_only_comment_does_not_claim_the_live_check_is_off() -> None:
    """The `[concurrency]` comment is what a reader of task.toml alone believes;
    for a live-checked read-only task it must not say live checking is off."""
    spec = load_spec(SFN_JSONATA)
    toml = build_task_toml(spec, "awscdk", "00000000-0000-0000-0000-000000000000")
    assert "verifier.live_check.enabled\n# is false" not in toml
    assert "verifier.live_check.enabled is true" in toml


def test_turning_a_live_check_on_never_forces_a_concurrency_mode() -> None:
    raw = load_spec(SFN_JSONATA).model_dump(mode="json")
    raw["verifier"]["live_check"]["concurrency_mode"] = "read-only"
    Spec.model_validate(raw)  # must not raise


def test_gating_without_enabled_is_still_rejected() -> None:
    """The one coupling that DOES exist: a check that never runs cannot gate."""
    raw = load_spec(SFN_JSONATA).model_dump(mode="json")
    raw["verifier"]["live_check"].update({"enabled": False, "hand_authored": False})
    with pytest.raises(ValueError, match="gating=true requires enabled=true"):
        Spec.model_validate(raw)
