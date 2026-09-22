"""generator/tests/test_hcl_modules_image.py — the `hcl_modules` arm's IMAGE and
its registry sidecar (DECISIONS.md Amendment 46 (a), (b), (c), (g); phase 4 of
docs/design/tf-modules-arm.md).

Everything here reads files. The claims that need a container — offline `init`
through the responder, the transitive kms hop, an unlisted version refused —
belong to `arms/hcl-modules/environment/preflight.sh`, which `make preflight`
runs under `--network none`. What this module protects is the set of silent
drifts that a green preflight would not notice:

* the arm image diverging from `hcl-raw`'s toolchain, which would turn a
  cross-arm score difference into a toolchain difference;
* the provider mirror falling behind the vendored module tree, which fails
  `init` only for the one scenario that reaches the missing submodule;
* the CLI config and the compose file disagreeing about the sidecar's name or
  port, which fails every trial of the arm at once but passes every unit test
  that looks at either file alone;
* the in-context copy of `scripts/vendor_modules.py` drifting from the script
  the owner actually runs, which would leave the build verifying the tree with
  code no one maintains.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARM = REPO_ROOT / "arms" / "hcl-modules" / "environment"
RAW = REPO_ROOT / "arms" / "hcl-raw" / "environment"
DOCKERFILE = (ARM / "Dockerfile").read_text()
RAW_DOCKERFILE = (RAW / "Dockerfile").read_text()
TERRAFORMRC = (ARM / "terraformrc").read_text()
COMPOSE = yaml.safe_load((ARM / "docker-compose.yaml").read_text())
PREFLIGHT = (ARM / "preflight.sh").read_text()

# A provider source is two segments (`hashicorp/aws`); a registry MODULE source
# is three (`terraform-aws-modules/s3-bucket/aws`), so this pattern cannot
# confuse them.
PROVIDER_SOURCE_RE = re.compile(r'^\s*source\s*=\s*"([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)"\s*$')
VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"\s*$')


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def _declared_providers(root: Path) -> dict[str, list[str]]:
    """source address -> every version constraint declared for it anywhere under
    `root`. Derived from the bytes, not from a table: a module refresh that adds
    a provider shows up here without anyone remembering to write it down."""
    found: dict[str, list[str]] = {}
    for tf in sorted(root.rglob("*.tf")):
        lines = tf.read_text().splitlines()
        for i, line in enumerate(lines):
            m = PROVIDER_SOURCE_RE.match(line)
            if not m:
                continue
            constraints = found.setdefault(m.group(1), [])
            for follow in lines[i + 1 : i + 3]:
                v = VERSION_RE.match(follow)
                if v:
                    constraints.append(v.group(1))
                    break
    return found


VENDORED = _declared_providers(ARM / "modules")
MIRRORED = _declared_providers(ARM / "mirror-src")
# The one provider the tree declares and the mirror deliberately omits. Its only
# declarer, `lambda//modules/docker-build`, builds container images and needs a
# Docker daemon the agent container has not got, and mirroring it measured 370s
# of a 415s `terraform providers mirror` step against Harbor's 600s
# build_timeout_sec for a cold task build. Written as an exception list of
# exactly one so that a SECOND judgment call has to be argued here rather than
# quietly added to mirror-src/main.tf.
NOT_MIRRORED = {"kreuzwerker/docker"}


# ---------------------------------------------------------------------------
# the provider mirror vs the vendored tree
# ---------------------------------------------------------------------------


def test_the_mirror_declares_every_provider_the_vendored_tree_names() -> None:
    """`terraform init` resolves a module's WHOLE tree, so a provider that only
    a never-called submodule declares still has to be in the mirror — and with
    no `direct {}` fallback its absence is a hard init failure. Two of the nine
    are reachable only that way (`hashicorp/random` through the rds decoy's
    db_instance submodule, `kreuzwerker/docker` through lambda's docker-build),
    and `random` is missing from the spec matrix §4b table, which is why this
    test recomputes the set instead of restating it. NOT_MIRRORED is the one
    documented exception."""
    expected = set(VENDORED) - NOT_MIRRORED
    assert set(MIRRORED) == expected, sorted(expected ^ set(MIRRORED))


def test_the_mirror_declares_nothing_the_tree_does_not_name() -> None:
    """A provider nobody needs is 30-200 MB of image and one more thing to
    re-pin. Covered by the equality above; stated separately so a failure says
    which direction broke."""
    assert not set(MIRRORED) - set(VENDORED)


def test_the_excluded_provider_is_still_one_the_tree_declares() -> None:
    """A stale exception is an exception that stops meaning anything: if a
    refresh drops docker-build, the omission has to be re-argued or deleted."""
    assert NOT_MIRRORED <= set(VENDORED)


@pytest.mark.parametrize("source", sorted(set(VENDORED) - NOT_MIRRORED))
def test_every_mirrored_version_satisfies_every_floor_in_the_tree(source: str) -> None:
    pinned = MIRRORED[source]
    assert len(pinned) == 1, f"{source} must be pinned exactly once, got {pinned}"
    pin = _version_tuple(pinned[0])
    for constraint in VENDORED[source]:
        assert constraint.startswith(">="), (
            f"{source} declares {constraint!r}, which is not a floor — a pinned "
            "mirror cannot satisfy an upper bound or a ~> by being newest"
        )
        assert pin >= _version_tuple(constraint), f"{source}: {pinned[0]} < {constraint}"


def test_the_aws_provider_is_the_pin_hcl_raw_uses() -> None:
    """The two Terraform arms must resolve identical provider schemas or a
    cross-arm score difference could be a provider difference (Amendment 48)."""
    assert MIRRORED["hashicorp/aws"] == _declared_providers(RAW / "mirror-src")["hashicorp/aws"]


# ---------------------------------------------------------------------------
# the toolchain is hcl-raw's
# ---------------------------------------------------------------------------


def _pinned_fetches(dockerfile: str) -> set[tuple[str, str]]:
    """(URL template, sha256) for every build-time download. The URLs carry
    ${TARGETARCH}, so this compares the pin as written rather than as resolved."""
    urls = set(re.findall(r'URL="(https://[^"]+)"', dockerfile))
    shas = set(re.findall(r'_SHA256="([0-9a-f]{64})"', dockerfile))
    return {(u, s) for u in urls for s in shas}


def test_the_pinned_toolchain_fetches_are_hcl_raws() -> None:
    """Same terraform, opa, jq and hcl2json bytes as the arm this one derives
    from. A bump on one side only would grade the two arms with two tools."""
    assert _pinned_fetches(DOCKERFILE) == _pinned_fetches(RAW_DOCKERFILE)


def test_the_terraform_and_provider_args_match_hcl_raw() -> None:
    for arg in ("TERRAFORM_VERSION", "AWS_PROVIDER_VERSION"):
        pattern = rf"^ARG {arg}=(\S+)$"
        assert re.findall(pattern, DOCKERFILE, re.M) == re.findall(
            pattern, RAW_DOCKERFILE, re.M
        ), arg


def test_the_asset_mirror_default_is_the_fixed_url() -> None:
    """docs/asset-mirror.md: the default is non-empty and nothing overrides it,
    so every builder hashes these RUN lines identically and shares one layer
    cache. A different default here forks that cache silently."""
    assert re.findall(r"^ARG ASSET_MIRROR=(\S+)$", DOCKERFILE, re.M) == re.findall(
        r"^ARG ASSET_MIRROR=(\S+)$", RAW_DOCKERFILE, re.M
    )


def test_the_image_declares_no_user() -> None:
    """Amendment 46 (c)'s first half — "the tree is unreadable to the agent
    user" — is VOID as built: the agent runs as root here like every other arm,
    and generator/gen.py refuses a `USER` line outright for a seeded spec
    because Harbor's ScriptRunner prepares /logs/pre_invoke as root. Pinned as a
    test so that the void is a recorded fact rather than an oversight; what
    carries (c) is the phase-5 verifier deny on a non-registry `Source`."""
    assert not [
        line for line in DOCKERFILE.splitlines() if line.strip().upper().startswith("USER ")
    ]


# ---------------------------------------------------------------------------
# the vendored tree
# ---------------------------------------------------------------------------


def test_the_in_context_verifier_is_a_byte_copy_of_the_script() -> None:
    """A Docker build context cannot reach above itself, so the image build
    verifies the tree with a copy of scripts/vendor_modules.py that lives in the
    context. Byte equality is the whole guarantee: a drifted copy would verify
    the shipped tree with code the owner never runs on a refresh."""
    assert (ARM / "vendor_modules.py").read_bytes() == (
        REPO_ROOT / "scripts" / "vendor_modules.py"
    ).read_bytes()


def test_the_build_verifies_the_manifest() -> None:
    """A manifest that is computed and never checked is this repo's signature
    failure mode. The `--verify` run is a build step, so a tree edited in place
    stops the build instead of shipping."""
    assert "RUN python3 /opt/vendor_modules.py --verify --root /opt/terraform-modules" in DOCKERFILE


def test_no_module_byte_is_fetched_at_build() -> None:
    """Amendment 46 (b): the tree is COMMITTED and COPYed, so the host gates and
    the image share module bytes by construction."""
    assert "COPY modules/ /opt/terraform-modules/" in DOCKERFILE
    assert "codeload.github.com" not in DOCKERFILE
    assert "api.github.com" not in DOCKERFILE


# ---------------------------------------------------------------------------
# the CLI config and the sidecar must agree
# ---------------------------------------------------------------------------


def _registry_url() -> str:
    m = re.search(r'"modules\.v1"\s*=\s*"([^"]+)"', TERRAFORMRC)
    assert m, "terraformrc declares no modules.v1 service"
    return m.group(1)


def test_the_host_block_points_modules_at_the_compose_service() -> None:
    """The one cross-file claim no single-file test can make: the CLI config
    names a host:port, the compose file creates it. A rename on either side
    fails every trial of the arm and nothing else."""
    host, port = re.match(r"http://([^:/]+):(\d+)/", _registry_url()).groups()
    assert host in COMPOSE["services"], f"cli.tfrc names {host!r}, which is not a compose service"
    command = COMPOSE["services"][host]["command"]
    assert command[command.index("--port") + 1] == port
    healthcheck = " ".join(COMPOSE["services"][host]["healthcheck"]["test"])
    assert f":{port}/" in healthcheck, "the healthcheck probes a different port than the sidecar serves"


def test_the_host_block_restates_the_provider_service() -> None:
    """A `host` block REPLACES the whole service map rather than overriding one
    entry, so omitting providers.v1 makes Terraform report "registry.terraform.io
    does not offer a Terraform provider registry" instead of a missing-provider
    error. Nothing in this image consults it — provider_installation below has
    only a filesystem_mirror — but the message it buys is the difference between
    a diagnosable failure and a misleading one."""
    assert re.search(r'"providers\.v1"\s*=\s*"https://registry\.terraform\.io/', TERRAFORMRC)


def test_provider_installation_is_hcl_raws_filesystem_mirror_with_no_direct() -> None:
    """No `direct {}`: a provider missing from the mirror fails loudly instead
    of phoning home. Same mirror path as hcl-raw, so the same Dockerfile step
    fills it."""
    block = re.search(r"provider_installation \{.*?\n\}", TERRAFORMRC, re.S)
    raw_block = re.search(r"provider_installation \{.*?\n\}", (RAW / "terraformrc").read_text(), re.S)
    assert block and raw_block
    assert block.group(0) == raw_block.group(0)


def test_the_sidecar_runs_this_image_with_the_responder_as_its_command() -> None:
    """Amendment 46 (a): the responder, the module bytes and the manifest are one
    artifact. The sidecar therefore declares a build of the SAME context as the
    agent service rather than an image of its own — the two builds produce
    identical RootFS layers. Neither sets `image:`: a fixed tag shared by both
    services would be raced by two concurrent trials of different tasks."""
    sidecar = COMPOSE["services"]["tf-registry"]
    assert sidecar["build"]["context"] == "."
    assert "image" not in sidecar and "image" not in COMPOSE["services"]["main"]
    assert sidecar["command"][:2] == ["python3", "/opt/tf-registry/responder.py"]
    assert f"COPY tf-registry/responder.py {sidecar['command'][1]}" in DOCKERFILE


def test_the_sidecar_binds_beyond_loopback() -> None:
    """The responder defaults to 127.0.0.1, which no other container can reach.
    Without this the agent's every `terraform init` is a connection refused."""
    command = COMPOSE["services"]["tf-registry"]["command"]
    assert command[command.index("--bind") + 1] == "0.0.0.0"


def test_the_sidecar_serves_the_tree_the_image_verified() -> None:
    command = COMPOSE["services"]["tf-registry"]["command"]
    assert command[command.index("--root") + 1] == "/opt/terraform-modules"


def test_the_agent_waits_for_the_registry_to_serve() -> None:
    """`terraform init` one second early fails with a connection error that
    reads like an offline-arm bug, so the dependency is on HEALTHY, not on
    started, and the healthcheck is a real request."""
    assert COMPOSE["services"]["main"]["depends_on"]["tf-registry"]["condition"] == "service_healthy"
    test = COMPOSE["services"]["tf-registry"]["healthcheck"]["test"]
    assert any("/.well-known/terraform.json" in part for part in test)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


def test_preflight_runs_every_fixture_that_ships() -> None:
    """A fixture directory nobody runs is a claim nobody checks."""
    fixtures = sorted(p.name for p in (ARM / "fixtures").iterdir() if p.is_dir())
    assert fixtures
    for name in fixtures:
        assert f"run_fixture {name}" in PREFLIGHT, name


def test_preflight_derives_its_cli_config_from_the_shipped_one() -> None:
    """The preflight runs in a single container, where the compose service name
    does not resolve, so it substitutes loopback into the IMAGE's own config
    rather than hand-writing a second one — otherwise it would be proving a
    config the image does not ship."""
    assert "/etc/terraform.d/cli.tfrc >" in PREFLIGHT
    assert "COPY terraformrc /etc/terraform.d/cli.tfrc" in DOCKERFILE


def test_preflight_asserts_the_negative_case() -> None:
    """An unlisted version must fail, AND fail for that reason: a container with
    no route to the sidecar also fails `init`."""
    assert "the responder is answering outside its allowlist" in PREFLIGHT
    assert "the newest available version is 5.16.1" in PREFLIGHT


def test_preflight_asserts_no_service_discovery_request() -> None:
    """If Terraform ever issues /.well-known/terraform.json, the host override
    is not being honoured and the arm's offline claim would depend on resolving
    registry.terraform.io."""
    assert "/.well-known/terraform.json" in PREFLIGHT


def test_make_preflight_runs_this_arms_entrypoint() -> None:
    """The Makefile picks an entrypoint per arm; an arm missing from that case
    gets /usr/local/bin/preflight.sh, which does not exist in this image."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "hcl-raw|hcl-modules) entrypoint=/opt/preflight/preflight.sh" in makefile
    assert "COPY preflight.sh ./preflight.sh" in DOCKERFILE
    assert "WORKDIR /opt/preflight" in DOCKERFILE


def test_preflight_scopes_the_registry_source_rule_to_root_calls() -> None:
    """Amendment 46 (c)'s "a modules.json Source that is not a registry source
    is a deny" is false as literally written: a registry module calls its own
    submodules by relative path, so ecs, eks and rds each install entries whose
    Source is `./modules/...`. The rule that holds is scoped to the calls the
    ROOT module makes — a Key with no dot — and a blanket version would refuse
    three vendored modules while still passing every fixture that has no
    submodules."""
    assert '.Key == "" or (.Key | contains("."))' in PREFLIGHT
    assert "all(.Modules[]; .Source" not in PREFLIGHT


def test_a_fixture_exercises_the_relative_submodule_case() -> None:
    """Without a fixture that actually installs relative-source entries, the
    scoped rule above passes vacuously and a blanket rewrite of it would go
    unnoticed."""
    fixture = (ARM / "fixtures" / "nested-submodules" / "main.tf").read_text()
    assert 'source  = "terraform-aws-modules/ecs/aws"' in fixture
    assert '| not))] | length >= 3' in PREFLIGHT
