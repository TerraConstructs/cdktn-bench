"""generator/tests/test_equipping_material.py — the committed tuned-equipping
material under `equipping/` (prereg §2.2, ROADMAP M2).

Five things are checked, and the deny-list one is deliberately split in two --
see THE DENY-LIST SCOPE below.

1. THE PINS AND THE TREE AGREE. `scripts/vendor_equipping.py --verify` re-hashes
   every vendored and bench-written file against `equipping/MANIFEST.json`, so an
   edit to a skill is either in the manifest or a failure.
2. EVERY LEVEL RESOLVES. A level file's skill sources exist, and its MCP servers
   are either the bench sidecar (a URL on the compose network) or a pinned
   distribution recorded in MANIFEST.json -- never an unpinned `@latest`.
3. THE LEVEL IS NOT DISCOVERABLE FROM INSIDE THE CONTAINER. For one arm, `tuned`
   and `tuned-stale` must land the same skill DIRECTORY names and declare the
   same MCP server names. If an agent could read which level it drew, H2 would
   measure the label rather than the guidance.
4. BENCH-AUTHORED TEXT IS CLEAN, IN FULL. Our own prose is held to the whole deny
   list and to a meta-vocabulary check: a skill that names the study tells the
   agent it is in one.
5. VENDORED TEXT CARRIES NO SCENARIO'S OWN ANSWER (and its licence travels).

THE DENY-LIST SCOPE. `spec_model.identity_deny_hits` exists to stop the BENCH's
own authored text handing an agent a scenario's answer, so bench-authored
equipping is swept in full (check 4). Upstream skill prose is not bench-authored
text: `lifecycle`, `drift` and `create_before_destroy` are Terraform's public
vocabulary, and a Terraform authoring skill that avoided them would not be one --
the same reasoning `test_vendored_modules.py` records for the vendored module
tree. What IS assertable of upstream prose, and is asserted in check 5, is that it
does not reserve any ONE scenario's vocabulary: a pattern only a spec or two
reserves is that spec's trap, and a skill naming it is a leak for that spec
alone. The two surviving hits are allowlisted with their quoted context, so
adding a third is a failure that someone must look at.
"""

from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from spec_model import Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EQUIPPING = REPO_ROOT / "equipping"
LEVELS = EQUIPPING / "levels"
MANIFEST = json.loads((EQUIPPING / "MANIFEST.json").read_text())

ALL_SPECS: list[Spec] = [
    load_spec(p) for p in sorted((REPO_ROOT / "specs").glob("*.yaml")) if p.name != "split.yaml"
]

# A deny pattern this many specs or fewer reserve is that scenario's own trap
# vocabulary rather than the mechanism vocabulary every spec shares.
PER_SPEC_OWNERS_MAX = 3

# Reviewed hits in the vendored upstream prose, with the context that makes each
# one a generic English use and not the scenario it collides with. A new hit fails
# until it is read and either removed or added here.
ALLOWLISTED_VENDOR_HITS = {
    ("singleton", "singleton-child-resource-clobber"): (
        "upstream uses `singleton` for the `count = cond ? 1 : 0` pattern and for "
        "reserving the name `this`; the scenario's trap is an AWS child resource "
        "that is authoritative per parent, which the skill never mentions"
    ),
    ("authoritative", "singleton-child-resource-clobber"): (
        "upstream says `treat findReferences as the authoritative reference set`, "
        "about a language server, not about an AWS resource"
    ),
}

# Words that would tell the agent it is inside a study. `scenario` is included:
# the generator stamps `ScenarioStack`, but equipping prose has no business
# repeating the harness's own vocabulary.
META_VOCAB = re.compile(r"\b(bench|benchmark|prereg|pre-?registration|trial|holdout|cdktn-bench)\b", re.I)


def _bench_files() -> list[Path]:
    """Bench-authored files that CAN reach a container: everything under
    `bench/` except the provenance notes, which live outside every skill
    directory precisely because they name the study (see
    test_the_provenance_file_ships_in_no_skill_directory)."""
    return sorted(
        f
        for f in (EQUIPPING / "bench").rglob("*")
        if f.is_file() and not f.name.endswith("UPSTREAM.md")
    )


def _skill_dirs_in_levels() -> list[Path]:
    out = []
    for lvl in sorted(LEVELS.glob("*.yaml")):
        for skill in yaml.safe_load(lvl.read_text())["skills"]:
            out.append(EQUIPPING / skill["source"])
    return out


def _hits(text: str) -> list[tuple[str, str]]:
    return [(h, spec.id) for spec in ALL_SPECS for h in set(spec.identity_leaks(text))]


def _owner_counts() -> dict[str, int]:
    owners: dict[str, set[str]] = collections.defaultdict(set)
    for spec in ALL_SPECS:
        for pat in spec.agent_deny_vocab:
            owners[pat].add(spec.id)
    # The global patterns are reserved by construction for every spec; anything
    # in a spec's own vocab list is counted above.
    return {pat: len(ids) for pat, ids in owners.items()}


# ---------------------------------------------------------------------------
# 1. the pins and the tree agree
# ---------------------------------------------------------------------------


def test_vendor_equipping_verify_is_green() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "vendor_equipping.py"), "--verify"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_vendored_package_records_its_licence_and_pin() -> None:
    for pkg in MANIFEST["packages"]:
        assert pkg["licence"], pkg["dir"]
        if pkg["dir"].startswith("vendor/"):
            assert len(pkg.get("upstream_commit", "")) == 40, (
                f"{pkg['dir']} is vendored from upstream and must pin a commit sha, "
                "not a tag: a tag can move and a tarball digest is not a pin"
            )
            assert "LICENSE" in pkg["files"], (
                f"{pkg['dir']} ships no LICENSE; the copy that reaches the container "
                "is the copy the licence has to accompany"
            )


# ---------------------------------------------------------------------------
# 2. every level resolves, and every server is pinned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level_file", sorted(LEVELS.glob("*.yaml")), ids=lambda p: p.name)
def test_level_resolves(level_file: Path) -> None:
    data = yaml.safe_load(level_file.read_text())
    pinned = {s["name"] for s in MANIFEST["servers"]}
    for skill in data["skills"]:
        assert (EQUIPPING / skill["source"]).is_dir(), skill
        assert (EQUIPPING / skill["source"] / "SKILL.md").is_file(), skill
    for server in data["mcp_servers"]:
        if server["transport"] == "streamable-http":
            assert server["url"].startswith("http://"), server
            continue
        assert "@latest" not in " ".join(server.get("args") or []), (
            f"{level_file.name} declares {server['name']} unpinned; an `@latest` "
            "resolved at container start is a second uncontrolled input inside the "
            "measured trial"
        )
        assert any(server["command"].endswith(p) for p in pinned), (
            f"{level_file.name} declares {server['name']} ({server['command']}) with "
            f"no pinned version in equipping/MANIFEST.json servers: {sorted(pinned)}"
        )


# ---------------------------------------------------------------------------
# 3. the level is not discoverable from inside the container
# ---------------------------------------------------------------------------


def test_tuned_and_stale_are_indistinguishable_except_by_content() -> None:
    for tuned in sorted(LEVELS.glob("*.tuned.yaml")):
        stale = tuned.with_name(tuned.name.replace(".tuned.yaml", ".tuned-stale.yaml"))
        if not stale.is_file():
            continue
        a, b = (yaml.safe_load(f.read_text()) for f in (tuned, stale))
        assert [s["as"] for s in a["skills"]] == [s["as"] for s in b["skills"]], tuned.name
        assert [s["name"] for s in a["mcp_servers"]] == [
            s["name"] for s in b["mcp_servers"]
        ], tuned.name
        assert [s["source"] for s in a["skills"]] != [s["source"] for s in b["skills"]], (
            f"{tuned.name} and {stale.name} draw the same material, so they are the "
            "same equipping under two labels"
        )


def test_skill_frontmatter_name_is_level_independent() -> None:
    names: dict[str, set[str]] = collections.defaultdict(set)
    for d in _skill_dirs_in_levels():
        front = (d / "SKILL.md").read_text().split("---")[1]
        names[d.name.rsplit("-", 1)[0].removesuffix("-stale")].add(
            yaml.safe_load(front)["name"]
        )
    for family, seen in names.items():
        assert len(seen) == 1, (
            f"{family}: SKILL.md frontmatter `name` differs across levels ({seen}); "
            "the agent would be able to read which level it drew"
        )


# ---------------------------------------------------------------------------
# 4. bench-authored text is clean, in full
# ---------------------------------------------------------------------------


def test_bench_authored_equipping_trips_no_deny_pattern() -> None:
    for f in _bench_files():
        hits = _hits(f.read_text())
        assert not hits, f"{f.relative_to(EQUIPPING)} matches {sorted(set(hits))}"


def test_bench_authored_skills_name_no_study_vocabulary() -> None:
    for f in _bench_files():
        found = sorted(set(m.group(0).lower() for m in META_VOCAB.finditer(f.read_text())))
        assert not found, (
            f"{f.relative_to(EQUIPPING)} names {found}; this file is copied into the "
            "agent's container and would tell it what it is taking part in"
        )


def test_the_provenance_file_ships_in_no_skill_directory() -> None:
    for d in _skill_dirs_in_levels():
        assert not (d / "UPSTREAM.md").exists(), d


# ---------------------------------------------------------------------------
# 5. vendored text reserves no one scenario's vocabulary
# ---------------------------------------------------------------------------


def test_vendored_equipping_leaks_no_single_scenarios_trap() -> None:
    owners = _owner_counts()
    unexpected: list[str] = []
    for d in _skill_dirs_in_levels():
        if (EQUIPPING / "bench") in d.parents:
            continue
        for f in sorted(x for x in d.rglob("*") if x.is_file()):
            for pattern, spec_id in _hits(f.read_text()):
                if owners.get(pattern, len(ALL_SPECS)) > PER_SPEC_OWNERS_MAX:
                    continue  # mechanism vocabulary, see THE DENY-LIST SCOPE
                if (pattern, spec_id) in ALLOWLISTED_VENDOR_HITS:
                    continue
                unexpected.append(f"{f.relative_to(EQUIPPING)}: {pattern!r} ({spec_id})")
    assert not unexpected, (
        "vendored equipping prose reserves a scenario's own trap vocabulary:\n  "
        + "\n  ".join(unexpected)
        + "\nRead each one. Either it is a generic use -- add it to "
        "ALLOWLISTED_VENDOR_HITS with the quoted context -- or the skill names the "
        "trap, and this material cannot equip that scenario."
    )


def test_the_allowlist_is_still_load_bearing() -> None:
    """Every allowlisted hit must still be a real hit. A stale entry would hide
    the next genuine one behind a name that no longer occurs."""
    text = "\n".join(
        f.read_text()
        for d in _skill_dirs_in_levels()
        if (EQUIPPING / "bench") not in d.parents
        for f in d.rglob("*")
        if f.is_file()
    )
    live = set(_hits(text))
    for key in ALLOWLISTED_VENDOR_HITS:
        assert key in live, f"allowlisted hit {key} no longer occurs -- drop it"
