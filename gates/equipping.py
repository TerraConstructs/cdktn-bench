"""gates/equipping.py — the equipping hash (build plan Phase 0 item 4).

``compute_equipping_hash()`` produces a single sha256 digest binding
together everything that can make one trial's result incomparable to
another's under the *same* arm/model/reward label:

  1. the exact instruction text the agent received (``instruction.md``, or
     every ``steps/<name>/instruction.md`` for a multi-step task, which has no
     root instruction.md at all — see ``_discover_step_instructions``);
  2. every skill/MCP/plugin config file shipped alongside the task
     (the ``--skill``/``--mcp-config``/plugin-manifest equipping that makes
     up the prereg §2.2 empty-vs-tuned harness axis,
     ``docs/aws-bench-guide.md`` "Claude Code specifics");
  3. the content-addressed Docker image the agent actually ran in;
  4. any other harness-affecting knob (model name, ``harness`` flag,
     ``--ak``/``--ae`` overrides, ...) the caller passes as ``extra_cfg``.

This is the lex00/chant-bench "equipping hash" pattern
(``docs/iac-abstraction-aws-bench-plan.md`` Phase 0 item 4): no result row
can be silently pooled across a different prompt, a different tuned-skill
set, or a rebuilt image, because all three are baked into one hash carried
on every row (see the required ``equipping_hash`` field in
``metrics/result_schema.json``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import warnings
from pathlib import Path
from typing import Any

# Bump if the manifest shape below ever changes in a way that should mint
# new hashes for byte-identical inputs (e.g. a new field is folded in).
HASH_SCHEME_VERSION = 1

# Filenames/dirs treated as "equipping" config, discovered anywhere under
# task_dir. This is our own convention layered on top of aws-bench/Harbor's
# actual knobs, which take a file/dir of any name
# (``--mcp-config <file>``, ``--skill <dir>``,
# ``docs/aws-bench-guide.md`` "Claude Code specifics"); standardizing on
# these names inside a task dir gives compute_equipping_hash something
# deterministic to glob for without a second manifest to keep in sync.
_MCP_CONFIG_NAMES = {"mcp.json", ".mcp.json"}
_PLUGIN_CONFIG_NAMES = {"plugins.json", "plugin.json", "marketplace.json"}
_SKILL_DIR_NAME = "skills"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _discover_equipping_files(task_dir: Path) -> list[Path]:
    """Every skill/MCP/plugin config file under task_dir, as relative paths.

    Returned unsorted — callers must sort before hashing so directory-walk
    order (which varies by filesystem/OS) never affects the result.
    """
    found: list[Path] = []
    for path in task_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(task_dir)
        if _SKILL_DIR_NAME in rel.parts[:-1]:
            found.append(rel)
        elif path.name in _MCP_CONFIG_NAMES or path.name in _PLUGIN_CONFIG_NAMES:
            found.append(rel)
    return found


def _discover_step_instructions(task_dir: Path) -> list[dict[str, str]]:
    """Every ``steps/<name>/instruction.md`` under task_dir, sorted, hashed.

    A MULTI-STEP task (``[[steps]]`` in task.toml, run by
    ``cdktn_bench.trial.CdktnMultiStepTrial``) has **no root instruction.md**:
    Harbor sets ``Task.instruction = ""`` for a steps task and delivers
    ``steps/<name>/instruction.md`` per step instead
    (``harbor/models/task/task.py``). Without this, ``compute_equipping_hash``
    raised FileNotFoundError on every multi-step task and ``to_result_row``
    then refused to emit a row at all — a multi-step trial could not be
    published (2026-08-20, task #14).

    Sorted by relative posix path so filesystem walk order never leaks into the
    hash, exactly like ``equipping_files``. Every step instruction is folded
    in, not just the declared ones, because an undeclared
    ``steps/<n>/instruction.md`` sitting in a task dir is itself a difference
    between two otherwise-identical equippings.
    """
    steps_dir = task_dir / "steps"
    if not steps_dir.is_dir():
        return []
    found = [
        p for p in steps_dir.glob("*/instruction.md") if p.is_file()
    ]
    return [
        {
            "path": p.relative_to(task_dir).as_posix(),
            "sha256": _sha256_bytes(p.read_bytes()),
        }
        for p in sorted(found, key=lambda p: p.relative_to(task_dir).as_posix())
    ]


def _resolve_image_digest(image_ref: str) -> tuple[str, bool]:
    """Return ``(content_address, resolved)`` for a Docker image reference.

    ``resolved=True`` means the returned string is a genuine content
    digest — an already-pinned ``repo@sha256:...`` ref passed straight
    through, a registry ``RepoDigest``, or a local image ``Id`` — so two
    builds with identical layers hash identically regardless of tag.
    ``resolved=False`` means we fell back to the bare ``image_ref`` string
    itself (no ``docker`` binary, daemon unreachable/offline, or the image
    isn't built/pulled locally): the hash still deterministically reflects
    *that string*, but can no longer detect a silently-rebuilt image under
    the same tag. A warning is always emitted in the fallback case.
    """
    if "@sha256:" in image_ref:
        return image_ref, True  # already content-addressed; no need to shell out

    for fmt in ("{{index .RepoDigests 0}}", "{{.Id}}"):
        try:
            proc = subprocess.run(
                ["docker", "inspect", f"--format={fmt}", image_ref],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            break  # no docker binary, or a hung daemon — stop trying, fall through
        out = proc.stdout.strip()
        if proc.returncode == 0 and out and out != "<no value>":
            return out, True

    warnings.warn(
        f"compute_equipping_hash: could not resolve a content digest for "
        f"image {image_ref!r} (docker unavailable, image not built/pulled "
        f"locally, or offline) — falling back to the bare tag string. The "
        f"equipping hash will NOT change if this image is silently "
        f"rebuilt under the same tag.",
        stacklevel=3,
    )
    return image_ref, False


def compute_equipping_hash(
    task_dir: str | Path,
    image_ref: str,
    extra_cfg: dict[str, Any],
) -> str:
    """Canonical sha256 hex digest over everything that equips one trial.

    Args:
        task_dir: task directory containing ``instruction.md`` (or, for a
            multi-step task, ``steps/<name>/instruction.md``) and (if the
            task uses tuned equipping) any ``mcp.json``/``plugins.json``/
            ``skills/`` config alongside it.
        image_ref: the Docker image reference the agent container ran
            (a tag like ``cdktn-bench/awscdk:dev`` or an already-pinned
            ``repo@sha256:...`` reference).
        extra_cfg: JSON-serializable dict of everything else that changes
            the equipping but isn't a file — e.g.
            ``{"model": "claude-sonnet-5", "harness": "tuned",
            "max_turns": 8}``.

    Returns:
        A 64-character lowercase hex sha256 digest.

    Deterministic: two calls with byte-identical ``task_dir`` contents, the
    same ``image_ref`` (or two ``image_ref`` values docker resolves to the
    same digest), and an equal ``extra_cfg`` produce the identical hash —
    independent of machine, filesystem walk order, or ``extra_cfg`` key
    insertion order. Changing a single byte of ``instruction.md``, any
    equipping file, the resolved image digest, or any ``extra_cfg`` value
    changes the hash.
    """
    task_dir = Path(task_dir)

    instruction_path = task_dir / "instruction.md"
    step_instructions = _discover_step_instructions(task_dir)
    if instruction_path.is_file():
        instruction_sha: str | None = _sha256_bytes(instruction_path.read_bytes())
    elif step_instructions:
        # Multi-step task: the prompts live per step. See
        # _discover_step_instructions.
        instruction_sha = None
    else:
        raise FileNotFoundError(
            f"compute_equipping_hash: {instruction_path} does not exist and no "
            f"{task_dir / 'steps'}/*/instruction.md was found — every task must "
            f"have an instruction to hash."
        )

    equipping_files = [
        {"path": rel.as_posix(), "sha256": _sha256_bytes((task_dir / rel).read_bytes())}
        for rel in sorted(_discover_equipping_files(task_dir), key=lambda p: p.as_posix())
    ]

    image_digest, _resolved = _resolve_image_digest(image_ref)

    try:
        # Round-trip through json to (a) prove extra_cfg is JSON-serializable
        # up front with a clear error, and (b) normalize e.g. tuple->list so
        # equal-but-not-identical Python values still canonicalize the same.
        extra_cfg_canonical = json.loads(json.dumps(extra_cfg, sort_keys=True))
    except TypeError as exc:
        raise TypeError(
            f"compute_equipping_hash: extra_cfg must be JSON-serializable "
            f"(model/harness flags), got: {exc}"
        ) from exc

    manifest: dict[str, Any] = {
        "hash_scheme_version": HASH_SCHEME_VERSION,
        "equipping_files": equipping_files,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "extra_cfg": extra_cfg_canonical,
    }
    # Exactly one of these two keys is ever present. A single-step task keeps
    # the original key and therefore its original hash BIT-FOR-BIT — no
    # HASH_SCHEME_VERSION bump, no re-hashing of published results. The
    # multi-step key is new for a task shape that has never been hashed before,
    # so it cannot move an existing hash.
    if instruction_sha is not None:
        manifest["instruction_md_sha256"] = instruction_sha
    else:
        manifest["step_instructions"] = step_instructions
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))
