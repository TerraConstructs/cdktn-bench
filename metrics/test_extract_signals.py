"""The importable half of metrics/extract_signals.py: rbw and escape-hatch.

The CLI was analysis-only and untested (docs/signal-extraction.md §3). These
cover the two signals the published row now carries, including the token
double-counting trap the module's own docstring warns about.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gates.tests.conftest import ARMS, FIXTURES_DIR  # noqa: E402
from metrics.extract_signals import ENTRY, ESCAPE, arm_of, trial_signals  # noqa: E402


def write_session(trial_dir: Path, messages, step: str | None = None) -> Path:
    base = trial_dir / ("steps/" + step if step else "")
    d = base / "agent" / "sessions" / "projects" / "-app-project"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "session.jsonl"
    path.write_text("".join(json.dumps(m) + "\n" for m in messages))
    return path


def assistant(mid, tokens, blocks, *, repeat_usage=1):
    """One assistant message, optionally emitted once per content block -- which
    is what a real session jsonl does, repeating `usage` every time."""
    return [
        {"type": "assistant", "message": {"id": mid, "usage": {"output_tokens": tokens}, "content": blocks}}
        for _ in range(repeat_usage)
    ]


def tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def test_every_known_arm_has_an_entry_file_and_an_escape_rule():
    # A new arm must arrive with both, or its rows silently report rbw null and
    # escape "n/a" as if it had no abstraction to leave.
    assert set(ENTRY) == set(ARMS)
    assert set(ESCAPE) == set(ARMS)


def test_arm_of_resolves_the_fourth_arm_and_its_truncation():
    assert arm_of("singleton-child-resource-clobber-hcl-modules__abc") == "hcl-modules"
    assert arm_of("singleton-child-resource-clobber-hcl-mod__abc") == "hcl-modules"


def test_rbw_counts_output_tokens_up_to_the_first_entry_file_write(tmp_path):
    write_session(
        tmp_path,
        assistant("m1", 100, [tool("Read", file_path="/app/project/main.tf")])
        + assistant("m2", 200, [tool("Grep", pattern="aws_s3")])
        + assistant("m3", 60, [tool("Write", file_path="/app/project/main.tf", content="resource {}")])
        + assistant("m4", 40, [tool("Bash", command="terraform validate")]),
    )
    signals = trial_signals(tmp_path, "hcl-raw")
    assert signals["rbw"] == {"tokens": 360, "msgs": 3, "output_tokens": 400, "pct": 90.0}


def test_usage_repeated_per_content_block_is_deduplicated_by_message_id(tmp_path):
    write_session(
        tmp_path,
        assistant("m1", 100, [tool("Read", file_path="/app/project/main.tf")], repeat_usage=3)
        + assistant("m2", 100, [tool("Write", file_path="/app/project/main.tf", content="x")], repeat_usage=2),
    )
    signals = trial_signals(tmp_path, "hcl-raw")
    assert signals["rbw"]["output_tokens"] == 200
    assert signals["rbw"]["msgs"] == 2


def test_a_bash_redirect_into_the_entry_file_is_a_mutation(tmp_path):
    write_session(
        tmp_path,
        assistant("m1", 50, [tool("Read", file_path="/app/project/main.tf")])
        + assistant("m2", 10, [tool("Bash", command="cat <<'EOF' > main.tf\nresource {}\nEOF")]),
    )
    assert trial_signals(tmp_path, "hcl-raw")["rbw"]["tokens"] == 60


def test_no_entry_file_write_is_null_tokens_not_zero(tmp_path):
    write_session(tmp_path, assistant("m1", 100, [tool("Read", file_path="/app/project/README.md")]))
    rbw = trial_signals(tmp_path, "hcl-raw")["rbw"]
    assert rbw["tokens"] is None and rbw["pct"] is None
    assert rbw["output_tokens"] == 100


def test_no_transcript_at_all_is_none_not_an_empty_reading(tmp_path):
    assert trial_signals(tmp_path, "hcl-raw") is None


@pytest.mark.parametrize(
    "arm,body,expected",
    [
        ("awscdk", "new s3.CfnBucket(this, 'B', {});", "yes"),
        ("awscdk", "new s3.Bucket(this, 'B');", "no"),
        ("terraconstructs", "import { AwsProvider } from 'x/provider/aws';", "yes"),
        ("terraconstructs", "new S3Bucket(this, 'B', {});", "no"),
        ("hcl-modules", 'resource "aws_s3_bucket" "this" {}', "yes"),
        ("hcl-modules", 'module "b" {\n  source = "terraform-aws-modules/s3-bucket/aws"\n}', "no"),
        # hcl-raw is provider resources by construction: "n/a", never "no".
        ("hcl-raw", 'resource "aws_s3_bucket" "this" {}', "n/a"),
    ],
)
def test_escape_hatch_per_arm(tmp_path, arm, body, expected):
    entry = ENTRY[arm][0]
    write_session(tmp_path, assistant("m1", 10, [tool("Write", file_path="/app/project/" + entry, content=body)]))
    assert trial_signals(tmp_path, arm)["escape_hatch"] == expected


def test_escape_hatch_is_ever_used_across_steps_and_rbw_is_the_final_steps(tmp_path):
    entry = "/app/project/lib/scenario-stack.ts"
    write_session(
        tmp_path,
        assistant("a1", 100, [tool("Write", file_path=entry, content="new s3.CfnBucket(this, 'B', {});")]),
        step="01-initial",
    )
    write_session(
        tmp_path,
        assistant("b1", 300, [tool("Read", file_path=entry)])
        + assistant("b2", 100, [tool("Write", file_path=entry, content="new s3.Bucket(this, 'B');")]),
        step="02-change-request",
    )
    signals = trial_signals(tmp_path, "awscdk")
    assert signals["escape_hatch"] == "yes"
    # A share is never summed across steps: the top-level numbers are step 2's.
    assert signals["rbw"]["pct"] == 100.0
    assert signals["rbw"]["output_tokens"] == 400
    assert set(signals["rbw"]["steps"]) == {"01-initial", "02-change-request"}
    assert signals["rbw"]["steps"]["01-initial"]["pct"] == 100.0


@pytest.mark.parametrize("arm", ARMS)
def test_the_gate_fixtures_carry_a_readable_transcript(arm):
    signals = trial_signals(FIXTURES_DIR / arm / "genuine", arm)
    assert signals["rbw"]["pct"] == 90.0
    assert signals["escape_hatch"] in ("yes", "no", "n/a")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("new cdk.CfnOutput(this, 'ApiUrl', { value: url });", "no"),
        ("new cdk.CfnParameter(this, 'Env');", "no"),
        ("new cdk.CfnCondition(this, 'IsProd');", "no"),
        ("new apigw.CfnDeployment(this, 'D', {});", "yes"),
        ("bucket.node.defaultChild as s3.CfnBucket;", "yes"),
        ("(role.node.defaultChild as iam.CfnRole).addPropertyOverride('X', 1);", "yes"),
    ],
)
def test_template_plumbing_is_not_an_escape_hatch(tmp_path, source, expected):
    """ROADMAP §3 finding 5 was a `CfnOutput` matched by a bare `Cfn[A-Z]\\w+`.
    The flag is published now, so plumbing with no L2 to leave must not set it."""
    write_session(
        tmp_path,
        assistant("m1", 10, [tool("Write", file_path="/app/project/lib/scenario-stack.ts", content=source)]),
    )
    assert trial_signals(tmp_path, "awscdk")["escape_hatch"] == expected
