"""oracles/tests/toolcheck.py

Best-effort local discovery of `opa` and `cfn-guard`, for the small number
of tests that validate an emitted skeleton with the real tool rather than
just asserting on its Python-level content. Neither tool is a hard
dependency of this repo (`pyproject.toml` has no such entry, deliberately —
these are developer-machine conveniences, not CI requirements); tests that
need one call `pytest.skip(...)` when it can't be found, per the task
brief's "if opa is installable locally via mise/brew... else validate syntax
with a vendored parser test and note it."

Search order, matching how each tool actually ended up available on this
machine (see the response accompanying this file's original authoring
turn for the full trail):
  1. `shutil.which` — the normal case, tool already on PATH.
  2. `~/.local/share/mise/shims/<tool>` — mise-installed but the shims dir
     isn't on this process's PATH (true for every non-interactive subprocess
     spawned outside an activated mise shell, which is the common case for
     a test runner).
  3. Homebrew's fixed prefixes (`/opt/homebrew/bin`, `/usr/local/bin`) —
     where `cfn-guard` actually landed here (`brew install cfn-guard`).
"""

from __future__ import annotations

import shutil
from pathlib import Path


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    mise_shim = Path.home() / ".local" / "share" / "mise" / "shims" / name
    if mise_shim.exists():
        return str(mise_shim)

    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)

    return None
