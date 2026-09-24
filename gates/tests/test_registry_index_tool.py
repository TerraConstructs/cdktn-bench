"""The bench-owned registry index tool: schemas, answers, misses, determinism.

The nine tool NAMES and input schemas are upstream
`hashicorp/terraform-mcp-server` v1.3.0's `registry` toolset, so an agent or a
skill tuned against the real server calls the same tools with the same
arguments (`docs/design/registry-index-tool.md` §1, design B). What differs is
where the answers come from: this environment's vendored module tree and its
provider mirror, with no registry connection at all. The tests that matter are
therefore the ones about honesty rather than prose — that a miss is a successful
result naming what does exist, that an input the HCL reader cannot read says so
instead of carrying a guess, and that two runs are byte-identical.

Schema parity is derived from the memo's §1 table rather than restated here: a
renamed tool or a moved required argument fails this file instead of being
copied twice and agreeing with itself.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "gates"))

import tf_registry  # noqa: E402

from test_tf_registry import get, rpc  # noqa: E402  the MCP client both files drive

MEMO = REPO_ROOT / "docs" / "design" / "registry-index-tool.md"
VENDORED = tf_registry.MODULES_ROOT
# One mirrored version per provider is enough to exercise every provider path;
# the real mirror is 2 GB of zips and lives only inside the arm image.
FAKE_MIRROR = {
    ("hashicorp", "aws"): {"6.66.0": ["linux_arm64"]},
    ("hashicorp", "tls"): {"4.4.1": ["linux_arm64"], "4.3.0": ["linux_amd64", "linux_arm64"]},
}


def _load_responder():
    spec = importlib.util.spec_from_file_location("responder_under_test", tf_registry.RESPONDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


responder = _load_responder()

pytestmark = pytest.mark.skipif(
    not (VENDORED / "manifest.json").is_file(), reason="vendored tree not committed yet"
)


@pytest.fixture(scope="module")
def mirror_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("plugin-mirror") / "registry.terraform.io"
    for (namespace, name), versions in FAKE_MIRROR.items():
        directory = root / namespace / name
        directory.mkdir(parents=True)
        (directory / "index.json").write_text(json.dumps({"versions": {v: {} for v in versions}}))
        for version, platforms in versions.items():
            (directory / f"{version}.json").write_text(json.dumps({
                "archives": {p: {"hashes": ["h1:x"], "url": f"terraform-provider-{name}_{version}_{p}.zip"}
                             for p in platforms}
            }))
    return root.parent


@pytest.fixture(scope="module")
def index(mirror_root) -> object:
    """The tool bodies over the REAL vendored manifest: what the arm ships is
    what a golden here is worth asserting about."""
    manifest = responder.Manifest(VENDORED)
    return responder.Index(manifest, responder.ProviderMirror(mirror_root))


def call(index, tool: str, **arguments) -> str:
    return index.call(tool, arguments)


def document(index, tool: str, **arguments) -> dict:
    return json.loads(call(index, tool, **arguments))


# ---------------------------------------------------------------------------
# schema parity with the memo's §1 table
# ---------------------------------------------------------------------------

_ARG = re.compile(r"^[a-z][a-z_]+$")


def memo_rows() -> list[tuple[list[str], list[str], list[str]]]:
    """`(tool names, required args, optional args)` per row of §1's table. A row
    naming two tools (`search_policies` / `get_policy_details`) names their
    required arguments in the same order, which is how they are paired."""
    section = MEMO.read_text().split("## 1.")[1].split("## 2.")[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = line.split("|")
        names = [t for t in re.findall(r"`([^`]+)`", cells[1]) if _ARG.match(t)]
        required_text, _, optional_text = cells[2].partition("; opt")
        required = [t for t in re.findall(r"`([^`]+)`", required_text) if _ARG.match(t)]
        optional = [t for t in re.findall(r"`([^`]+)`", optional_text) if _ARG.match(t)]
        rows.append((names, required, optional))
    return rows


def memo_schemas() -> dict[str, tuple[list[str], list[str]]]:
    schemas: dict[str, tuple[list[str], list[str]]] = {}
    for names, required, optional in memo_rows():
        for position, name in enumerate(names):
            own = [required[position]] if len(names) > 1 and len(names) == len(required) else required
            schemas[name] = (sorted(own), sorted(optional))
    return schemas


class TestSchemaParity:
    def test_the_memo_table_describes_nine_tools(self):
        assert sorted(memo_schemas()) == sorted(responder.TOOL_NAMES)

    @pytest.mark.parametrize("tool", sorted(memo_schemas()))
    def test_required_and_optional_arguments_match_the_memo(self, tool):
        required, optional = memo_schemas()[tool]
        schema = next(t["inputSchema"] for t in responder.TOOLS if t["name"] == tool)
        assert schema["required"] == required
        assert sorted(set(schema["properties"]) - set(required)) == optional

    def test_the_document_type_enum_is_the_upstream_one(self):
        schema = next(t["inputSchema"] for t in responder.TOOLS if t["name"] == "search_providers")
        listed = re.search(r"enum: ([^)]+)\)", MEMO.read_text().split("## 1.")[1]).group(1)
        assert schema["properties"]["provider_document_type"]["enum"] == [s.strip() for s in listed.split(",")]


# ---------------------------------------------------------------------------
# goldens: one answer per tool over the real manifest
# ---------------------------------------------------------------------------


class TestModuleGoldens:
    def test_search_matches_the_module_name(self, index):
        found = document(index, "search_modules", module_query="dynamodb")
        assert [m["source"] for m in found["modules"]] == ["terraform-aws-modules/dynamodb-table/aws"]
        assert found["total"] == 1

    def test_search_matches_an_input_name_and_names_which(self, index):
        found = document(index, "search_modules", module_query="deletion_window_in_days")
        assert {m["source"]: m["inputs_matching_query"] for m in found["modules"]} == {
            "terraform-aws-modules/kms/aws": ["deletion_window_in_days"],
            "terraform-aws-modules/eks/aws": ["kms_key_deletion_window_in_days"],
        }

    def test_every_word_of_a_phrase_query_must_match(self, index):
        """The natural phrasing of the commonest request. Matching the query as one
        literal string answered "s3 bucket" with nothing, which handicaps the tuned
        level rather than describing the index."""
        phrase = document(index, "search_modules", module_query="s3 bucket")
        assert "terraform-aws-modules/s3-bucket/aws" in [m["source"] for m in phrase["modules"]]
        # AND, not OR: a phrase whose second word matches nothing matches nothing.
        assert document(index, "search_modules", module_query="s3 cloudfront")["total"] == 0

    def test_an_empty_query_pages_the_whole_allowlist(self, index):
        first = document(index, "search_modules", module_query="")
        assert first["total"] == len(responder.Manifest(VENDORED).names)
        assert len(first["modules"]) == responder.SEARCH_PAGE_SIZE
        assert first["next_offset"] == responder.SEARCH_PAGE_SIZE
        second = document(index, "search_modules", module_query="", current_offset=first["next_offset"])
        assert second["modules"][0]["source"] > first["modules"][-1]["source"]

    def test_a_query_matching_nothing_is_an_empty_page_not_an_error(self, index):
        found = document(index, "search_modules", module_query="cloudfront")
        assert found["modules"] == [] and found["total"] == 0

    def test_module_details_carry_inputs_outputs_versions_and_the_upstream_pin(self, index):
        details = document(index, "get_module_details", module_id="terraform-aws-modules/kms/aws/4.0.0")
        assert details["versions_available"] == ["4.0.0", "4.2.2"]
        assert details["upstream"]["repo"] == "terraform-aws-modules/terraform-aws-kms"
        assert len(details["upstream"]["commit"]) == 40
        assert details["provider_requirements"] == [
            {"name": "aws", "source": "hashicorp/aws", "version": ">= 6.0"}
        ]
        assert details["required_terraform_version"] == ">= 1.5.7"
        aliases = next(row for row in details["inputs"] if row["name"] == "aliases")
        assert aliases == {
            "name": "aliases",
            "required": False,
            "type": "list(string)",
            "default": "[]",
            "description": (
                "A list of aliases to create. Note - due to the use of `toset()`, values must "
                "be static strings and not computed values"
            ),
        }
        assert {"name": "key_arn", "description": "The Amazon Resource Name (ARN) of the key"} in details["outputs"]

    def test_a_version_less_module_id_answers_for_the_newest_and_says_so(self, index):
        details = document(index, "get_module_details", module_id="terraform-aws-modules/kms/aws")
        assert details["version"] == "4.2.2"
        assert details["notes"][0] == "module_id carried no version; answered for the newest available, 4.2.2."

    def test_a_submodule_address_answers_for_that_submodule(self, index):
        """The `iam` module's root declares nothing at all, so a caller that can
        only ask about roots gets an empty answer for the module it would write."""
        root = document(index, "get_module_details", module_id="terraform-aws-modules/iam/aws/6.8.2")
        assert root["inputs"] == [] and root["outputs"] == []
        assert "called through one of its submodules" in root["notes"][0]
        assert {"path": "modules/iam-policy",
                "source": "terraform-aws-modules/iam/aws//modules/iam-policy"} in root["submodules"]
        sub = document(index, "get_module_details",
                       module_id="terraform-aws-modules/iam/aws/6.8.2//modules/iam-policy")
        assert sub["id"] == "terraform-aws-modules/iam/aws/6.8.2//modules/iam-policy"
        assert {row["name"] for row in sub["inputs"]} >= {"name", "policy"}

    def test_latest_module_version_is_the_latest_available_here(self, index):
        latest = document(index, "get_latest_module_version", module_publisher="terraform-aws-modules",
                          module_name="kms", module_provider="aws")
        assert latest["latest_version"] == "4.2.2"
        assert latest["versions_available"] == ["4.0.0", "4.2.2"]
        assert latest["notes"][0].startswith("Latest AVAILABLE HERE")


class TestProviderGoldens:
    def test_latest_provider_version_comes_from_the_mirror_index(self, index):
        latest = document(index, "get_latest_provider_version", namespace="hashicorp", name="tls")
        assert latest["latest_version"] == "4.4.1"
        assert latest["mirrored_versions"] == ["4.3.0", "4.4.1"]

    def test_capabilities_answer_versions_and_platforms_and_decline_the_rest(self, index):
        capabilities = document(index, "get_provider_capabilities", namespace="hashicorp", name="tls",
                                version="4.3.0")
        assert capabilities["platforms"] == ["linux_amd64", "linux_arm64"]
        assert capabilities["mirrored_versions"] == ["4.3.0", "4.4.1"]
        # The honest limit: a filesystem mirror holds packages, not docs, so the
        # resource/data-source inventory is handed to AWS Docs MCP rather than
        # invented from the zip's name.
        assert "not in a filesystem mirror" in capabilities["notes"][0]
        assert responder.AWS_DOCS_HANDOFF in capabilities["notes"][0]

    def test_capabilities_default_to_the_newest_mirrored_version(self, index):
        assert document(index, "get_provider_capabilities", namespace="hashicorp",
                        name="tls")["version"] == "4.4.1"

    def test_provider_docs_decline_in_favour_of_aws_docs_mcp(self, index):
        for tool, arguments in (
            ("search_providers", {"provider_name": "aws", "provider_namespace": "hashicorp",
                                  "service_slug": "s3", "provider_document_type": "resources"}),
            ("get_provider_details", {"provider_doc_id": "8894603"}),
        ):
            assert call(index, tool, **arguments) == (
                f"{tool} is not available in this environment; {responder.AWS_DOCS_HANDOFF}"
            )

    def test_policy_tools_decline_because_no_policy_library_is_served(self, index):
        for tool, arguments in (
            ("search_policies", {"policy_query": "cis"}),
            ("get_policy_details", {"terraform_policy_id": "policies/hashicorp/CIS-Policy-Set-for-AWS/1.0.1"}),
        ):
            assert call(index, tool, **arguments) == (
                f"{tool} is not available in this environment; {responder.NO_POLICIES}"
            )


class TestMissGoldens:
    """Every miss is a SUCCESSFUL result whose text names what does exist: an
    error reads to an agent as an outage worth retrying, and a bare "not found"
    reads as a bad query rather than a bounded environment."""

    def test_an_unvendored_module_names_the_allowlist(self, index):
        assert call(index, "get_module_details", module_id="terraform-aws-modules/cloudfront/aws/5.0.0") == (
            "terraform-aws-modules/cloudfront/aws is not available in this environment; "
            "available modules: acm, alb, apigateway-v2, autoscaling, dynamodb-table, ecr, ecs, "
            "eks, iam, kms, lambda, rds, route53, s3-bucket, security-group, sns, sqs, "
            "step-functions, vpc"
        )

    def test_an_unvendored_version_names_the_versions_that_exist(self, index):
        assert call(index, "get_module_details", module_id="terraform-aws-modules/kms/aws/1.0.0") == (
            "terraform-aws-modules/kms/aws 1.0.0 is not available in this environment; "
            "available versions: 4.0.0, 4.2.2"
        )

    def test_another_namespace_names_the_one_namespace_served(self, index):
        assert call(index, "get_module_details", module_id="cloudposse/s3-bucket/aws/1.0.0").startswith(
            "cloudposse/s3-bucket/aws is not available in this environment; this registry serves "
            "only terraform-aws-modules/<name>/aws, with <name> one of: acm,"
        )

    def test_an_unknown_submodule_names_the_submodules_that_exist(self, index):
        assert call(index, "get_module_details",
                    module_id="terraform-aws-modules/kms/aws/4.2.2//modules/grant") == (
            "terraform-aws-modules/kms/aws//modules/grant is not available in this environment; "
            "available submodules: none"
        )

    def test_an_unmirrored_provider_names_the_mirrored_ones(self, index):
        assert call(index, "get_latest_provider_version", namespace="kreuzwerker", name="docker") == (
            "kreuzwerker/docker is not available in this environment; available providers: "
            "hashicorp/aws, hashicorp/tls"
        )

    def test_an_unmirrored_provider_version_names_the_mirrored_ones(self, index):
        assert call(index, "get_provider_capabilities", namespace="hashicorp", name="aws",
                    version="5.0.0") == (
            "hashicorp/aws 5.0.0 is not available in this environment; mirrored versions: 6.66.0"
        )

    def test_no_mirror_at_all_says_so_rather_than_naming_a_provider(self):
        bare = responder.Index(responder.Manifest(VENDORED), responder.ProviderMirror(Path("/nonexistent")))
        assert call(bare, "get_latest_provider_version", namespace="hashicorp", name="aws") == (
            "hashicorp/aws is not available in this environment; no provider mirror is present "
            "in this process, so no provider can be described here"
        )

    def test_every_miss_ends_on_the_one_unavailable_phrase(self, index):
        phrase = responder.UNAVAILABLE.format(what="x").removeprefix("x ")
        for tool, arguments in (
            ("get_module_details", {"module_id": "terraform-aws-modules/cloudfront/aws/1.0.0"}),
            ("get_latest_module_version", {"module_publisher": "terraform-aws-modules",
                                           "module_name": "cloudfront", "module_provider": "aws"}),
            ("get_latest_provider_version", {"namespace": "kreuzwerker", "name": "docker"}),
            ("get_provider_capabilities", {"namespace": "kreuzwerker", "name": "docker"}),
            ("search_providers", {"provider_name": "aws", "provider_namespace": "hashicorp",
                                  "service_slug": "s3", "provider_document_type": "resources"}),
            ("search_policies", {"policy_query": "cis"}),
        ):
            assert phrase in call(index, tool, **arguments)


class TestArgumentErrors:
    """The one thing reported as an MCP error: a caller mistake the caller can
    fix. A missing argument answered as a miss would read as "this module does
    not exist", which is a false statement about the environment."""

    @pytest.mark.parametrize("tool,arguments", [
        ("get_module_details", {}),
        ("get_module_details", {"module_id": "s3-bucket"}),
        ("get_latest_module_version", {"module_name": "kms", "module_provider": "aws"}),
        ("get_latest_provider_version", {"namespace": "hashicorp"}),
        ("search_modules", {"module_query": "kms", "current_offset": -1}),
        ("search_modules", {"module_query": "kms", "current_offset": 1.5}),
    ])
    def test_a_malformed_argument_raises(self, index, tool, arguments):
        with pytest.raises(responder.ArgumentError):
            index.call(tool, arguments)

    def test_an_empty_query_is_not_an_error(self, index):
        """`module_query = ""` is the honest way to ask what this environment
        holds, and the HTTP search endpoint already answers it."""
        assert document(index, "search_modules", module_query="  ")["total"] > 0


# ---------------------------------------------------------------------------
# honesty about what cannot be read, and about what must not be revealed
# ---------------------------------------------------------------------------


def all_details(index) -> list[dict]:
    manifest = responder.Manifest(VENDORED)
    return [
        document(index, "get_module_details", module_id=f"terraform-aws-modules/{name}/aws/{version}")
        for name, version in sorted(manifest.modules)
    ]


class TestHonesty:
    def test_an_unreadable_description_is_named_not_shown_and_never_guessed(self, index):
        """`rds`' `master_user_secret_kms_key_id` writes its description as a
        heredoc, which this reader does not evaluate. It is the live example of
        the rule: the field is listed in `not_shown` and absent from the row,
        rather than carrying a value the tool invented."""
        details = document(index, "get_module_details", module_id="terraform-aws-modules/rds/aws/7.2.2")
        row = next(r for r in details["inputs"] if r["name"] == "master_user_secret_kms_key_id")
        assert row == {"name": "master_user_secret_kms_key_id", "required": False,
                       "type": "string", "default": "null", "not_shown": ["description"]}
        assert any("not_shown" in note and "never guessed" in note for note in details["notes"])

    def test_no_row_anywhere_carries_a_field_it_reported_as_not_shown(self, index):
        for details in all_details(index):
            for row in details["inputs"] + details["outputs"] + details["provider_requirements"]:
                for field in row.get("not_shown", []):
                    assert field not in row, (details["id"], row)

    def test_every_vendored_module_answers_with_a_readable_interface(self, index):
        """1257 inputs and 415 outputs across the tree; the ones this reader
        cannot read are countable and small. A parser regression shows up as this
        number moving, not as a module quietly answering nothing."""
        unreadable = [d["id"] for d in all_details(index) if d.get("unreadable_files")]
        assert unreadable == []
        not_shown = sum(1 for d in all_details(index) for row in d["inputs"] if row.get("not_shown"))
        assert not_shown == 1

    def test_no_answer_marks_a_decoy(self, index):
        """A decoy that advertised itself would hand the agent the module-selection
        answer this arm measures; the manifest carries no such flag and neither
        may any answer built from it (`arms/hcl-modules/README.md`, Amendment 46)."""
        answers = [call(index, "search_modules", module_query="")] + [json.dumps(d) for d in all_details(index)]
        for answer in answers:
            assert "decoy" not in answer.lower()


class TestDeterminism:
    def test_two_calls_are_byte_identical(self, index):
        for tool, arguments in (
            ("search_modules", {"module_query": "bucket"}),
            ("get_module_details", {"module_id": "terraform-aws-modules/s3-bucket/aws/5.16.1"}),
            ("get_provider_capabilities", {"namespace": "hashicorp", "name": "tls"}),
        ):
            assert index.call(tool, arguments) == index.call(tool, arguments)

    def test_a_second_process_worth_of_state_is_byte_identical(self, index, mirror_root):
        """A fresh Index over the same bytes: nothing in an answer depends on
        what was asked before it, so a trial's nth call cannot differ from a
        replay's first."""
        fresh = responder.Index(responder.Manifest(VENDORED), responder.ProviderMirror(mirror_root))
        for tool, arguments in (
            ("search_modules", {"module_query": ""}),
            ("get_module_details", {"module_id": "terraform-aws-modules/eks/aws/21.25.1"}),
            ("get_latest_provider_version", {"namespace": "hashicorp", "name": "aws"}),
        ):
            assert fresh.call(tool, arguments) == index.call(tool, arguments)


# ---------------------------------------------------------------------------
# over the wire: one stdlib MCP client, and the offline guarantee
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def served(mirror_root):
    with tf_registry.running_registry(VENDORED, mirror_root=mirror_root) as env:
        yield env


def tool_call(env, name: str, arguments: dict, session: str | None = None) -> dict:
    _, payload, _ = rpc(env, {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, session)
    return payload["result"]


class TestOverMcp:
    def test_a_full_client_round_trip_reaches_every_tool(self, served):
        """initialize, the initialized notification, tools/list, then one call per
        advertised tool on that session -- the sequence a client actually runs."""
        _, handshake, headers = rpc(served, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        session = headers["Mcp-Session-Id"]
        assert handshake["result"]["protocolVersion"] == responder.PROTOCOL_VERSION
        status, body, _ = rpc(served, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
        assert (status, body) == (202, None)
        _, listed, _ = rpc(served, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
        advertised = {tool["name"] for tool in listed["result"]["tools"]}
        assert advertised == set(responder.TOOL_NAMES)
        arguments = {
            "search_modules": {"module_query": "kms"},
            "get_module_details": {"module_id": "terraform-aws-modules/kms/aws/4.2.2"},
            "get_latest_module_version": {"module_publisher": "terraform-aws-modules",
                                          "module_name": "kms", "module_provider": "aws"},
            "search_providers": {"provider_name": "aws", "provider_namespace": "hashicorp",
                                 "service_slug": "kms", "provider_document_type": "resources"},
            "get_provider_details": {"provider_doc_id": "8894603"},
            "get_latest_provider_version": {"namespace": "hashicorp", "name": "aws"},
            "get_provider_capabilities": {"namespace": "hashicorp", "name": "aws"},
            "search_policies": {"policy_query": "cis"},
            "get_policy_details": {"terraform_policy_id": "policies/hashicorp/x/1.0.0"},
        }
        for name in sorted(advertised):
            result = tool_call(served, name, arguments[name], session)
            assert result["isError"] is False, name
            assert result["content"][0]["type"] == "text"
            assert result["content"][0]["text"].strip(), name

    def test_the_wire_answer_is_the_in_process_answer(self, served, index):
        result = tool_call(served, "get_module_details",
                           {"module_id": "terraform-aws-modules/s3-bucket/aws/5.16.1"})
        assert result["content"][0]["text"] == call(
            index, "get_module_details", module_id="terraform-aws-modules/s3-bucket/aws/5.16.1"
        )

    def test_a_malformed_argument_is_the_one_error_result(self, served):
        result = tool_call(served, "get_module_details", {"module_id": "s3-bucket"})
        assert result["isError"] is True
        assert result["content"][0]["text"].startswith("get_module_details: module_id must be")

    def test_a_miss_over_the_wire_is_still_a_successful_result(self, served):
        result = tool_call(served, "get_module_details", {"module_id": "terraform-aws-modules/vpn/aws/1.0.0"})
        assert result["isError"] is False
        assert "available modules:" in result["content"][0]["text"]

    def test_an_unknown_tool_is_a_jsonrpc_error(self, served):
        _, payload, _ = rpc(served, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                     "params": {"name": "apply_terraform", "arguments": {}}})
        assert payload["error"]["code"] == -32602

    def test_the_search_endpoint_and_the_index_tool_agree_on_what_exists(self, served, index):
        """Design C (the untuned row's search endpoint) and design B (the tuned
        row's index tool) are one process over one manifest, so they cannot
        disagree about the allowlist -- which is what makes the two equipping
        levels differ in DISCOVERY TOOLING only, not in what is available."""
        _, body, _ = get(served, "/v1/modules/search?q=")
        endpoint = {hit["source"] for hit in json.loads(body)["modules"]}
        listed = set()
        offset = 0
        while True:
            page = document(index, "search_modules", module_query="", current_offset=offset)
            listed.update(module["source"] for module in page["modules"])
            if "next_offset" not in page:
                break
            offset = page["next_offset"]
        assert endpoint == listed


def test_the_index_tool_opens_no_outbound_connection(mirror_root, tmp_path):
    """The offline guarantee, extended to the new code paths: every one of the
    nine tools plus a miss, under a `socket.connect` audit hook. One recorded
    connect would mean an answer could come from the public registry, which is
    the single failure this arm's offline guarantee cannot tolerate."""
    connects = tmp_path / "connects.log"
    launcher = tmp_path / "audited_responder.py"
    launcher.write_text(textwrap.dedent(f"""
        import runpy, sys

        def hook(event, args):
            if event == "socket.connect":
                with open({str(connects)!r}, "a") as fh:
                    fh.write(repr(args) + "\\n")

        sys.addaudithook(hook)
        sys.argv = ["responder.py", "--root", {str(VENDORED)!r}, "--port", "0",
                    "--mirror-root", {str(mirror_root)!r}]
        runpy.run_path({str(tf_registry.RESPONDER)!r}, run_name="__main__")
    """))
    proc = subprocess.Popen([sys.executable, str(launcher)], stdout=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline().strip().removeprefix("PORT="))
        env = {tf_registry.URL_VAR: f"http://127.0.0.1:{port}"}
        for name in responder.TOOL_NAMES:
            # Empty arguments on purpose: an argument error must not reach a
            # socket either, and the loop then needs no per-tool table.
            tool_call(env, name, {})
        tool_call(env, "get_module_details", {"module_id": "terraform-aws-modules/kms/aws/4.2.2"})
        tool_call(env, "get_latest_provider_version", {"namespace": "hashicorp", "name": "aws"})
        tool_call(env, "get_module_details", {"module_id": "terraform-aws-modules/vpn/aws/1.0.0"})
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        proc.stdout.close()
    assert not connects.exists(), connects.read_text()


@pytest.mark.skipif(
    not (REPO_ROOT / ".cache" / "falsifiability-tf-mirror" / "hcl_modules" / "mirror").is_dir(),
    reason="no docker cp'ed provider mirror under .cache (run make falsifiability or build-arms)",
)
def test_the_real_mirror_answers_every_provider_the_arm_pins():
    """Against the mirror `docker cp`ed out of the arm image itself, not the fake
    one: the eight sources `environment/mirror-src/main.tf` declares are the
    providers this tool must be able to name."""
    mirror = REPO_ROOT / ".cache" / "falsifiability-tf-mirror" / "hcl_modules" / "mirror"
    index = responder.Index(responder.Manifest(VENDORED), responder.ProviderMirror(mirror))
    declared = set(re.findall(
        r'source\s+=\s+"(hashicorp/[a-z]+)"',
        (VENDORED.parent / "mirror-src" / "main.tf").read_text(),
    ))
    assert declared, "mirror-src/main.tf declared no provider"
    for address in sorted(declared):
        namespace, name = address.split("/")
        answer = document(index, "get_provider_capabilities", namespace=namespace, name=name)
        assert answer["mirrored_versions"], address
        assert answer["platforms"], address
