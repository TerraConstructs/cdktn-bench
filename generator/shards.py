"""Scenario shards: the count, the assignment rule, and the materializer.

A shard IS an AWS member account — aws-bench binds one scenario to exactly one
account and serializes mutating trials per scenario_id, so more scenarios is
the only way to get more concurrency or contamination isolation. Shard 0 keeps
the pre-existing name "anchor" so raising the count never re-provisions it;
shard k>=1 is "anchor-k".

THE ASSIGNMENT RULE (also stated in specs/SCHEMA.md §8.3 and DECISIONS.md
Amendment 33): a read-only task runs on shard 0; a mutating task runs on one of
shards 1..N-1, chosen so one spec's arms land on different shards whenever
N >= 4. At N == 1 every task is on "anchor" and this module changes nothing.

Background and the owner-side AWS consequences: docs/generator.md "Scenario
shards".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARDS_CONFIG_PATH = Path(__file__).resolve().parent / "shards.toml"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
LOCAL_REGISTRY_PATH = REPO_ROOT / "local-registry.json"
REGISTRY_DATASET_NAME = "cdktn-bench-anchor"

# Shard 0's name is the pre-existing scenario's name: renaming it would orphan
# the member account `env init` already tagged `aws-bench:scenario = anchor/PRIMARY`.
SCENARIO_BASE = "anchor"

# Assignment is a function of (spec.id, arm), so the arm order must be fixed
# here rather than read from a dict whose insertion order could shift.
ARM_ORDER: tuple[str, ...] = ("awscdk", "hcl_raw", "terraconstructs")


class ShardDrift(RuntimeError):
    """A shard tree or the registry does not match what --write would emit."""


def shard_count() -> int:
    """N from generator/shards.toml. Out-of-range values are refused here so a
    typo cannot silently collapse the benchmark onto one account."""
    raw = tomllib.loads(SHARDS_CONFIG_PATH.read_text())
    n = raw.get("shard_count")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(
            f"{SHARDS_CONFIG_PATH}: shard_count must be an integer >= 1, got {n!r}"
        )
    return n


def shard_name(index: int) -> str:
    if index < 0:
        raise ValueError(f"shard index must be >= 0, got {index}")
    return SCENARIO_BASE if index == 0 else f"{SCENARIO_BASE}-{index}"


def _is_mutating(spec) -> bool:
    # `concurrency_mode` unset means read-only — the same default
    # generator/gen.py::build_task_toml writes into [concurrency] mode.
    return spec.verifier.live_check.concurrency_mode == "mutating"


def shard_for(spec, arm: str) -> str:
    """The aws-bench scenario_id this (spec, arm) task binds to.

    Read-only tasks share shard 0: they co-run under the admission gate's
    reader-preferring lock, so extra accounts buy them nothing. A mutating task
    holds the gate exclusively for its whole trial plus its reset, so its arms
    spread over shards 1..N-1 — at N >= 4 one spec's three arms never wait on
    each other. The per-spec offset rotates each spec's arm->shard mapping to
    even out mutating load; two specs' same-arm trials may still share a shard.
    """
    if arm not in ARM_ORDER:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARM_ORDER}")
    n = shard_count()
    if n == 1 or not _is_mutating(spec):
        return shard_name(0)
    mutating_shards = n - 1
    offset = int(hashlib.sha256(spec.id.encode("utf-8")).hexdigest()[:8], 16)
    return shard_name(1 + (offset + ARM_ORDER.index(arm)) % mutating_shards)


# --- materializer ----------------------------------------------------------


def template_files() -> list[str]:
    """The TRACKED files of scenarios/anchor, as posix paths relative to it.

    Tracked-only, via git: aws-bench re-hashes every file under a scenario dir
    on every reset, so copied node_modules/cdk.out/dist would add hundreds of MB
    of hash surface and reset I/O per shard, for output the scenario Dockerfile
    rebuilds with `npm ci && npm run build`.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "scenarios/anchor"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rels = [p for p in out.split("\0") if p]
    if not rels:
        raise ShardDrift(
            "git ls-files scenarios/anchor returned nothing — the shard "
            "template is unreadable (not a git checkout?), refusing to "
            "materialize an empty scenario"
        )
    prefix = "scenarios/anchor/"
    return sorted(p[len(prefix):] for p in rels)


def _rewrite(rel: str, body: bytes, name: str) -> bytes:
    """Shard k's copy differs from the template in its NAME only.

    scenario.toml's `name` tags the member account and README.md's first
    heading tells two shards apart. Everything else stays byte-identical, which
    is what makes a shard interchangeable with shard 0.
    """
    if rel == "scenario.toml":
        old = f'name = "{SCENARIO_BASE}"\n'.encode()
        if old not in body:
            raise ShardDrift(
                f"scenarios/{SCENARIO_BASE}/scenario.toml has no "
                f'`name = "{SCENARIO_BASE}"` line to rewrite'
            )
        return body.replace(old, f'name = "{name}"\n'.encode(), 1)
    if rel == "README.md":
        old = f"# scenarios/{SCENARIO_BASE}\n".encode()
        if not body.startswith(old):
            raise ShardDrift(
                f"scenarios/{SCENARIO_BASE}/README.md no longer opens with "
                f"`# scenarios/{SCENARIO_BASE}` — the shard materializer "
                "rewrites that heading and will not guess a replacement"
            )
        return f"# scenarios/{name}\n".encode() + body[len(old):]
    return body


def expected_shard_tree(index: int) -> dict[str, bytes]:
    name = shard_name(index)
    return {
        rel: _rewrite(rel, (SCENARIOS_DIR / SCENARIO_BASE / rel).read_bytes(), name)
        for rel in template_files()
    }


def expected_registry_scenarios() -> list[dict[str, str]]:
    return [
        {"name": shard_name(k), "path": f"scenarios/{shard_name(k)}"}
        for k in range(shard_count())
    ]


def _existing_shard_dirs() -> list[Path]:
    return sorted(
        p
        for p in SCENARIOS_DIR.glob(f"{SCENARIO_BASE}-*")
        if p.is_dir() and p.name[len(SCENARIO_BASE) + 1:].isdigit()
    )


def _registry_dataset() -> dict:
    data = json.loads(LOCAL_REGISTRY_PATH.read_text())
    dataset = next((d for d in data if d.get("name") == REGISTRY_DATASET_NAME), None)
    if dataset is None:
        raise ShardDrift(
            f"{LOCAL_REGISTRY_PATH}: no dataset named {REGISTRY_DATASET_NAME!r}"
        )
    return dataset


def _registry_scenarios_on_disk() -> list[dict[str, str]]:
    return _registry_dataset().get("scenarios", [])


def check_scenarios() -> list[str]:
    """Every way scenarios/ + local-registry.json differ from --write's output."""
    problems: list[str] = []
    n = shard_count()
    wanted = {shard_name(k) for k in range(1, n)}
    for stale in _existing_shard_dirs():
        if stale.name not in wanted:
            problems.append(
                f"scenarios/{stale.name}/ exists but shard_count = {n} — "
                "run `make shards` to remove it"
            )
    for k in range(1, n):
        name = shard_name(k)
        root = SCENARIOS_DIR / name
        expected = expected_shard_tree(k)
        if not root.is_dir():
            problems.append(f"scenarios/{name}/ is missing — run `make shards`")
            continue
        actual = {
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
        }
        for rel in sorted(set(expected) - actual):
            problems.append(f"scenarios/{name}/{rel} is missing")
        for rel in sorted(actual - set(expected)):
            problems.append(f"scenarios/{name}/{rel} is not in the shard template")
        for rel in sorted(set(expected) & actual):
            if (root / rel).read_bytes() != expected[rel]:
                problems.append(
                    f"scenarios/{name}/{rel} differs from scenarios/{SCENARIO_BASE}/{rel} "
                    "(shards are name-rewrites of the template, never hand-edited)"
                )
    if _registry_scenarios_on_disk() != expected_registry_scenarios():
        problems.append(
            f"{LOCAL_REGISTRY_PATH.name}: the dataset's `scenarios` array does not "
            f"list shards 0..{n - 1} — run `make shards`"
        )
    return problems


def check_tasks() -> list[str]:
    """Every way the generated tasks/ tree disagrees with shard_count.

    `make shards` materializes scenarios/ and the registry but never touches
    tasks/, so raising the knob without `make gen-all` leaves every task on its
    old shard while the extra member accounts sit idle. Nothing else notices:
    task.toml's scenario_id still matches its own parent directory, because
    neither was regenerated. local-registry.json's `tasks` array is checked here
    for the same reason — only gen.py writes it.
    """
    from gen import ARM_DIRNAME, TASKS_DIR, task_dir  # gen imports this module
    from spec_model import load_spec

    problems: list[str] = []
    n = shard_count()
    registry_paths = {
        entry.get("name"): entry.get("path")
        for entry in _registry_dataset().get("tasks", [])
    }
    known = {shard_name(k) for k in range(n)}
    for child in sorted(TASKS_DIR.iterdir()):
        if child.is_dir() and child.name not in known:
            problems.append(
                f"tasks/{child.name}/ is not one of shards 0..{n - 1} — a task "
                "tree with no scenario beside it; run `make gen-all`"
            )
    for spec_path in sorted((REPO_ROOT / "specs").glob("*.yaml")):
        if spec_path.name == "split.yaml":
            continue
        spec = load_spec(spec_path)
        for arm in spec.arms.enabled_arms():
            wanted = task_dir(spec, arm)
            name = f"{spec.id}-{ARM_DIRNAME[arm]}"
            if not wanted.is_dir():
                problems.append(
                    f"tasks/{shard_for(spec, arm)}/{name}/ is missing — tasks/ is "
                    f"stale for shard_count = {n}, run `make gen-all`"
                )
            for other in sorted(TASKS_DIR.glob(f"*/{name}")):
                if other.is_dir() and other != wanted:
                    problems.append(
                        f"{other.relative_to(REPO_ROOT)} is a copy of a task that "
                        f"belongs to shard {shard_for(spec, arm)} — tasks/ is stale "
                        f"for shard_count = {n}, run `make gen-all`"
                    )
            want_path = wanted.relative_to(REPO_ROOT).as_posix()
            if name in registry_paths and registry_paths[name] != want_path:
                problems.append(
                    f"{LOCAL_REGISTRY_PATH.name}: task {name!r} points at "
                    f"{registry_paths[name]!r}, not {want_path!r} — run `make gen-all`"
                )
    return problems


def check() -> list[str]:
    """Scenario/registry drift AND tasks/ staleness — everything `make check`
    must see before an operator pays for accounts a run never uses."""
    return check_scenarios() + check_tasks()


def write() -> list[str]:
    """Materialize shards 1..N-1 and the registry. A no-op at N == 1."""
    changed: list[str] = []
    n = shard_count()
    wanted = {shard_name(k) for k in range(1, n)}
    for stale in _existing_shard_dirs():
        if stale.name not in wanted:
            shutil.rmtree(stale)
            changed.append(f"removed scenarios/{stale.name}/")
    for k in range(1, n):
        name = shard_name(k)
        root = SCENARIOS_DIR / name
        if root.exists():
            shutil.rmtree(root)
        tree = expected_shard_tree(k)
        for rel, body in tree.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        changed.append(f"wrote scenarios/{name}/ ({len(tree)} files)")

    data = json.loads(LOCAL_REGISTRY_PATH.read_text())
    dataset = next((d for d in data if d.get("name") == REGISTRY_DATASET_NAME), None)
    if dataset is None:
        raise ShardDrift(
            f"{LOCAL_REGISTRY_PATH}: no dataset named {REGISTRY_DATASET_NAME!r}"
        )
    expected = expected_registry_scenarios()
    if dataset.get("scenarios") != expected:
        dataset["scenarios"] = expected
        LOCAL_REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n")
        changed.append(f"updated {LOCAL_REGISTRY_PATH.name} scenarios[]")
    return changed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="materialize shards + registry")
    group.add_argument("--check", action="store_true", help="fail on drift (exit 1)")
    args = parser.parse_args(argv[1:])
    n = shard_count()
    if args.write:
        for line in write() or ["nothing to do"]:
            print(f"shards: {line}")
        return 0
    problems = check()
    for line in problems:
        print(f"SHARD DRIFT: {line}", file=sys.stderr)
    if problems:
        return 1
    print(f"shards: OK (shard_count = {n}: {', '.join(shard_name(k) for k in range(n))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
