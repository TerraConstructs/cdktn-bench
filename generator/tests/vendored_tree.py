"""generator/tests/vendored_tree.py — the one definition of "this file is
upstream `terraform-aws-modules` source, not bench-authored text", shared by
every agent-visible sweep that walks an `hcl_modules` task's `environment/`.

The Dockerfile COPYs `environment/` whole, so the vendored tree IS agent-visible
and every such sweep meets it. Sweeping it for scenario vocabulary would assert
that `terraform-aws-modules` is written in some other language: `lifecycle`,
`create_before_destroy` and `throttling_burst_limit` are the library's public
surface, and discovering them is the skill this arm measures. What makes the
exemption safe is proved elsewhere, in full: every file's sha256 is in
`manifest.json` and the manifest's commit is the pinned tag's, so no byte under
a `<name>-<version>/` directory is ours (`test_vendored_modules.py`, which owns
that proof and states the scope argument at length). `manifest.json` sits at the
tree's root rather than inside a version directory, so it is NOT exempt here --
the responder answers `/v1/modules/search` out of it, and it is bench-authored.

Exempting this in three sweeps by three copies of one path test is how the four
arms drifted apart before; the predicate lives here so a sweep cannot half-know
about the tree.
"""

from __future__ import annotations

from pathlib import Path

VENDORED_MODULES_DIR = "modules"


def is_vendored_module_file(path: Path, env_dir: Path) -> bool:
    """True for a file inside `environment/modules/<name>-<version>/`.

    Depth is part of the test, not incidental: a file directly in
    `environment/modules/` (`manifest.json`) is bench-authored and swept.
    """
    rel = path.relative_to(env_dir).parts
    return len(rel) > 2 and rel[0] == VENDORED_MODULES_DIR
