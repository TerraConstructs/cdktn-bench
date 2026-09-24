"""The loopback module registry: protocol, allowlist, MCP skeleton, offline init.

The end-to-end test is the one that matters: real `terraform init`, real module
resolution, and the proof that it came from the responder is the responder's own
access log rather than the absence of an error. Everything above it exists so a
protocol break names itself instead of surfacing as a failed init.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "gates"))

import tf_registry  # noqa: E402

RESPONDER = tf_registry.RESPONDER
VENDORED = tf_registry.MODULES_ROOT

# The fake tree stands in for the vendored one wherever a test only needs the
# protocol: a module with no `required_providers` lets `terraform init` finish
# with no provider installation at all, so the e2e run needs no mirror and no
# network for anything.
FAKE_MODULES = [
    ("s3-bucket", "5.16.1", False, "Private S3 bucket with policy and encryption inputs"),
    ("s3-bucket", "5.15.0", False, "Private S3 bucket with policy and encryption inputs"),
    ("kms", "4.0.0", True, "KMS key with alias, grants and key policy inputs"),
]


@pytest.fixture(scope="module")
def fake_tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("modules")
    entries = []
    for name, version, decoy, description in FAKE_MODULES:
        d = root / f"{name}-{version}"
        d.mkdir()
        (d / "main.tf").write_text(f'output "id" {{\n  value = "{name}-{version}"\n}}\n')
        (d / "LICENSE").write_text("Apache License 2.0\n")
        files = [
            {"path": p.relative_to(d).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(d.rglob("*")) if p.is_file()
        ]
        entries.append({
            "name": name, "version": version, "dir": d.name,
            "source": f"terraform-aws-modules/{name}/aws",
            "upstream_tag": f"v{version}", "commit_sha": "0" * 40,
            "description": description, "files": files, "decoy": decoy,
        })
    (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "modules": entries}))
    return root


@pytest.fixture(scope="module")
def registry(fake_tree):
    with tf_registry.running_registry(fake_tree) as env:
        yield env


def get(env, path: str):
    """`(status, body_bytes, headers)` — never raises on a 4xx, because the
    refusal bodies are what several of these tests assert on."""
    url = env[tf_registry.URL_VAR] + path
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def rpc(env, payload: dict, session: str | None = None):
    req = urllib.request.Request(
        env[tf_registry.URL_VAR] + "/mcp",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    if session:
        req.add_header("Mcp-Session-Id", session)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if body else None), dict(resp.headers)


def access_log(env) -> str:
    return Path(env[tf_registry.LOG_VAR]).read_text()


class TestProtocol:
    def test_discovery_document_points_at_the_modules_service(self, registry):
        status, body, _ = get(registry, "/.well-known/terraform.json")
        assert status == 200
        assert json.loads(body) == {"modules.v1": "/v1/modules/"}

    def test_versions_lists_every_manifest_entry_newest_last(self, registry):
        status, body, _ = get(registry, "/v1/modules/terraform-aws-modules/s3-bucket/aws/versions")
        assert status == 200
        versions = [v["version"] for v in json.loads(body)["modules"][0]["versions"]]
        assert versions == ["5.15.0", "5.16.1"]

    def test_unvendored_namespace_is_a_404_naming_the_allowlist(self, registry):
        status, body, _ = get(registry, "/v1/modules/hashicorp/consul/aws/versions")
        assert status == 404
        text = body.decode()
        assert "terraform-aws-modules/<name>/aws" in text
        assert "kms, s3-bucket" in text

    def test_unvendored_module_is_a_404_naming_what_exists(self, registry):
        status, body, _ = get(registry, "/v1/modules/terraform-aws-modules/eks/aws/versions")
        assert status == 404
        assert "available modules: kms, s3-bucket" in body.decode()

    def test_download_is_204_with_an_absolute_tarball_url(self, registry):
        status, body, headers = get(
            registry, "/v1/modules/terraform-aws-modules/s3-bucket/aws/5.16.1/download"
        )
        assert status == 204
        assert body == b""
        assert headers["X-Terraform-Get"] == (
            registry[tf_registry.URL_VAR] + "/tarballs/s3-bucket-5.16.1.tar.gz"
        )

    def test_unvendored_version_is_a_404_naming_the_newest_one(self, registry):
        status, body, _ = get(
            registry, "/v1/modules/terraform-aws-modules/s3-bucket/aws/9.9.9/download"
        )
        assert status == 404
        assert "the newest available version is 5.16.1" in body.decode()

    def test_tarball_carries_the_module_root_at_its_top_level(self, registry, tmp_path):
        status, body, _ = get(registry, "/tarballs/s3-bucket-5.16.1.tar.gz")
        assert status == 200
        archive = tmp_path / "s3-bucket.tar.gz"
        archive.write_bytes(body)
        with tarfile.open(archive) as tar:
            names = sorted(tar.getnames())
        # No `s3-bucket-5.16.1/` prefix: go-getter extracts the archive AS the
        # module root, so a retained top directory hides every .tf file.
        assert names == ["LICENSE", "main.tf"]


class TestSearch:
    def test_search_matches_name_and_description(self, registry):
        status, body, _ = get(registry, "/v1/modules/search?q=bucket")
        assert status == 200
        hits = json.loads(body)["modules"]
        assert [h["source"] for h in hits] == ["terraform-aws-modules/s3-bucket/aws"]
        assert hits[0]["versions"] == ["5.16.1", "5.15.0"]

    def test_empty_query_lists_the_whole_allowlist(self, registry):
        _, body, _ = get(registry, "/v1/modules/search?q=")
        assert [h["source"] for h in json.loads(body)["modules"]] == [
            "terraform-aws-modules/kms/aws",
            "terraform-aws-modules/s3-bucket/aws",
        ]

    def test_decoys_are_served_unmarked(self, registry):
        """A decoy that advertised itself would hand the agent the selection
        answer this arm measures."""
        _, body, _ = get(registry, "/v1/modules/search?q=kms")
        hits = json.loads(body)["modules"]
        assert hits and all("decoy" not in json.dumps(h) for h in hits)


class TestMcpSkeleton:
    def test_initialize_issues_a_session_id_that_round_trips(self, registry):
        status, payload, headers = rpc(registry, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert status == 200
        session = headers["Mcp-Session-Id"]
        assert session
        assert payload["result"]["serverInfo"]["name"] == "cdktn-bench-registry-index"
        _, _, listed = rpc(registry, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
        assert listed["Mcp-Session-Id"] == session

    def test_initialized_notification_is_accepted_with_no_body(self, registry):
        status, payload, _ = rpc(registry, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert status == 202
        assert payload is None

    def test_tools_list_is_the_nine_registry_tool_names(self, registry):
        _, payload, _ = rpc(registry, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        tools = payload["result"]["tools"]
        assert sorted(t["name"] for t in tools) == sorted([
            "get_latest_module_version", "get_latest_provider_version", "get_module_details",
            "get_policy_details", "get_provider_capabilities", "get_provider_details",
            "search_modules", "search_policies", "search_providers",
        ])
        by_name = {t["name"]: t["inputSchema"] for t in tools}
        assert by_name["search_modules"]["required"] == ["module_query"]
        assert by_name["get_module_details"]["required"] == ["module_id"]
        assert by_name["get_latest_module_version"]["required"] == [
            "module_name", "module_provider", "module_publisher"
        ]
        assert "resources" in by_name["search_providers"]["properties"]["provider_document_type"]["enum"]

    def test_the_nine_names_are_the_ones_the_design_memo_read_off_v1_3_0(self, registry):
        """M2 replaces these bodies in place, so an agent tuned against the real
        `hashicorp/terraform-mcp-server` registry toolset must find the same nine
        names here. The memo's table was read off the tagged source; deriving the
        expectation from it means a renamed tool fails here rather than being
        copied twice and agreeing with itself."""
        memo = (REPO_ROOT / "docs" / "design" / "registry-index-tool.md").read_text()
        section = memo.split("## 1.")[1].split("## 2.")[0]
        documented = set()
        for line in section.splitlines():
            if not line.startswith("| `"):
                continue
            cell = line.split("|")[1]
            documented.update(
                token for token in re.findall(r"`([^`]+)`", cell)
                if re.fullmatch(r"[a-z][a-z_]+", token)
            )
        assert len(documented) == 9, sorted(documented)
        _, payload, _ = rpc(registry, {"jsonrpc": "2.0", "id": 6, "method": "tools/list"})
        assert {t["name"] for t in payload["result"]["tools"]} == documented

    def test_every_call_declines_as_a_successful_result(self, registry):
        for name in ("search_modules", "get_provider_details", "search_policies"):
            _, payload, _ = rpc(registry, {
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            result = payload["result"]
            # A declined call is a result, not an error: an error reads to an
            # agent as an outage worth retrying.
            assert result["isError"] is False
            assert result["content"] == [
                {"type": "text", "text": f"{name}: not available in this environment"}
            ]

    def test_an_unknown_tool_is_a_jsonrpc_error(self, registry):
        _, payload, _ = rpc(registry, {
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "apply_terraform", "arguments": {}},
        })
        assert payload["error"]["code"] == -32602


def test_responder_opens_no_outbound_connection(fake_tree, tmp_path):
    """Run the responder under an audit hook that records every `socket.connect`
    and drive every endpoint. The manifest is the whole world: one recorded
    connect would mean an unlisted version could be answered from upstream,
    which is the failure the arm's offline guarantee cannot tolerate."""
    connects = tmp_path / "connects.log"
    launcher = tmp_path / "audited_responder.py"
    launcher.write_text(textwrap.dedent(f"""
        import runpy, sys

        def hook(event, args):
            if event == "socket.connect":
                with open({str(connects)!r}, "a") as fh:
                    fh.write(repr(args) + "\\n")

        sys.addaudithook(hook)
        sys.argv = ["responder.py", "--root", {str(fake_tree)!r}, "--port", "0"]
        runpy.run_path({str(RESPONDER)!r}, run_name="__main__")
    """))
    proc = subprocess.Popen([sys.executable, str(launcher)], stdout=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline().strip().removeprefix("PORT="))
        env = {tf_registry.URL_VAR: f"http://127.0.0.1:{port}"}
        for path in (
            "/.well-known/terraform.json",
            "/v1/modules/terraform-aws-modules/s3-bucket/aws/versions",
            "/v1/modules/terraform-aws-modules/s3-bucket/aws/5.16.1/download",
            "/tarballs/s3-bucket-5.16.1.tar.gz",
            "/v1/modules/search?q=s3",
            "/v1/modules/terraform-aws-modules/eks/aws/versions",
        ):
            get(env, path)
        rpc(env, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        proc.stdout.close()
    assert not connects.exists(), connects.read_text()


class TestHostWiring:
    def test_cli_config_keeps_the_inherited_provider_block(self, tmp_path):
        inherited = tmp_path / "cli.tfrc"
        inherited.write_text(
            'provider_installation {\n  filesystem_mirror {\n'
            '    path = "/opt/terraform-plugin-mirror"\n  }\n}\n'
        )
        text = tf_registry.cli_config_text(8081, inherited)
        # Both blocks, or provider installation silently returns to the network.
        assert "/opt/terraform-plugin-mirror" in text
        assert '"modules.v1"   = "http://127.0.0.1:8081/v1/modules/"' in text
        assert text.index("provider_installation") < text.index('host "registry.terraform.io"')

    def test_cli_config_without_an_inherited_one_is_the_override_alone(self):
        text = tf_registry.cli_config_text(8081, None)
        assert "provider_installation" not in text
        assert text.lstrip().startswith("//")

    def test_the_host_block_restates_the_provider_service(self):
        """A `host` block REPLACES the whole service map: overriding modules
        alone makes Terraform report that registry.terraform.io offers no
        provider registry and fail init on the provider stage."""
        text = tf_registry.cli_config_text(8081, None)
        assert '"providers.v1" = "https://registry.terraform.io/v1/providers/"' in text

    def test_missing_manifest_refuses_rather_than_serving_nothing(self, tmp_path):
        with pytest.raises(RuntimeError, match="no manifest.json"):
            with tf_registry.running_registry(tmp_path):
                pass

    def test_other_arms_get_their_environment_unchanged(self, monkeypatch):
        """Arm-gated: three green arms must not depend on a fourth arm's
        subprocess, so `arm_env` is identity for everything but hcl_modules.

        `arm_env` lives beside `running_registry` in this module, and every gate
        that runs a toolchain reaches it from here -- including the generator-side
        reference-path gate, which resolved modules from the PUBLIC registry until
        it did. Asserted as object identity so a gate that grew its own copy is
        red here rather than quietly offline-in-name-only."""
        import artifact_collector
        import check_reference_paths
        import grading_proof
        import oracle_falsifiability

        for module in (
            artifact_collector,
            grading_proof,
            oracle_falsifiability,
            check_reference_paths,
        ):
            assert module.arm_env is tf_registry.arm_env, module.__name__

        def fail(*a, **k):
            raise AssertionError("running_registry started for a non-modules arm")

        monkeypatch.setattr(oracle_falsifiability.tf_registry, "running_registry", fail)
        env = {"PATH": "/usr/bin", "AWS_ENDPOINT_URL": "http://127.0.0.1:1"}
        for arm in artifact_collector.ARMS:
            if arm == "hcl_modules":
                continue
            with artifact_collector.arm_env(arm, env) as out:
                assert out is env

    def test_the_modules_arm_gets_the_registry_environment(self, fake_tree, monkeypatch):
        import oracle_falsifiability

        monkeypatch.setattr(oracle_falsifiability.tf_registry, "MODULES_ROOT", fake_tree)
        env = {"PATH": "/usr/bin"}
        with oracle_falsifiability.arm_env("hcl_modules", env) as out:
            assert out["TF_CLI_CONFIG_FILE"] != env.get("TF_CLI_CONFIG_FILE")
            assert Path(out["TF_CLI_CONFIG_FILE"]).read_text().count('"modules.v1"   = ') == 1


def _workspace(path: Path, name: str, version: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "main.tf").write_text(
        f'module "m" {{\n  source  = "terraform-aws-modules/{name}/aws"\n'
        f'  version = "{version}"\n}}\n'
    )
    return path


def _init(work: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["terraform", "init", "-input=false", "-no-color"],
        cwd=work, env=env, capture_output=True, text=True, timeout=180,
    )


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not on PATH")
def test_terraform_init_resolves_a_module_offline_from_the_responder(registry, tmp_path):
    """The whole point, end to end: `terraform init` with only the CLI config's
    `host` override, and the responder's own access log as the proof of where
    the module came from. No proxy variables — a dead proxy would prove only
    that outbound failed, not that the module arrived from here."""
    work = _workspace(tmp_path / "ws", "s3-bucket", "5.16.1")
    before = len(access_log(registry))
    result = _init(work, registry)
    assert result.returncode == 0, result.stdout + result.stderr
    modules = json.loads((work / ".terraform" / "modules" / "modules.json").read_text())
    entry = next(m for m in modules["Modules"] if m["Key"] == "m")
    assert entry["Source"].endswith("terraform-aws-modules/s3-bucket/aws")
    assert entry["Version"] == "5.16.1"
    log = access_log(registry)[before:]
    assert "ACCESS GET /v1/modules/terraform-aws-modules/s3-bucket/aws/versions 200" in log
    assert "ACCESS GET /v1/modules/terraform-aws-modules/s3-bucket/aws/5.16.1/download 204" in log
    assert "ACCESS GET /tarballs/s3-bucket-5.16.1.tar.gz 200" in log
    # The override skips discovery entirely; a request here would mean
    # Terraform had consulted the real registry's service map.
    assert "/.well-known/terraform.json" not in log


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not on PATH")
@pytest.mark.skipif(not (VENDORED / "manifest.json").is_file(), reason="vendored tree not committed yet")
def test_terraform_init_resolves_a_vendored_module(tmp_path):
    """Same run against the committed tree, the bytes the image ships. Green
    end to end: the module comes from the responder and `hashicorp/aws` from
    the host's own provider installation, exactly as the other three
    Terraform-shaped arms resolve providers on the host."""
    manifest = json.loads((VENDORED / "manifest.json").read_text())
    entries = manifest["modules"] if isinstance(manifest, dict) else manifest
    entry = sorted(entries, key=lambda m: (m["name"], m["version"]))[0]
    with tf_registry.running_registry(VENDORED) as env:
        work = _workspace(tmp_path / "ws", entry["name"], entry["version"])
        result = _init(work, env)
        assert result.returncode == 0, result.stdout + result.stderr
        modules = json.loads((work / ".terraform" / "modules" / "modules.json").read_text())
        assert any(m.get("Version") == entry["version"] for m in modules["Modules"])
        log = access_log(env)
    assert f"/{entry['version']}/download 204" in log
    assert f"/tarballs/{entry['name']}-{entry['version']}.tar.gz 200" in log
