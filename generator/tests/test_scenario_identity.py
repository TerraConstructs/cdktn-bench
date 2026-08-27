"""generator/tests/test_scenario_identity.py — SCENARIO IDENTITY, generator-wide.

specs/SCHEMA.md §0.1 (`workspace_id`), DECISIONS.md Amendment 28 addendum
"identity separation".

THE RULE, in one sentence: the spec `id` is OPERATOR-FACING and may name the
pitfall; every name the AGENT can see must be named for the CURRENT STEP'S GOAL
only. The leak test is one question — *does this name reveal more than this
step's own prompt does?*

WHY THIS MODULE EXISTS SEPARATELY from the two deny-list scans that came before
it. Both of those were written for ONE scenario form and both carried an
exemption for the scenario id, on the same procedural-sounding reasoning:

  * `test_multistep_emission.py` (Amendment 27) scanned `apigw-redeploy`'s
    step-1 surfaces for step-2 vocabulary — and scrubbed `apigw-redeploy` first,
    so its own `redeploy` token could never match the id that IS step 2's verb.
  * `test_workspace_seed.py::TestBrownfieldPromptSurface` (Amendment 28) scanned
    every brownfield spec's `environment/` for mechanism vocabulary — and
    scrubbed `named-resource-replacement` first, so its own `replacement` token
    could never match the id that IS the diagnosis.

Two independent guards, the same blind spot, twice. So the sweep here is:

  * CORPUS-WIDE — every spec, including `_toy/`, not just the one form each
    older module was written for. A future scenario inherits it by existing.
  * EXEMPTION-FREE for the id — nothing is scrubbed except values a VALIDATOR
    has already proven clean (`workspace_id`) and tokens the agent's own prompt
    hands it (proven per entry, below).
  * UNHYPHENATED-AWARE — Amendment 27's sweep grepped `re-deploy` only, which
    is the single reason `apigw-redeploy` survived it. Every separator-bearing
    pattern in `AGENT_IDENTITY_DENY_PATTERNS` matches `-`, `_`, a space, or
    nothing.

The deny-list itself lives in `spec_model.py`, not here, because a VALIDATOR
uses it too: a leaking `workspace_id`/`workspace_title` is refused at spec-load
time rather than noticed by a test three regenerations later.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import gen
from spec_model import AGENT_IDENTITY_DENY_PATTERNS, Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARMS_DIR = REPO_ROOT / "arms"

# Discovered, not listed: a scenario added later is swept automatically, and
# `_toy` is included deliberately — it is a real generated task dir and the
# corpus's own worked example, so an exemption for it would be an exemption for
# the pattern every new scenario is copied from.
ALL_SPEC_PATHS = sorted(
    [p for p in (REPO_ROOT / "specs").glob("*.yaml") if p.name != "split.yaml"]
    + list((REPO_ROOT / "specs" / "_toy").glob("*.yaml"))
)
ALL_SPECS = [load_spec(p) for p in ALL_SPEC_PATHS]

# Machine-generated: transitive package names/versions are not authored text and
# would make any vocabulary scan meaningless noise.
SCAN_EXCLUDE = {"package-lock.json"}

# Phrases that match a deny-list pattern for a reason unrelated to any
# scenario's trap, and that live in the SHARED ARM IMAGE SOURCES
# (`arms/<arm>/environment/**`) rather than in generated text.
# `test_boilerplate_allowlist_is_really_arm_text` proves each one really is arm
# text — it must be findable under `arms/`, i.e. written before any scenario
# consumed it. Keep this minimal: it is the one place a real leak could hide.
ARM_BOILERPLATE = (
    # arms/awscdk/environment/workspace/lib/example-stack.ts, describing what
    # the generator does to the placeholder stack the arm image ships:
    "replaced by the generator",
)


def _agent_visible_files(spec: Spec, arm: str):
    """Every file the agent can read, for one arm, PAIRED WITH ITS SCOPE.

    Yields `(path, foreshadowing)`, where `foreshadowing=True` means "an
    earlier step's agent can reach this, so it may not name a later step".

    Two surfaces, not one (Amendment 27 §5.1's lesson):
      * `environment/` IN FULL — the arm Dockerfile COPYs it into the image, so
        it is present from turn one. The unit that must be read hostilely is
        every byte the Dockerfile COPYs, not the files an author happened to
        write. Always foreshadowing-scoped.
      * THE PROMPT — the root `instruction.md` for a stepless task, each step's
        own `instruction.md` for a multi-step one. Every prompt but the LAST is
        foreshadowing-scoped; the last one is not, because there is nothing
        after it to foreshadow. It is still mechanism-scoped: even the final
        prompt may not name the fix.
    """
    root = gen.task_dir(spec, arm)
    for path in sorted((root / "environment").rglob("*")):
        if path.is_file() and path.name not in SCAN_EXCLUDE:
            yield path, True
    prompts = [p for p in (root / "instruction.md",) if p.is_file()]
    prompts += sorted(root.glob("steps/*/instruction.md"))
    # "All but the last" is only a correct scope if directory order IS step
    # order. It is -- step names are numerically prefixed and validated
    # consecutive (`Spec._step_names_are_consecutive`) -- but asserted rather
    # than assumed, because getting it wrong would silently exempt the FIRST
    # step's prompt from the foreshadowing scan, which is the one file this
    # whole module exists to protect.
    if spec.is_multi_step():
        assert [p.parent.name for p in prompts] == [s.name for s in spec.steps or []]
    for i, path in enumerate(prompts):
        yield path, i < len(prompts) - 1


def _prompt_literals(spec: Spec, arm: str) -> set[str]:
    """Tokens built FROM the scenario id that the agent's own prompt hands it.

    The only admissible reason to scrub a token before a leak scan is that the
    agent is TOLD it — `apigw-redeploy-api` is the REST API's required name and
    step 01's prompt says "named EXACTLY `apigw-redeploy-api`". Such a token
    reveals exactly as much as the prompt does, which is the definition of not
    a leak.

    Derived from the emitted prompt rather than declared in a list, so it
    cannot drift: a token stops being scrubbed the moment the prompt stops
    saying it. A BARE `spec.id` is never matched here (the pattern requires a
    suffix), which is what keeps the id itself inside the scan.
    """
    root = gen.task_dir(spec, arm)
    prompts = [p for p in (root / "instruction.md",) if p.is_file()]
    prompts += sorted(root.glob("steps/*/instruction.md"))
    text = "\n".join(p.read_text(errors="ignore") for p in prompts).lower()
    pattern = re.compile(rf"\b{re.escape(spec.id)}(?:[a-z0-9]+|-[a-z0-9]+)+\b")
    return set(pattern.findall(text))


def _scrub(text: str, spec: Spec, arm: str) -> str:
    """Everything removed before the deny-list runs — and nothing else.

    Three classes, each with its own mechanical justification test below:
      1. `workspace_identity()` — proven clean by a spec VALIDATOR, so scrubbing
         it removes no information the deny-list could have used.
      2. prompt literals — proven present in this arm's own prompt.
      3. arm boilerplate — proven to be text under `arms/`.
    The scenario `id` is deliberately NOT a class.
    """
    out = text.lower()
    wid = spec.workspace_identity().lower()
    out = out.replace(wid, "<workspace-id>").replace(
        wid.replace("-", "_"), "<workspace-id>"
    )
    for literal in sorted(_prompt_literals(spec, arm), key=len, reverse=True):
        out = out.replace(literal, "<prompt-literal>")
    for phrase in ARM_BOILERPLATE:
        out = out.replace(phrase, "<arm-boilerplate>")
    return out


def _spec_id(spec: Spec) -> str:
    """pytest node id: the scenario, so a failure names it."""
    return spec.id


# ---------------------------------------------------------------------------
# 1. THE OPERATOR-FACING ID NEVER REACHES THE AGENT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_spec_id_is_not_stamped_into_any_agent_visible_file(spec: Spec) -> None:
    """The exact, judgment-free half of the rule.

    No regex, no vocabulary: the operator-facing `id` must simply not be
    findable in anything the agent can read, once the workspace identity and
    the prompt's own literals are accounted for. For a scenario whose id is
    already agent-safe this passes trivially (id == workspace_id, so every
    occurrence IS the workspace id). For a scenario that needed to hide its id,
    it is the whole deliverable.
    """
    if spec.workspace_identity() == spec.id:
        pytest.skip(
            f"{spec.id}: id is the agent-visible identity (deny-list-validated), "
            "so its occurrences are workspace-id occurrences"
        )
    for arm in spec.arms.enabled_arms():
        for file, _ in _agent_visible_files(spec, arm):
            scrubbed = _scrub(file.read_text(errors="ignore"), spec, arm)
            assert spec.id not in scrubbed, (
                f"{file.relative_to(REPO_ROOT)} contains the operator-facing "
                f"scenario id {spec.id!r}. environment/ is COPY'd into the "
                f"agent image and instruction.md IS the prompt; this id names "
                f"the pitfall, which is why {spec.workspace_id!r} exists "
                "(SCHEMA.md §0.1)."
            )


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_agent_visible_identity_is_deny_list_clean(spec: Spec) -> None:
    """The schema-side half, pinned against the real spec rather than a fixture.

    Both agent-visible identity fields — the NAME (`workspace_id`, defaulting
    to `id`) and the SENTENCE (`workspace_title`, defaulting to `title`) — must
    survive the deny-list. Asserted here as well as in the validator so the
    corpus itself is the evidence: this is what makes scrubbing
    `workspace_identity()` in `_scrub` a safe operation rather than a second
    exemption.
    """
    assert not spec.identity_leaks(spec.workspace_identity())
    assert not spec.identity_leaks(spec.workspace_header())


# ---------------------------------------------------------------------------
# 2. THE VOCABULARY SWEEP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_agent_visible_files_carry_no_trap_or_foreshadowing_vocab(
    spec: Spec,
) -> None:
    """The hostile regex sweep, over every agent-visible byte of every task.

    Two vocabularies at once: the GLOBAL one (`AGENT_IDENTITY_DENY_PATTERNS` —
    mechanism, foreshadowing grammar, and benchmark meta-vocabulary, all with
    unhyphenated variants) and this scenario's OWN `agent_deny_vocab`, declared
    in its spec so the words that would give a trap away are reviewed in the
    same file as the trap.
    """
    for arm in spec.arms.enabled_arms():
        for file, foreshadowing in _agent_visible_files(spec, arm):
            leaked = spec.identity_leaks(
                _scrub(file.read_text(errors="ignore"), spec, arm),
                foreshadowing=foreshadowing,
            )
            assert not leaked, (
                f"{file.relative_to(REPO_ROOT)} ({spec.id}/{arm}) names "
                f"{leaked}. Everything under environment/ is COPY'd into the "
                "agent image and instruction.md IS the prompt: the agent may be "
                "asked for the CHANGE, never handed the mechanism or the next "
                "step (SCHEMA.md §0.1, Amendment 28)."
            )


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_identity_leakage_is_arm_symmetric(spec: Spec) -> None:
    """Asymmetry is the part that corrupts the MEASUREMENT, so it is asserted
    separately rather than riding on the scan above.

    Both leaks this module was written for were arm-asymmetric in the same
    direction — present on the arms whose entry file the generator stamps,
    absent on the arm whose entry file is hand-written — and two arms handed a
    hint the third lacks does not merely make a task easier, it biases the
    cross-arm comparison the whole benchmark produces. Compared as SETS so it
    still fails loudly if a future deny-list gap lets one token through
    uniformly.
    """
    per_arm: dict[str, set[str]] = {}
    for arm in spec.arms.enabled_arms():
        found: set[str] = set()
        for file, foreshadowing in _agent_visible_files(spec, arm):
            found.update(
                spec.identity_leaks(
                    _scrub(file.read_text(errors="ignore"), spec, arm),
                    foreshadowing=foreshadowing,
                )
            )
        per_arm[arm] = found
    distinct = {frozenset(v) for v in per_arm.values()}
    assert len(distinct) == 1, (
        f"{spec.id}: deny-list vocabulary differs per arm: "
        f"{ {a: sorted(v) for a, v in per_arm.items()} }"
    )


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_the_workspace_identity_is_stamped_identically_on_every_arm(
    spec: Spec,
) -> None:
    """The positive half of arm symmetry: whatever identity IS visible must be
    the same string everywhere it appears.

    `terraconstructs` is the only arm that stamps the identity as a value (the
    ScenarioStack construct id, the gridUUID, and therefore
    `cdktf.out/stacks/<id>/`), so the count legitimately differs per arm. What
    must NOT differ is the string: an arm stamping a different name would mean
    the three arms are not the same workspace, which is the premise of every
    cross-arm number this repo publishes.
    """
    wid = spec.workspace_identity()
    seen: dict[str, set[str]] = {}
    pattern = re.compile(r'ScenarioStack\(app, "([^"]+)"|gridUUID: "([^"]+)"')
    for arm in spec.arms.enabled_arms():
        names: set[str] = set()
        for file, _ in _agent_visible_files(spec, arm):
            for a, b in pattern.findall(file.read_text(errors="ignore")):
                names.add(a or b)
        seen[arm] = names
    for arm, names in seen.items():
        assert names <= {wid, "ScenarioStack"}, (
            f"{spec.id}/{arm} stamps construct identities {sorted(names)}, "
            f"which is not the declared workspace identity {wid!r}"
        )


# ---------------------------------------------------------------------------
# 3. THE SHARED ARM IMAGE NAMES NO SCENARIO
# ---------------------------------------------------------------------------


def test_arm_image_sources_name_no_scenario() -> None:
    """`arms/<arm>/environment/**` is byte-copied into EVERY task dir, so a
    comment there that names one scenario ships that name to all the others —
    and, worse, to that scenario's own agent.

    Five arm files used to do exactly this (`arms/awscdk/environment/Dockerfile`
    and `arms/terraconstructs/environment/Dockerfile` explaining why python3 is
    installed "for apigw-redeploy"; `arms/hcl-raw/.../provider.tf` ×3 lines;
    `mirror-src/main.tf` and the arm's own preflight stack), which
    put the string `redeploy` — this scenario's step-2 verb — inside the image
    of the very scenario it names, on all three arms, where it would have read
    as PROVEN BOILERPLATE to any allowlist-honesty check: it does appear under
    a greenfield control, because it appears under every control. Constant
    across scenarios is not the same as carrying no information about one.

    Fixed by describing the PROPERTY instead of the scenario ("any spec with
    verifier.live_check.enabled: true"); pinned here so it stays fixed.
    """
    ids = sorted({s.id for s in ALL_SPECS}, key=len, reverse=True)
    offenders: list[str] = []
    for path in sorted(ARMS_DIR.glob("*/environment/**/*")):
        if not path.is_file() or path.name in SCAN_EXCLUDE:
            continue
        text = path.read_text(errors="ignore").lower()
        for spec_id in ids:
            if spec_id in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {spec_id}")
    assert not offenders, (
        "shared arm image sources name specific scenarios:\n  "
        + "\n  ".join(offenders)
        + "\nThese files are byte-copied into every task's environment/, which "
        "is COPY'd into the agent image. Describe the property the arm needs, "
        "not the scenario that first needed it."
    )


# ---------------------------------------------------------------------------
# 4. THE ALLOWLISTS ARE HONEST
# ---------------------------------------------------------------------------


def test_boilerplate_allowlist_is_really_arm_text() -> None:
    """Keeps `ARM_BOILERPLATE` honest: every entry must be findable under
    `arms/*/environment/**`, i.e. text written for the ARM before any scenario
    consumed it, rather than a scenario's own words smuggled onto the allowlist
    to silence the scan."""
    corpus = "\n".join(
        p.read_text(errors="ignore")
        for p in ARMS_DIR.glob("*/environment/**/*")
        if p.is_file() and p.name not in SCAN_EXCLUDE
    ).lower()
    for phrase in ARM_BOILERPLATE:
        assert phrase in corpus, (
            f"{phrase!r} is allowlisted as arm boilerplate but does not appear "
            "under arms/*/environment/ — it is scenario-specific text and must "
            "not be scrubbed"
        )


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_prompt_literal_scrub_only_ever_removes_prompt_content(spec: Spec) -> None:
    """Keeps the derived prompt-literal allowlist honest.

    Every token `_prompt_literals` scrubs must (a) really occur in that arm's
    own prompt and (b) be strictly longer than the bare id — the bare id is
    never scrubbable, which is the invariant that makes test 1 above meaningful.
    """
    for arm in spec.arms.enabled_arms():
        for literal in _prompt_literals(spec, arm):
            assert literal != spec.id
            assert literal.startswith(spec.id)
            prompt = "\n".join(
                p.read_text(errors="ignore")
                for p, _ in _agent_visible_files(spec, arm)
                if p.name == "instruction.md"
            ).lower()
            assert literal in prompt


# ---------------------------------------------------------------------------
# 5. THE REGRESSIONS — reconstructed pre-fix bytes, required to FAIL
# ---------------------------------------------------------------------------

# The exact stamps the generator used to emit, per scenario, as the round-2
# verifier found them on disk. Each is required to be rejected by the sweep;
# together they are the proof that the fix is a fix and not a rename.
PRE_FIX_STAMPS = {
    "named-resource-replacement": [
        # tasks/anchor/named-resource-replacement-terraconstructs/environment/app/main.ts:19,21
        'new ScenarioStack(app, "named-resource-replacement", {',
        '  gridUUID: "named-resource-replacement",',
        # .../named-resource-replacement-awscdk/environment/workspace/bin/app.ts:7
        (
            " * Generated entrypoint -- generator/gen.py, from "
            "specs/named-resource-replacement.yaml."
        ),
        # .../named-resource-replacement-terraconstructs/environment/preflight.sh:72
        'STACK_DIR="cdktf.out/stacks/named-resource-replacement"',
    ],
    "apigw-redeploy": [
        # tasks/anchor/apigw-redeploy-terraconstructs/environment/app/main.ts:19,21
        'new ScenarioStack(app, "apigw-redeploy", {',
        '  gridUUID: "apigw-redeploy",',
        # .../apigw-redeploy-hcl-raw/environment/workspace/main.tf:3
        "# Generated skeleton -- generator/gen.py, from specs/apigw-redeploy.yaml.",
        # .../apigw-redeploy-terraconstructs/environment/preflight.sh:45
        'OUT_FILE="cdktf.out/stacks/apigw-redeploy/cdk.tf.json"',
    ],
}


@pytest.mark.parametrize("spec_id", sorted(PRE_FIX_STAMPS), ids=lambda s: s)
def test_the_sweep_would_have_caught_the_pre_fix_stamping(spec_id: str) -> None:
    """A deny-list nobody ever saw fail is a deny-list nobody can trust.

    Replays the literal bytes that were on disk at HEAD and requires the sweep
    to reject every one of them — through the deny-list, the id rule, or both.
    Run this against the pre-fix `_brownfield_scrub`/`ACCEPTED_RESIDUALS` and it
    goes red, which is the point: the exemptions cannot be reintroduced without
    this test noticing.
    """
    spec = next(s for s in ALL_SPECS if s.id == spec_id)
    arm = spec.arms.enabled_arms()[0]
    for stamp in PRE_FIX_STAMPS[spec_id]:
        scrubbed = _scrub(stamp, spec, arm)
        rejected = bool(spec.identity_leaks(scrubbed)) or spec.id in scrubbed
        assert rejected, (
            f"the sweep accepts {stamp!r}, which was really emitted into "
            f"{spec_id}'s agent image before SCHEMA.md §0.1's workspace_id. "
            "An exemption has been reintroduced."
        )


def test_no_deny_list_pattern_requires_a_separator() -> None:
    """THE `redeploy` LESSON, as a mechanical invariant.

    Amendment 27's foreshadowing sweep grepped `re-deploy`. `apigw-redeploy` is
    the same word with the hyphen removed, so the sweep read the scenario's own
    id — stamped into every step-1 skeleton header and into the terraconstructs
    `gridUUID` — and saw nothing. One optional-quantifier away from catching it.

    So: no pattern in either class may make its separator mandatory. Every
    `[ _-]` must be `[ _-]?`, which is what makes `redeploy`, `re-deploy`,
    `re_deploy` and `re deploy` all one token to this deny-list.
    """
    mandatory = [p for p in AGENT_IDENTITY_DENY_PATTERNS if re.search(r"\[ _-\](?!\?)", p)]
    assert not mandatory, (
        f"these patterns only match a SEPARATED spelling: {mandatory}. Make the "
        "separator optional (`[ _-]?`) — an unhyphenated variant is exactly how "
        "`apigw-redeploy` passed the sweep that was written to catch it."
    )


@pytest.mark.parametrize("spec", ALL_SPECS, ids=_spec_id)
def test_the_deny_list_still_rejects_the_words_it_names(spec: Spec) -> None:
    """Sanity: every global pattern must actually match something it claims to.

    Cheap protection against a pattern that was edited into never matching
    (a stray anchor, a broken character class) and therefore silently stopped
    guarding anything — the failure mode a deny-list has that an assertion
    does not.
    """
    del spec  # parametrized only so a failure names the corpus it protects
    probes = {
        r"create[ _-]?before[ _-]?destroy": "create_before_destroy",
        r"\bre[ _-]?deploy(s|ed|ing|ment|ments)?\b": "redeploy the stage",
        r"\breplacements?\b": "forces replacement",
        r"\bstep[ _-]?(2|two|02)\b": "in step 2 you will",
        r"\bday[ _-]?(2|two)\b": "a day-2 iteration",
    }
    for pattern, probe in probes.items():
        assert pattern in AGENT_IDENTITY_DENY_PATTERNS, pattern
        assert re.search(pattern, probe), (pattern, probe)
