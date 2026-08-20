"""generator/tests/test_multistep_emission.py -- the multi-step emission
contract (specs/SCHEMA.md §2.6/§8.3, DECISIONS.md Amendments 26/27).

Two kinds of test live here, deliberately not separated into two files:

  1. **Hostile reads of the REAL generated task dirs.** The
     no-foreshadowing property is a property of the bytes actually shipped,
     not of the generator function that produced them, so these read
     `tasks/anchor/apigw-redeploy-*/` off disk. A spec edit that reintroduces
     foreshadowing turns this suite red instead of shipping.
  2. **Pure-function tests of the emitter**, including a synthetic spec that
     exercises `pre_invoke.deploy_prior` -- the one declarative harness action
     no real spec uses today (`apigw-redeploy` opts into agent-deploys in both
     steps; docs/prompt-decomposition-audit.md §3). Without this, that code
     path would ship unexercised.

Offline and toolchain-free: no docker, no AWS, no npm.
"""

from __future__ import annotations

import copy
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import (  # noqa: E402
    ARM_DIRNAME,
    build_instruction_md,
    build_step_pre_invoke_sh,
    build_static_tiers_sh,
    build_steps_toml,
    build_task_toml,
    instruction_rel_paths,
    task_dir,
    write_tests_dir,
)
from spec_model import Spec, load_spec  # noqa: E402

SPEC_PATH = REPO_ROOT / "specs" / "apigw-redeploy.yaml"
ARMS = ("awscdk", "hcl_raw", "terraconstructs")


@pytest.fixture(scope="module")
def spec() -> Spec:
    return load_spec(SPEC_PATH)


# ---------------------------------------------------------------------------
# 1. The no-foreshadowing property, read off the real generated task dirs
# ---------------------------------------------------------------------------

# The leak deny-lists, split into two classes because they have genuinely
# different scopes.
#
# CONTENT tokens name step 2's SUBSTANCE. They may not appear anywhere a step-1
# reader could reach: the step-1 prompt, step 1's own tests/, or the shared
# tests/. (Step 1's tests are not uploaded until step 1's VERIFICATION, i.e.
# after its agent -- so this is defence in depth against a Harbor ordering
# change, not a live hole. docs/prompt-decomposition-audit.md §6.)
CONTENT_TOKENS = (
    "/status",
    "mockintegration",
    "mock integration",
    "mock-integration",
    '"routes": 3',
    '"routes":3',
    '{"status": "ok"',
)

# TEMPORAL tokens are the "then / later / you will" grammar of foreshadowing.
# They are banned in the PROMPT and in `environment/` (both of which the step-1
# agent reads) but legitimate in generator/meta commentary, which explains the
# mechanism rather than the task -- a tests/README that says "readable by a
# later step's agent" is documentation of Harbor's upload ordering, not a hint.
#
# The "day-2 / iteration" cluster was added after a verifier found the scenario
# TITLE stamped into the agent's own skeleton files (SCHEMA.md §0.1): the
# earlier list caught only "re-deploy" out of that leak, so the signal was one
# token wide. NOTE "modify" is deliberately NOT a token -- the arm skeletons and
# the step-1 ownership note both legitimately say "do not modify provider.tf".
TEMPORAL_TOKENS = (
    "step 2",
    "step 02",
    "second deploy",
    "re-deploy",
    "redeploy",
    "later",
    "afterwards",
    "will change",
    "change request",
    "revision 2",
    "for now",
    "next step",
    "another route",
    "third route",
    "modification",
    "prescribed",
    "day-2",
    "day 2",
    "day-two",
    "iteration",
    "subsequent",
    "follow-up",
    "second apply",
)

# KNOWN, ACCEPTED RESIDUAL (docs/prompt-decomposition-audit.md §6): the REST
# API's own required name is `apigw-redeploy-api`, and the spec id
# `apigw-redeploy` appears in every generated file's header. Both contain the
# substring "redeploy". The name is load-bearing -- live_check.py discovers the
# deployed API by it, and every reference/broken fixture writes it -- and it
# reveals no step-2 CONTENT (not the route, not the integration type, not that
# a second prompt is coming; "redeploy" is ordinary API Gateway vocabulary).
# Stripped before scanning so the scan stays sharp instead of being disabled.
ACCEPTED_RESIDUALS = ("apigw-redeploy-api", "apigw-redeploy")

# ARM BOILERPLATE residuals, scrubbed ONLY from the `environment/` scan below.
# These phrases live in the shared arm image sources (arms/<arm>/environment/**)
# and are copied verbatim into every scenario's task dir, this one included.
# They are commentary about the ARM, written before any scenario existed, so
# they cannot encode this scenario's arc. `test_environment_boilerplate_is_
# really_boilerplate` proves that claim mechanically -- each phrase must also
# appear under a STEPLESS spec's environment/, or the allowlist entry is
# rejected. Keep this list minimal: it is the one place a real leak could hide.
ENVIRONMENT_BOILERPLATE = (
    # arms/*/environment/Dockerfile, comment on a pre-installed tool:
    "for later task slices",
)

# `environment/` files excluded from the byte scan: machine-generated lockfiles
# whose transitive package names/versions are not authored text (npm writes
# them) and would make the deny-list scan meaningless noise.
ENVIRONMENT_SCAN_EXCLUDE = {"package-lock.json"}


def _scrub(text: str) -> str:
    out = text.lower()
    for residual in ACCEPTED_RESIDUALS:
        out = out.replace(residual, "<scenario-id>")
    return out


def _scrub_environment(text: str) -> str:
    out = _scrub(text)
    for phrase in ENVIRONMENT_BOILERPLATE:
        out = out.replace(phrase.lower(), "<arm-boilerplate>")
    return out


def _leaks_env(text: str) -> list[str]:
    scrubbed = _scrub_environment(text)
    return [tok for tok in CONTENT_TOKENS + TEMPORAL_TOKENS if tok.lower() in scrubbed]


def _environment_files(spec: Spec, arm: str):
    root = task_dir(spec, arm) / "environment"
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in ENVIRONMENT_SCAN_EXCLUDE:
            yield path


def _leaks(text: str, tokens: tuple[str, ...]) -> list[str]:
    scrubbed = _scrub(text)
    return [tok for tok in tokens if tok.lower() in scrubbed]


def _step_names(spec: Spec) -> list[str]:
    return [s.name for s in spec.steps or []]


def test_apigw_redeploy_is_multi_step(spec: Spec) -> None:
    """The pilot decomposition is in place -- everything below assumes it."""
    assert spec.is_multi_step()
    assert _step_names(spec) == ["01-initial-deploy", "02-change-request"]


def test_step_one_instruction_leaks_nothing_about_step_two(spec: Spec) -> None:
    """THE test this whole slice exists for.

    Reads the generated step-1 prompt for every arm as a hostile reader would
    and requires that no step-2 vocabulary appears anywhere in it -- body,
    language line, ownership note, trailer or JSON fence.
    """
    first = (spec.steps or [])[0]
    for arm in ARMS:
        path = task_dir(spec, arm) / "steps" / first.name / "instruction.md"
        text = path.read_text()
        leaked = _leaks(text, CONTENT_TOKENS + TEMPORAL_TOKENS)
        assert not leaked, (
            f"{path.relative_to(REPO_ROOT)} leaks step-2 intent: {leaked}. "
            "A step-1 prompt that names the day-2 change measures day-1 "
            "authoring with perfect foreknowledge -- the trap never fires "
            "(docs/prompt-decomposition-audit.md §0)."
        )


def test_step_one_environment_leaks_nothing_about_step_two(spec: Spec) -> None:
    """The companion to the prompt test — and the one that was missing.

    `environment/` is not metadata: every arm Dockerfile `COPY`s it into the
    agent image (`COPY workspace/main.tf ./main.tf`, `COPY workspace/{bin,lib}`,
    `COPY app/main.ts`), so the skeleton the step-1 agent opens first is prompt
    surface. Amendment 26 §7 rule 2 / multistep-trial-investigation.md §5 rule
    2: never place later-step material in `environment/` — that IS the image
    the agent lives in.

    Regression pinned: `generator/gen.py` used to stamp `spec.title` into all
    five skeleton headers, so `apigw-redeploy`'s whole-arc title ("deploy,
    confirm, modify, re-deploy (day-2 iteration)") shipped inside the agent's
    own `main.tf` line 1 while the step-1 prompt was clean. `workspace_title`
    (SCHEMA.md §0.1) is the fix; this test is what keeps it fixed.
    """
    for arm in ARMS:
        for path in _environment_files(spec, arm):
            leaked = _leaks_env(path.read_text(errors="ignore"))
            assert not leaked, (
                f"{path.relative_to(REPO_ROOT)} leaks step-2 intent: {leaked}. "
                "environment/ is COPY'd into the agent image — this text is "
                "read by the step-1 agent (SCHEMA.md §0.1)."
            )


def test_environment_boilerplate_is_really_boilerplate() -> None:
    """Keeps ENVIRONMENT_BOILERPLATE honest.

    Every allowlisted phrase must also occur under a STEPLESS spec's
    `environment/`, which proves it is shared arm-image text rather than this
    scenario's own words smuggled onto the allowlist to silence the scan above.
    """
    control = load_spec(REPO_ROOT / "specs" / "sfn-jsonata.yaml")
    assert not control.is_multi_step(), "control spec must be stepless"
    corpus = "\n".join(
        path.read_text(errors="ignore")
        for arm in ("awscdk", "hcl_raw")
        for path in _environment_files(control, arm)
    ).lower()
    for phrase in ENVIRONMENT_BOILERPLATE:
        assert phrase.lower() in corpus, (
            f"{phrase!r} is allowlisted as arm boilerplate but does not appear "
            f"in the stepless control spec {control.id!r}'s environment/ — it "
            "is scenario-specific text and must not be scrubbed"
        )


def test_step_one_oracle_leaks_nothing_about_step_two(spec: Spec) -> None:
    """Same hostile read of step 1's own tests/ tree.

    Defence in depth: Harbor uploads a step's tests/ at that step's
    VERIFICATION (after its agent), so this is not visible during step 1
    today. It is kept clean so the property holds by construction rather than
    by a Harbor ordering detail a future release could change.
    """
    first = (spec.steps or [])[0]
    # policy.{rego,guard} are the shared, spec-level tier-1 bundles -- they
    # describe deployment/depends_on coverage generically and are byte-copied
    # into every step, so they are excluded from this particular read.
    exempt = {"policy.rego", "policy.guard"}
    for arm in ARMS:
        tests = task_dir(spec, arm) / "steps" / first.name / "tests"
        for path in sorted(tests.rglob("*")):
            if not path.is_file() or path.name in exempt:
                continue
            leaked = _leaks(path.read_text(errors="ignore"), CONTENT_TOKENS)
            assert not leaked, (
                f"{path.relative_to(REPO_ROOT)} mentions step-2 material: {leaked}"
            )


def test_shared_root_tests_holds_no_oracle(spec: Spec) -> None:
    """DECISIONS.md Amendment 26 §7 rule 1.

    Harbor uploads the shared tests/ during EVERY step's verification and only
    empties /tests at the start of the NEXT step's verification, so anything
    step-specific here is readable inside a later step's agent phase.
    """
    for arm in ARMS:
        shared = task_dir(spec, arm) / "tests"
        names = sorted(p.name for p in shared.iterdir() if p.is_file())
        assert names == ["README.md"], (
            f"{shared.relative_to(REPO_ROOT)} must hold only the step-agnostic "
            f"README, got {names}"
        )
        leaked = _leaks(shared.joinpath("README.md").read_text(), CONTENT_TOKENS)
        assert not leaked, f"the shared tests README mentions step-2 material: {leaked}"


def test_no_root_instruction_md(spec: Spec) -> None:
    """A multi-step task must have none.

    Harbor sets `Task.instruction = ""` for a steps task, and
    gates/equipping.py folds steps/*/instruction.md into the equipping hash
    ONLY in the absence of a root one -- a leftover root instruction.md would
    silently revert the hash to the single-step key for text no agent saw.
    """
    for arm in ARMS:
        assert not (task_dir(spec, arm) / "instruction.md").exists()


def test_every_step_has_its_own_prompt_and_oracle(spec: Spec) -> None:
    for arm in ARMS:
        root = task_dir(spec, arm)
        for step in spec.steps or []:
            step_dir = root / "steps" / step.name
            assert (step_dir / "instruction.md").is_file()
            assert (step_dir / "tests" / "test.sh").is_file()
            assert (step_dir / "tests" / "static_tiers.sh").is_file()
            assert (step_dir / "tests" / "_assert_lib.sh").is_file()


def test_apigw_redeploy_emits_no_pre_invoke(spec: Spec) -> None:
    """The agent-deploys opt-in (Amendment 26 §2) is visible on disk.

    Also guards the workspace carry-over the opt-in depends on: Harbor uploads
    steps/<n>/workdir/ only if it exists, so the ABSENCE of that directory is
    what guarantees step 02's agent opens the workspace its step-01 self left.
    """
    for arm in ARMS:
        root = task_dir(spec, arm)
        for step in spec.steps or []:
            assert not (root / "steps" / step.name / "pre_invoke").exists()
            assert not (root / "steps" / step.name / "workdir").exists()
        toml_text = (root / "task.toml").read_text()
        assert "[pre_invoke]" not in toml_text


def test_final_step_oracle_is_byte_identical_to_the_full_suite(spec: Spec) -> None:
    """The last step runs the FULL tier suite, so a multi-step scenario's
    terminal grading is what the single-step form graded.

    Compared against a freshly rendered `step=None` script rather than against
    git history, so this keeps holding as the generator evolves. Only the
    generated STEP header comment may differ.
    """
    final = (spec.steps or [])[-1]
    for arm in ARMS:
        stepped = build_static_tiers_sh(spec, arm, final)
        full = build_static_tiers_sh(spec, arm, None)
        strip = lambda text: "\n".join(  # noqa: E731
            line for line in text.splitlines() if not line.startswith("# ")
        )
        assert strip(stepped) == strip(full)


def test_non_final_step_oracle_is_a_strict_subset(spec: Spec) -> None:
    first, final = (spec.steps or [])[0], (spec.steps or [])[-1]
    first_names = set(spec.step_assert_names(first))
    final_names = set(spec.step_assert_names(final))
    assert first_names < final_names
    assert "mock-integration-wired" in final_names - first_names, (
        "the assert whose own description says 'backing the day-2 /status "
        "route' must be step-2-only"
    )


def test_task_toml_declares_the_engine_contract(spec: Spec) -> None:
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        assert cfg["multi_step_reward_strategy"] == "final", (
            "Amendment 26 §3: `mean` lets a trial aborted after step 1 outscore "
            "one that ran both steps and failed the second"
        )
        steps = cfg["steps"]
        assert [s["name"] for s in steps] == _step_names(spec)
        assert steps[0]["min_reward"] == 1.0, "step 2 must not fire unless step 1 is green"
        assert "min_reward" not in steps[-1], "the final step has no successor to gate"
        for s in steps:
            assert s["agent"]["timeout_sec"] == 3600.0
            assert s["verifier"]["env"]["SPEC_LIVE_CHECK_ENABLED"] == "true"


def test_instruction_rel_paths_matches_disk(spec: Spec) -> None:
    rels = [rel for rel, _step in instruction_rel_paths(spec)]
    assert rels == [f"steps/{n}/instruction.md" for n in _step_names(spec)]
    for arm in ARMS:
        for rel in rels:
            assert (task_dir(spec, arm) / rel).is_file()


def test_step_prompts_carry_the_spec_level_standing_constraints(spec: Spec) -> None:
    """Sessions are fresh per step (Amendment 26 §1), so constraints stated
    once at step 1 would be invisible to every later step's agent."""
    marker = "/cdktn-bench-task/"
    for arm in ARMS:
        for step in spec.steps or []:
            text = (task_dir(spec, arm) / "steps" / step.name / "instruction.md").read_text()
            assert marker in text
            assert "agent-output.json" in text


def test_non_final_steps_have_a_reference_solution(spec: Spec) -> None:
    """The new proof obligation the decomposition creates -- an intermediate
    oracle nothing can satisfy aborts every trial at the min_reward gate."""
    for arm in ARMS:
        root = task_dir(spec, arm)
        for step in (spec.steps or [])[:-1]:
            assert (root / "steps" / step.name / "solution" / "solve.sh").is_file()
        # The FINAL step's reference is the task-root solution/solve.sh.
        assert not (root / "steps" / (spec.steps or [])[-1].name / "solution").exists()
        assert (root / "solution" / "solve.sh").is_file()


def test_solution_corpus_still_covers_every_catch(spec: Spec) -> None:
    """The decomposition must not have lost a negative fixture."""
    for arm in ARMS:
        broken = task_dir(spec, arm) / "solution" / "broken"
        for catch in spec.catches:
            if arm not in catch.applies_to:
                continue
            assert (broken / catch.name / "solve.sh").is_file(), (
                f"{arm}: missing negative fixture for catch {catch.name!r}"
            )


# ---------------------------------------------------------------------------
# 2. Emitter unit tests, incl. the deploy_prior path no real spec uses
# ---------------------------------------------------------------------------


def _spec_with_deploy_prior() -> Spec:
    """apigw-redeploy, minimally mutated to exercise `pre_invoke.deploy_prior`.

    Built from the real spec rather than a from-scratch fixture so it stays
    valid as the schema evolves; the mutation is exactly the two fields the
    feature needs.
    """
    raw = yaml.safe_load(SPEC_PATH.read_text())
    raw = copy.deepcopy(raw)
    for arm in ARMS:
        raw["instruction"]["per_arm"][arm]["output_contract"]["deploy_command"] = (
            f"echo deploying-{arm} && terraform apply -input=false -auto-approve"
        )
    raw["steps"][1]["pre_invoke"] = {"deploy_prior": True, "timeout_sec": 2400.0}
    return Spec.model_validate(raw)


def test_deploy_prior_emits_a_credentialed_step_script() -> None:
    spec = _spec_with_deploy_prior()
    step = (spec.steps or [])[1]
    script = build_step_pre_invoke_sh(spec, "hcl_raw", step)

    assert script.startswith("#!/usr/bin/env bash\n")
    assert "terraform apply -input=false -auto-approve" in script
    # ScriptRunner starts the script in /pre_invoke/, not the workspace.
    assert "cd /app/project" in script
    # ScriptRunner.run(output_file_name="placeholder.json") RAISES if the file
    # is absent, which would abort the step.
    assert "/logs/pre_invoke/placeholder.json" in script


def test_deploy_prior_sizes_the_task_level_pre_invoke_timeout() -> None:
    """Amendment 26 draft addendum (a): the per-step pre_invoke inherits the
    TASK-level timeout, whose aws-bench default (600 s) a real deploy
    exceeds."""
    spec = _spec_with_deploy_prior()
    lines = build_steps_toml(spec, spec.verifier.live_check)
    rendered = "\n".join(lines)
    assert "[pre_invoke]" in rendered
    assert "timeout_sec = 2400.0" in rendered


def test_deploy_prior_requires_a_declared_deploy_command() -> None:
    """The generator refuses to guess a real deploy command."""
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][1]["pre_invoke"] = {"deploy_prior": True}
    with pytest.raises(ValueError, match="deploy_command"):
        Spec.model_validate(raw)


def test_deploy_prior_is_refused_on_the_first_step() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    for arm in ARMS:
        raw["instruction"]["per_arm"][arm]["output_contract"]["deploy_command"] = "true"
    raw["steps"][0]["pre_invoke"] = {"deploy_prior": True}
    with pytest.raises(ValueError, match="FIRST step"):
        Spec.model_validate(raw)


def test_a_dangling_deploy_command_is_refused() -> None:
    """A real deploy command nothing ever runs is a trap for the next reader."""
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["instruction"]["per_arm"]["hcl_raw"]["output_contract"]["deploy_command"] = "true"
    with pytest.raises(ValueError, match="no step declares pre_invoke.deploy_prior"):
        Spec.model_validate(raw)


def test_final_step_must_not_narrow_the_oracle() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][-1]["oracle"] = {"structural_asserts": ["rest-api-exists"]}
    with pytest.raises(ValueError, match="must OMIT"):
        Spec.model_validate(raw)


def test_non_final_step_must_narrow_the_oracle() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    del raw["steps"][0]["oracle"]["structural_asserts"]
    with pytest.raises(ValueError, match="must name"):
        Spec.model_validate(raw)


def test_unknown_assert_name_is_refused() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][0]["oracle"]["structural_asserts"].append("no-such-assert")
    with pytest.raises(ValueError, match="no-such-assert"):
        Spec.model_validate(raw)


def test_one_step_is_refused() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"] = raw["steps"][:1]
    del raw["steps"][0]["oracle"]["structural_asserts"]
    with pytest.raises(ValueError, match="at least 2"):
        Spec.model_validate(raw)


def test_min_reward_is_refused_on_the_final_step() -> None:
    """Same treatment `oracle.structural_asserts` already gets.

    `min_reward` gates the NEXT step's prompt, so on the last step it has no
    successor to gate and `build_steps_toml` drops it (`if not is_final`). A
    schema that ACCEPTS a key the emitter silently discards reads, to the next
    spec author, as a gate that exists. Rejected at load instead.
    """
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][-1]["min_reward"] = 1.0
    with pytest.raises(ValueError, match="must OMIT min_reward"):
        Spec.model_validate(raw)


def test_min_reward_is_still_accepted_on_a_non_final_step() -> None:
    """The rejection above must not have swallowed the legitimate case."""
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][0]["min_reward"] = 0.0
    spec = Spec.model_validate(raw)
    rendered = "\n".join(build_steps_toml(spec, spec.verifier.live_check))
    assert "min_reward = 0.0" in rendered


def test_step_names_must_be_consecutive() -> None:
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][1]["name"] = "05-change-request"
    with pytest.raises(ValueError, match="consecutive"):
        Spec.model_validate(raw)


def test_per_step_language_line_overrides_the_spec_level_one(spec: Spec) -> None:
    """Leak 4's fix: the arm-specific construct hint for the day-2 integration
    type must appear at step 02 and nowhere earlier."""
    first, final = (spec.steps or [])[0], (spec.steps or [])[-1]
    assert "MockIntegration" not in build_instruction_md(spec, "awscdk", first)
    assert "MockIntegration" in build_instruction_md(spec, "awscdk", final)
    # ... and not via the spec-level fallback either.
    assert "MockIntegration" not in spec.instruction.per_arm.awscdk.language_line


def test_multi_step_spec_without_workspace_title_is_refused() -> None:
    """SCHEMA.md §0.1, the schema-level half of the environment/ leak fix.

    Omission must be an error, not a silent fallback to `title` — that
    fallback is exactly what stamped "modify, re-deploy (day-2 iteration)"
    into the step-1 agent's own main.tf.
    """
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw.pop("workspace_title")
    with pytest.raises(ValueError, match="workspace_title"):
        Spec.model_validate(raw)


def test_workspace_title_is_refused_on_a_stepless_spec() -> None:
    """The other direction: a single-step spec keeps stamping `title`, so a
    `workspace_title` there would be an inert rename that silently forfeits the
    byte-identity guarantee for existing task dirs."""
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw.pop("steps")
    raw["verifier"]["live_check"].pop("steps", None)
    with pytest.raises(ValueError, match="workspace_title"):
        Spec.model_validate(raw)


def test_skeletons_use_workspace_title_not_title(spec: Spec) -> None:
    """Pins the five interpolation sites (gen.py:331/378/410/472/548).

    Asserted on the emitter functions, not just on disk, so a future skeleton
    template that reintroduces `{spec.title}` fails even before regeneration.
    """
    from gen import (  # noqa: PLC0415
        awscdk_bin_app_ts,
        awscdk_stack_skeleton,
        hcl_raw_main_tf,
        terraconstructs_main_ts,
        terraconstructs_stack_skeleton,
    )

    assert spec.workspace_header() == "API Gateway REST API (live)"
    assert spec.workspace_header() != spec.title
    for fn in (
        awscdk_bin_app_ts,
        awscdk_stack_skeleton,
        hcl_raw_main_tf,
        terraconstructs_main_ts,
        terraconstructs_stack_skeleton,
    ):
        text = fn(spec)
        assert spec.workspace_header() in text, fn.__name__
        assert spec.title not in text, (
            f"{fn.__name__} still stamps the whole-arc `title` into "
            "environment/ — see SCHEMA.md §0.1"
        )


def _spec_with_step_one_live_check_off(*, hand_authored: bool) -> Spec:
    """apigw-redeploy with step 01 opting OUT of the spec-level live check.

    No real spec reaches this today (both apigw-redeploy steps are
    live-checked), which is exactly why the emitter branch it exercises needs a
    test of its own.
    """
    raw = copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))
    raw["steps"][0]["oracle"]["live_check"] = {"enabled": False}
    spec = Spec.model_validate(raw)
    if not hand_authored:
        # `hand_authored: false` alongside a spec-level `enabled: true` is
        # refused at the schema level (it would ship the generated
        # not-implemented stub as the scenario's live oracle), so the
        # generator-written case is built by mutating the loaded model rather
        # than the YAML.
        spec.verifier.live_check.hand_authored = False
    return spec


def test_opted_out_step_deletes_a_GENERATED_live_check(tmp_path) -> None:
    """The legitimate half of the cleanup: a leftover generated live_check.py
    must go, because `test.sh`'s own `[ -f live_check.py ]` guard would still
    run it for a step that declared no live check."""
    spec = _spec_with_step_one_live_check_off(hand_authored=False)
    step = (spec.steps or [])[0]
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    stale = tests_dir / "live_check.py"
    stale.write_text("# generator-written stub\n")

    write_tests_dir(spec, "hcl_raw", tests_dir, step)

    assert not stale.exists(), "a generator-written live_check.py must be cleaned up"
    assert (tests_dir / "static_tiers.sh").is_file()
    assert (tests_dir / "policy.rego").is_file()


def test_opted_out_step_REFUSES_to_delete_a_hand_authored_live_check(
    tmp_path,
) -> None:
    """The guard this test exists for: gen.py must never delete hand-written
    oracle material.

    Matches the two sibling paths (`_clear_generated_tests_files` and
    `write_multi_step_layout`'s stale-step-dir sweep), which already hard-error
    rather than unlink. Latent today — no shipped spec sets a step's
    `live_check.enabled: false` — but `make gen` is run on every spec edit, so
    the first spec that does would have silently destroyed the file.
    """
    spec = _spec_with_step_one_live_check_off(hand_authored=True)
    assert spec.verifier.live_check.hand_authored
    step = (spec.steps or [])[0]
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    precious = tests_dir / "live_check.py"
    precious.write_text("# hand-written, hours of work\n")

    with pytest.raises(RuntimeError, match="HAND-AUTHORED live_check.py"):
        write_tests_dir(spec, "hcl_raw", tests_dir, step)

    assert precious.read_text() == "# hand-written, hours of work\n", (
        "the generator raised but deleted the file anyway"
    )


def test_task_toml_description_carries_the_step_one_safe_title(spec: Spec) -> None:
    """Amendment 27 §5.1's lesson, applied to the last generator-stamped copy
    of the arc left in the task dir.

    task.toml is host-side only (harbor/trial/trial.py uploads no task file),
    so this is defence in depth — but "it's only metadata" is exactly how the
    whole-arc title got into the step-1 agent's own main.tf. The full title is
    kept in [metadata] scenario_title.
    """
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        description = cfg["task"]["description"]
        assert spec.workspace_header() in description
        assert spec.title not in description
        assert not _leaks(description, CONTENT_TOKENS + TEMPORAL_TOKENS)
        assert cfg["metadata"]["scenario_title"] == spec.title


def test_multi_step_scenario_title_comment_is_frozen(spec: Spec) -> None:
    """The COMMENT above `scenario_title`, pinned byte-for-byte.

    Not pedantry. `[metadata] scenario_title` was later reused by the brownfield
    form (Amendment 28 §3 rule 7), and generalising this comment's prose to
    cover both forms silently rewrote three already-published `apigw-redeploy`
    task.toml files -- a regeneration diff on task dirs nobody had touched.
    `gen.py::build_task_toml` now emits form-specific wording, and this freezes
    the multi-step half so the next author to widen a shared key has to notice.
    """
    expected = (
        "# The WHOLE-ARC scenario title. [task] description deliberately\n"
        "# carries the step-1-safe workspace_title instead (SCHEMA.md §0.1,\n"
        "# DECISIONS.md Amendment 27 §5.1) -- this key is where the full\n"
        "# arc wording lives, for host-side reporting only.\n"
        "scenario_title = "
    )
    for arm in ARMS:
        raw = (task_dir(spec, arm) / "task.toml").read_text()
        assert expected in raw, f"{arm}: multi-step scenario_title comment drifted"


def test_stepless_task_toml_description_is_unchanged() -> None:
    """The byte-identity guarantee: `workspace_header()` returns `title`
    verbatim for a stepless spec, and no `scenario_title` key appears."""
    control = load_spec(REPO_ROOT / "specs" / "sfn-jsonata.yaml")
    assert not control.is_multi_step()
    for arm in control.arms.enabled_arms():
        cfg = tomllib.loads((task_dir(control, arm) / "task.toml").read_text())
        assert cfg["task"]["description"].startswith(f"{control.title} -- {arm} arm.")
        assert "scenario_title" not in cfg["metadata"]


def test_multi_step_verification_explanation_qualifies_its_paths(spec: Spec) -> None:
    """A multi-step task has no tests/live_check.py and no tests/test.sh at the
    root — the shared tests/ holds only README.md — so an unqualified mention
    sends a reader of task.toml alone after two files that do not exist."""
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        explanation = cfg["metadata"]["verification_explanation"]
        assert "steps/<name>/tests/live_check.py" in explanation
        assert "steps/<name>/tests/test.sh" in explanation
        # No mention of either file at the task ROOT survives. Both are
        # checked as whole path tokens, so the step-qualified spellings
        # (".../steps/<name>/tests/test.sh") do not match.
        for orphan in ("tests/live_check.py, run by tests/test.sh",):
            assert orphan not in explanation
        for root_path in ("tests/test.sh", "tests/live_check.py"):
            assert explanation.count(root_path) == explanation.count(
                f"steps/<name>/{root_path}"
            ), f"{root_path} is still referenced at the task root"
        # ...and the claim is true of the real task dir.
        root_tests = task_dir(spec, arm) / "tests"
        assert not (root_tests / "live_check.py").exists()
        assert not (root_tests / "test.sh").exists()


def test_build_task_toml_is_deterministic(spec: Spec) -> None:
    """Cheap idempotence proof for the two emitter edits above: the same spec
    and uuid render byte-identically, so `make gen-all` stays a no-op."""
    for arm in ARMS:
        first = build_task_toml(spec, arm, "fixed-uuid")
        assert first == build_task_toml(spec, arm, "fixed-uuid")


def test_stepless_specs_are_untouched() -> None:
    """The regression guarantee: a spec without `steps` still emits the
    single-step shape, root instruction.md and all."""
    for spec_path in sorted((REPO_ROOT / "specs").glob("*.yaml")):
        if spec_path.name == "split.yaml":
            continue
        other = load_spec(spec_path)
        if other.is_multi_step():
            continue
        assert instruction_rel_paths(other) == [("instruction.md", None)]
        assert build_steps_toml(other, other.verifier.live_check) == []
        for arm in other.arms.enabled_arms():
            root = task_dir(other, arm)
            assert (root / "instruction.md").is_file(), ARM_DIRNAME[arm]
            assert (root / "tests" / "static_tiers.sh").is_file()
            assert not (root / "steps").exists()


def test_harbor_still_keeps_one_container_across_steps() -> None:
    """The agent-deploys opt-in rests on TWO Harbor properties. Pin both
    against the installed rev, so an aws-bench/harbor pin bump that changed
    them fails here instead of at the next live run.

    (1) The agent environment is stopped ONCE, after the whole step loop --
        so the workspace, the terraform state and the deployed stack all
        survive every step boundary.
    (2) A step's `workdir/` is uploaded ONLY IF it exists -- so the generator
        emitting none is what guarantees nothing overwrites /app/project
        between steps.

    Source-level rather than behavioural because exercising it for real needs
    a docker daemon and an AWS account, which this suite must not touch.
    """
    import inspect  # noqa: PLC0415

    from harbor.trial.multi_step import MultiStepTrial  # noqa: PLC0415

    run_src = inspect.getsource(MultiStepTrial._run)
    assert "_stop_agent_environment" in run_src, (
        "harbor no longer stops the agent environment in _run (after the step "
        "loop) -- re-check WHERE it stops it before trusting workspace carry-over"
    )

    # `_run_step` contains ONE other stop call, and it is unreachable for us:
    # it fires only for a SEPARATE-environment verifier on the last step, and
    # cdktn_bench.trial.validate_multi_step_layout refuses a task that declares
    # one on any step (aws-bench phase scripts run in the agent container).
    step_src = inspect.getsource(MultiStepTrial._run_step)
    for line in step_src.splitlines():
        if "_stop_agent_environment" in line:
            assert "VerifierEnvironmentMode.SEPARATE" in step_src, (
                "harbor stops the agent environment inside _run_step on a path "
                "that is no longer gated on a separate-environment verifier -- "
                "the workspace may no longer survive a step boundary"
            )

    upload_src = inspect.getsource(MultiStepTrial._upload_step_workdir)
    assert "step_workdir_dir.exists()" in upload_src, (
        "harbor no longer guards the step-workdir upload on the directory "
        "existing -- a multi-step task's workspace may now be overwritten "
        "between steps, which breaks apigw-redeploy's agent-deploys opt-in"
    )
    setup_src = inspect.getsource(MultiStepTrial._run_step_setup)
    assert "setup_script.exists()" in setup_src
