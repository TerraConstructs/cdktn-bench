"""oracles/tests/toolcheck.py

Best-effort local discovery of `opa`, for the small number of tests that
validate an emitted skeleton with the real tool rather than just asserting
on its Python-level content. It is not a hard dependency of this repo (`pyproject.toml` has no such entry, deliberately —
this is a developer-machine convenience, not a CI requirement); a test that
needs it calls `pytest.skip(...)` when it can't be found.

Search order, matching how the tool actually ends up available on a
developer machine:
  1. `shutil.which` — the normal case, tool already on PATH.
  2. `~/.local/share/mise/shims/<tool>` — mise-installed but the shims dir
     isn't on this process's PATH (true for every non-interactive subprocess
     spawned outside an activated mise shell, which is the common case for
     a test runner).
  3. Homebrew's fixed prefixes (`/opt/homebrew/bin`, `/usr/local/bin`).
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
