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
     ``--ak``/``--ae`` overrides, ...) the caller passes as ``extra_cfg``;
  5. Harbor's own equipping declarations -- ``task.toml [environment]
     mcp_servers`` and ``skills_dir`` -- and ``environment/docker-compose.yaml``,
     which can add a sidecar service the agent and the verifier both reach
     (``HASH_SCHEME_VERSION`` 2, DECISIONS.md Amendment 47).

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
import tomllib
import warnings
from pathlib import Path, PurePosixPath
from typing import Any

# Bump if the manifest shape below ever changes in a way that should mint
# new hashes for byte-identical inputs (e.g. a new field is folded in).
# Scheme 2 folds in Harbor's OWN equipping declarations -- the compose sidecar
# file, `task.toml [environment] mcp_servers` and `[environment] skills_dir` --
# which scheme 1 never read, so an inline mcp_servers block changed the trial and
# not the hash. Rows minted under the two schemes are not comparable by hash
# (DECISIONS.md Amendment 47).
HASH_SCHEME_VERSION = 2

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

# Harbor merges a task's `environment/docker-compose.yaml` extra services after
# its own base file and runs one compose project per trial, so this file is the
# only place a sidecar service (the module-registry responder, which also hosts
# the M2 index tool) is declared. Nothing else in the manifest walks
# `environment/`, and the image digest does not cover it.
COMPOSE_REL_PATH = "environment/docker-compose.yaml"


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


def _compose_sha256(task_dir: Path) -> str | None:
    """sha256 of ``environment/docker-compose.yaml``, or None when absent.

    The key is ALWAYS present in the manifest (null when there is no file), so
    adding the first compose file to a task moves its hash rather than leaving two
    differently-equipped trials sharing one.
    """
    compose = task_dir / COMPOSE_REL_PATH
    if not compose.is_file():
        return None
    return _sha256_bytes(compose.read_bytes())


def _skills_dir_files(task_dir: Path, declared: str) -> list[dict[str, str]] | None:
    """Per-file sha256 of the tree ``[environment] skills_dir`` names, sorted by
    posix path, or None when the tree is not readable from the host.

    ``skills_dir`` is a path INSIDE the container, so it is resolved two ways: as
    a task-dir-relative path, then by its own basename when exactly one directory
    of that name ships in the task dir (Harbor COPYs ``environment/`` into the
    image, so that is where a vendored skill lives). Ambiguous or absent means
    None -- a guess between two candidate trees would put a wrong digest in the
    hash, which is worse than recording that only the declared path is known and
    leaving the image digest to cover the bytes.
    """
    candidate: Path | None = None
    direct = task_dir / declared.lstrip("/")
    if direct.is_dir():
        candidate = direct
    else:
        basename = PurePosixPath(declared).name
        matches = sorted(p for p in task_dir.rglob(basename) if p.is_dir())
        if len(matches) == 1:
            candidate = matches[0]
    if candidate is None:
        return None
    return [
        {
            "path": f.relative_to(task_dir).as_posix(),
            "sha256": _sha256_bytes(f.read_bytes()),
        }
        for f in sorted(
            (f for f in candidate.rglob("*") if f.is_file()),
            key=lambda f: f.relative_to(task_dir).as_posix(),
        )
    ]


def harbor_declared_equipping(task_dir: str | Path) -> dict[str, Any]:
    """Harbor's OWN equipping declarations from ``task.toml [environment]``.

    ``mcp_servers`` is a list of ``{name, transport, url, command, args}`` tables
    and ``skills_dir`` a container path, both read by Harbor when it builds the
    agent (``harbor/models/task/config.py``, ``harbor/trial/trial.py``). Neither is
    a file this module's glob can find, so a task declaring an MCP server inline
    changed the trial and not the hash under scheme 1. Both keys are always
    present, null when undeclared.

    A malformed/absent ``task.toml`` reads as "nothing declared", the same
    treatment ``_workspace_seed_sha256`` gives it.
    """
    task_dir = Path(task_dir)
    task_toml = task_dir / "task.toml"
    declared: dict[str, Any] = {"mcp_servers": None, "skills_dir": None}
    if not task_toml.is_file():
        return declared
    try:
        data = tomllib.loads(task_toml.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return declared
    environment = data.get("environment") or {}
    servers = environment.get("mcp_servers")
    if servers:
        declared["mcp_servers"] = json.loads(json.dumps(servers, sort_keys=True))
    skills_dir = environment.get("skills_dir")
    if isinstance(skills_dir, str) and skills_dir:
        declared["skills_dir"] = {
            "declared": skills_dir,
            "files": _skills_dir_files(task_dir, skills_dir),
        }
    return declared


def harbor_equipping_offenders(task_dir: str | Path) -> list[str]:
    """Human-readable names of the Harbor-declared equipping a task carries.

    The holdout rule is about equipping, not about files, so it has to read the
    same channel the hash does: a holdout task that declares an MCP server or a
    skills dir in ``task.toml`` is tuned equipping on a holdout scenario however
    few files it ships (``generator/gen.py::enforce_no_holdout_equipping``).
    """
    declared = harbor_declared_equipping(task_dir)
    offenders: list[str] = []
    servers = declared["mcp_servers"]
    if servers:
        names = ", ".join(
            str(s.get("name", "<unnamed>")) if isinstance(s, dict) else str(s)
            for s in servers
        )
        offenders.append(f"task.toml [environment] mcp_servers ({names})")
    if declared["skills_dir"]:
        offenders.append(
            f"task.toml [environment] skills_dir = {declared['skills_dir']['declared']}"
        )
    return offenders


# --- The equipping LEVEL a row is labelled with (ROADMAP M2) ----------------
#
# `metrics/result_schema.json`'s `harness` field is the equipping axis, and
# `metrics/tokens_to_green.py` already keys every cell on it -- so the M2
# factorial's third level is a third `harness` value, not a parallel field. One
# map, read by the emitter and by the generator's own tests:
LEVEL_TO_HARNESS = {"bare": "empty", "tuned": "tuned", "tuned-stale": "tuned-stale"}
# Matched longest-first, so a level name ending in another level's name is read
# as itself. `bare` is absent by construction: it is the no-suffix case.
_LEVEL_SUFFIXES = ("-tuned-stale", "-tuned")


class EquippingLabelMismatch(ValueError):
    """A task whose equipping LEVEL and equipping CHANNEL disagree.

    The signature M2 failure mode is a mislabelled row: a `-tuned` task dir whose
    material never reached the hash (so it is a bare trial published as tuned), or
    a bare task dir carrying equipping nobody registered (so a tuned trial is
    published as empty). Both pool incomparable trials into one cell, which is
    exactly what the hash exists to prevent -- so they are refused, never warned.
    """


def equipping_level(task_dir: str | Path) -> str:
    """One task's equipping level, cross-checked against the hash's own channel.

    The level's NAME comes from the task directory
    (`generator/gen.py::task_basename`), because `tuned` and `tuned-stale` are
    deliberately indistinguishable from inside the container -- same skill
    directory name, same frontmatter `name`, same MCP list -- so no in-container
    channel can tell them apart, and inventing one would make the level itself an
    observable the agent could condition on.

    Whether the task is equipped AT ALL comes from Harbor's declarations, the
    same channel `compute_equipping_hash` folds in (scheme 2, Amendment 47) and
    the same one the holdout gate reads. A disagreement between the two is
    refused: see EquippingLabelMismatch.
    """
    task_dir = Path(task_dir)
    level = "bare"
    for suffix in _LEVEL_SUFFIXES:
        if task_dir.name.endswith(suffix):
            level = suffix.lstrip("-")
            break
    declared = harbor_equipping_offenders(task_dir)
    if level == "bare" and declared:
        raise EquippingLabelMismatch(
            f"{task_dir} has no equipping-level suffix, so it would be published "
            f"as harness={LEVEL_TO_HARNESS['bare']!r}, but it declares equipping: "
            f"{'; '.join(declared)}. Unregistered equipping on a bare row."
        )
    if level != "bare" and not declared:
        raise EquippingLabelMismatch(
            f"{task_dir} names level {level!r} but declares no equipping in "
            f"task.toml [environment] (mcp_servers / skills_dir), the channel the "
            f"equipping hash reads. A bare trial cannot be published as tuned."
        )
    return level


def harness_for_task(task_dir: str | Path) -> str:
    """The `harness` value one task's rows carry, from `equipping_level`."""
    return LEVEL_TO_HARNESS[equipping_level(task_dir)]


def _tree_sha256(root: Path) -> str:
    """One digest over a directory: the canonical JSON of every file's posix path
    and sha256, sorted. Two skill dirs with identical bytes digest alike whatever
    their location or walk order."""
    entries = [
        {"path": f.relative_to(root).as_posix(), "sha256": _sha256_bytes(f.read_bytes())}
        for f in sorted(
            (f for f in root.rglob("*") if f.is_file()),
            key=lambda f: f.relative_to(root).as_posix(),
        )
    ]
    return _sha256_bytes(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def cli_equipping_digests(flags: list[str]) -> list[dict[str, Any]]:
    """CONTENT digests for ``--mcp-config <file>`` / ``--skill <dir>`` arguments.

    Input is ``["--skill=./skills/tf-authoring", ...]`` as ``scripts/run-bench.sh``
    assembles it; output is one ``{flag, sha256}`` entry per argument, in the order
    given. The path is deliberately NOT recorded: two different files at the same
    path hashed alike when ``jobs/*/budget.json`` held the flag string, which is
    the whole defect this replaces, and a local path is not a property of the
    trial. ``sha256`` is null when the argument names nothing readable, so a
    typo'd flag is visible as unhashable rather than as no equipping at all.
    """
    digests: list[dict[str, Any]] = []
    for flag in flags:
        name, _, value = flag.partition("=")
        path = Path(value) if value else None
        if path is not None and path.is_dir():
            digest: str | None = _tree_sha256(path)
        elif path is not None and path.is_file():
            digest = _sha256_bytes(path.read_bytes())
        else:
            digest = None
        digests.append({"flag": name, "sha256": digest})
    return digests


WORKSPACE_SEED_KEY = "workspace_seed_sha256"


def _workspace_seed_sha256(task_dir: Path) -> str | None:
    """``task.toml [metadata] workspace_seed_sha256``, or None.

    A BROWNFIELD task (``specs/SCHEMA.md`` §2.7) does not start from the empty
    ``entry_file`` skeleton — its starting workspace is a hand-authored,
    per-arm seed baked into the image. Two trials whose seed differs are not
    comparable, and nothing else in this manifest would notice: the hash covers
    ``instruction.md``, equipping files, the image digest and ``extra_cfg``, and
    it deliberately does **not** walk ``environment/``. The image digest *would*
    cover it — the seed is baked into the image — except that
    ``_resolve_image_digest`` falls back to the bare tag string whenever docker
    is unavailable/offline or the image isn't built locally (and only
    ``warnings.warn``s), at which point two different seeds under one tag hash
    identically.

    Reading it here rather than making every caller remember to pass it is the
    point: a channel a caller can forget is a channel that will be forgotten.
    Folded into the EXISTING ``extra_cfg`` slot (design memo §3.4), so no
    ``HASH_SCHEME_VERSION`` bump is needed and no greenfield task's already-
    published hash moves — greenfield ``task.toml``s simply have no such key.

    A malformed/absent ``task.toml`` is not an error here: ``task_dir`` is only
    contractually required to hold an instruction, and every failure mode of
    this lookup is "no seed declared", which is the greenfield default.
    """
    task_toml = task_dir / "task.toml"
    if not task_toml.is_file():
        return None
    try:
        data = tomllib.loads(task_toml.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return None
    value = (data.get("metadata") or {}).get(WORKSPACE_SEED_KEY)
    return value if isinstance(value, str) and value else None


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

    seed_sha = _workspace_seed_sha256(task_dir)
    if seed_sha is not None:
        declared = extra_cfg.get(WORKSPACE_SEED_KEY)
        if declared is not None and declared != seed_sha:
            raise ValueError(
                f"compute_equipping_hash: extra_cfg[{WORKSPACE_SEED_KEY!r}] is "
                f"{declared!r} but {task_dir / 'task.toml'} declares {seed_sha!r} "
                "— refusing to guess which starting workspace this trial ran "
                "against"
            )
        extra_cfg = {**extra_cfg, WORKSPACE_SEED_KEY: seed_sha}

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
        # Scheme 2 (DECISIONS.md Amendment 47): Harbor's own two equipping
        # channels, plus the compose file that can add a sidecar service to the
        # trial. All three keys are always present so their first use moves a
        # hash instead of silently pooling.
        "compose_sha256": _compose_sha256(task_dir),
        "harbor_equipping": harbor_declared_equipping(task_dir),
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
