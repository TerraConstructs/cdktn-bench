"""gates/tests/test_apigw_redeploy_offline_state.py -- regression test for
B3 (CONTEXT's "Slice G fix round" naming): RESIDUAL TERRAFORM STATE BREAKS
THE OFFLINE STATIC TIER.

The bug: after a real live `terraform apply` (this scenario's whole point --
see specs/apigw-redeploy.yaml), the working tree's `terraform.tfstate` (or,
on terraconstructs, `cdktf.out/stacks/apigw-redeploy/terraform.tfstate`)
names a REAL, previously-applied REST API/Lambda/IAM role. `tests/
static_tiers.sh` then runs `terraform init && terraform plan` OFFLINE
(dummy provider credentials, no network) to grade the FINAL delivered file
-- by DEFAULT, `terraform plan` refreshes every resource already tracked in
state, which means a real `GetRestApi`/`GetFunction` call against AWS,
which fails offline (network error, or a 403 against the dummy
credentials) -- scoring a PERFECT solution reward 0.0 for a reason that has
nothing to do with its own correctness. The fix (DECISIONS.md Slice G
amendment): `-refresh=false` on this scenario's `terraform plan` invocation
(both hcl_raw's spec-level `plan_command` and terraconstructs' generator-
hardcoded tf-plan step, gen.py's `build_static_tiers_sh`), gated on
`spec.verifier.live_check.enabled` so every other spec's generated output
is unaffected (see that gate's own comment).

`test_hcl_raw_residual_state_does_not_break_static_tier_offline` is the
real, deep proof: stages a sandbox with the CORRECT solution's final
(revision-2) main.tf, hand-crafts a real, schema-conformant
`terraform.tfstate` naming a real-looking `aws_api_gateway_rest_api` (built
from this exact provider version's own `terraform providers schema -json`
output, not guessed field names), and proves BOTH directions:
  (a) the CURRENT (fixed) generated tests/static_tiers.sh reaches reward
      1.0 despite the residual state, with AWS credential env vars scrubbed
      (so a regression that silently reintroduced a live network dependency
      would fail loudly here, not pass by accident against a developer's
      own ambient credentials);
  (b) reverting the fix (stripping `-refresh=false` back out, simulating
      the pre-fix generated script) makes the SAME sandbox+state FAIL --
      proving this fixture genuinely exercises the refresh code path
      instead of vacuously passing regardless of the flag.

`test_terraconstructs_static_tiers_sh_has_refresh_false` covers the other
arm structurally (the generated tf-plan step must contain the flag) plus a
real, un-seeded end-to-end run (npm ci + cdktn synth + terraform init/plan)
proving the flag's addition didn't regress the ordinary (no residual state)
path. A full hand-crafted-state deep proof was attempted for this arm too
(same technique as hcl_raw) and abandoned: aws_api_gateway_rest_api's
refresh path in the AWS provider's legacy-SDK CRUD silently tolerates a
malformed/incomplete synthetic prior state (a `[WARN] ... produced an
invalid plan ... tolerating it because it is using the legacy plugin SDK`)
rather than erroring or genuinely attempting the network read, which makes
a hand-built fixture non-deterministic proof material for THIS arm
specifically -- a fixture-construction limitation, not evidence the fix
itself is arm-specific (terraform's `-refresh=false` flag has identical,
provider-agnostic semantics on both arms; only hcl_raw's proof needed to be
this deep to be worth the toolchain cost, mirroring
test_oracle_falsifiability.py's own "hcl_raw only, smallest footprint"
precedent).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from oracles.tests.toolcheck import find_tool

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_PATH = REPO_ROOT / "specs" / "apigw-redeploy.yaml"

sys.path.insert(0, str(REPO_ROOT / "generator"))
from gen import ARM_WORKSPACE_SUBDIR, task_dir  # noqa: E402
from spec_model import load_spec  # noqa: E402

requires_hcl_raw_toolchain = pytest.mark.skipif(
    find_tool("terraform") is None or find_tool("jq") is None,
    reason="terraform and/or jq not found on PATH -- see toolcheck.find_tool",
)
requires_terraconstructs_toolchain = pytest.mark.skipif(
    find_tool("terraform") is None
    or find_tool("jq") is None
    or find_tool("npm") is None
    or find_tool("node") is None,
    reason="terraform/jq/npm/node not all found on PATH -- see toolcheck.find_tool",
)

# Kept minimal and self-contained (not extracted from solution/solve.sh's
# own heredocs) so this fixture doesn't silently go stale/desync if solve.sh
# is edited for unrelated reasons -- this main.tf only needs to be A
# structurally valid revision-2 delivered file (rest_api + 3 methods incl.
# one MOCK + a triggers-bearing deployment), not byte-identical to
# solution/solve.sh's own write_rev2().
_REV2_MAIN_TF = """\
resource "aws_iam_role" "lambda_exec" {
  name = "apigw-redeploy-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "hello" {
  function_name    = "apigw-redeploy-hello"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/hello.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/hello.zip")
}

resource "aws_api_gateway_rest_api" "api" {
  name = "apigw-redeploy-api"
}

resource "aws_api_gateway_resource" "hello" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "hello"
}

resource "aws_api_gateway_method" "hello_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.hello.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "hello_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.hello.id
  http_method             = aws_api_gateway_method.hello_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.hello.invoke_arn
}

resource "aws_api_gateway_resource" "status" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "status"
}

resource "aws_api_gateway_method" "status_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.status.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_method_response" "status_get_200" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  status_code = "200"
  response_models = {
    "application/json" = "Empty"
  }
}

resource "aws_api_gateway_integration" "status_get" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  type        = "MOCK"
  request_templates = {
    "application/json" = "{\\"statusCode\\": 200}"
  }
}

resource "aws_api_gateway_integration_response" "status_get_200" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.status.id
  http_method = aws_api_gateway_method.status_get.http_method
  status_code = aws_api_gateway_method_response.status_get_200.status_code
  response_templates = {
    "application/json" = jsonencode({ status = "ok", routes = 3 })
  }
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.hello.path_part,
      aws_api_gateway_method.hello_get.http_method,
      aws_api_gateway_integration.hello_get.type,
      aws_api_gateway_resource.status.path_part,
      aws_api_gateway_method.status_get.http_method,
      aws_api_gateway_integration.status_get.type,
      aws_api_gateway_integration.status_get.request_templates,
      aws_api_gateway_integration_response.status_get_200.response_templates,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.hello_get,
    aws_api_gateway_integration.status_get,
    aws_api_gateway_integration_response.status_get_200,
  ]
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.this.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = "prod"
}

output "api_url" {
  value = "${aws_api_gateway_stage.prod.invoke_url}/"
}
"""


def _stage_hcl_raw_sandbox(tmp: Path, spec) -> Path:
    """Build a `<tmp>/project` sandbox: this spec's hcl_raw workspace +
    tests/, the fixture rev2 main.tf, and real (tiny, valid) Lambda zips --
    everything `tests/static_tiers.sh` needs to run exactly as it would in a
    real trial, minus the AWS credentials it must NOT need."""
    task = task_dir(spec, "hcl_raw")
    project = tmp / "project"
    logs = tmp / "logs" / "verifier"
    logs.mkdir(parents=True)
    shutil.copytree(task / "environment" / ARM_WORKSPACE_SUBDIR["hcl_raw"], project, dirs_exist_ok=True)
    shutil.copytree(task / "tests", project / "tests", dirs_exist_ok=True)

    (project / "main.tf").write_text(_REV2_MAIN_TF)
    lambda_dir = project / "lambda"
    lambda_dir.mkdir(exist_ok=True)
    src_dir = project / "lambda-src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "index.js").write_text("exports.handler = async () => ({ statusCode: 200, body: 'hello' });")
    subprocess.run(
        ["zip", "-q", "-X", str(lambda_dir / "hello.zip"), "index.js"],
        cwd=src_dir, check=True, capture_output=True,
    )

    static_tiers = project / "tests" / "static_tiers.sh"
    text = static_tiers.read_text()
    text = text.replace("/logs/verifier", str(logs))
    text = text.replace("/app/project", str(project))
    static_tiers.write_text(text)
    return project


def _write_residual_rest_api_state(project: Path, schema_path: Path) -> None:
    """Write a real, `terraform providers schema -json`-conformant
    `terraform.tfstate` at `project`'s root, naming ONE resource --
    `aws_api_gateway_rest_api.api`, matching this fixture's own
    `_REV2_MAIN_TF` address -- with a real-looking id/name/arn. Every other
    attribute is a type-appropriate zero value (built from the schema, not
    guessed), so terraform's state decoder accepts it without complaint.
    Deliberately the ONLY resource in state (the rest of `_REV2_MAIN_TF`'s
    resources are absent, so they simply plan as ordinary creates) --
    minimal and sufficient to trigger a live refresh attempt against this
    one resource, exactly what a real prior `terraform apply` would leave
    behind for the REST API specifically."""
    schema = json.loads(schema_path.read_text())
    resource_schemas = schema["provider_schemas"]["registry.terraform.io/hashicorp/aws"]["resource_schemas"]
    rest_api_schema = resource_schemas["aws_api_gateway_rest_api"]
    attrs_schema = rest_api_schema["block"]["attributes"]

    def default_for(t):
        if isinstance(t, str):
            return {"string": "x", "bool": False, "number": 0}.get(t)
        if isinstance(t, list):
            kind = t[0]
            if kind in ("list", "set"):
                return []
            if kind == "map":
                return {}
            if kind == "object":
                return {k: default_for(v) for k, v in t[1].items()}
        return None

    values = {name: default_for(spec["type"]) for name, spec in attrs_schema.items()}
    values.update(
        {
            "id": "a1b2c3d4e5",
            "name": "apigw-redeploy-api",
            "arn": "arn:aws:apigateway:us-east-1::/restapis/a1b2c3d4e5",
            "execution_arn": "arn:aws:execute-api:us-east-1:123456789012:a1b2c3d4e5",
            "root_resource_id": "r00t0000",
            "created_date": "2026-08-06T00:00:00Z",
            "tags": {},
            "tags_all": {},
            "endpoint_configuration": [],
            "minimum_compression_size": None,
        }
    )
    state = {
        "version": 4,
        "terraform_version": "1.15.8",
        "serial": 1,
        "lineage": "gates-tests-b3-regression-fixture",
        "outputs": {},
        "resources": [
            {
                "mode": "managed",
                "type": "aws_api_gateway_rest_api",
                "name": "api",
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [
                    {"schema_version": rest_api_schema.get("version", 0), "attributes": values}
                ],
            }
        ],
        "check_results": None,
    }
    (project / "terraform.tfstate").write_text(json.dumps(state, indent=2))


def _clean_aws_env() -> dict:
    """A subprocess env with every AWS credential/profile var scrubbed --
    the sandbox must pass on the fix's own merits (`-refresh=false`), not
    because it happened to inherit real credentials from the host shell."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("AWS_"):
            del env[k]
    return env


@requires_hcl_raw_toolchain
def test_hcl_raw_residual_state_does_not_break_static_tier_offline() -> None:
    spec = load_spec(SPEC_PATH)
    assert spec.verifier.live_check.enabled, "this test only makes sense for the live-check-enabled spec"

    with tempfile.TemporaryDirectory(prefix="apigw-redeploy-b3-") as tmp_s:
        tmp = Path(tmp_s)
        project = _stage_hcl_raw_sandbox(tmp, spec)

        # `terraform init` first (needed either way, to fetch/mirror the
        # provider and to compute `terraform providers schema -json`).
        init = subprocess.run(
            ["terraform", "init", "-input=false"], cwd=project, capture_output=True, text=True, env=_clean_aws_env(),
        )
        assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

        schema_json = project / "_schema.json"
        schema_proc = subprocess.run(
            ["terraform", "providers", "schema", "-json"], cwd=project, capture_output=True, text=True, env=_clean_aws_env(),
        )
        assert schema_proc.returncode == 0, schema_proc.stderr
        schema_json.write_text(schema_proc.stdout)

        _write_residual_rest_api_state(project, schema_json)

        static_tiers = project / "tests" / "static_tiers.sh"
        fixed_text = static_tiers.read_text()
        assert "-refresh=false" in fixed_text, (
            "expected the generated static_tiers.sh's terraform plan step to "
            "carry -refresh=false (B3 fix, DECISIONS.md Slice G amendment) -- "
            "if this assertion fails, the fix regressed at the generator/spec "
            "level before this test ever got a chance to prove it works"
        )

        # (a) THE FIX: current (generated) static_tiers.sh, with the residual
        # state present and AWS credentials scrubbed, must still reach
        # reward 1.0.
        proc = subprocess.run(
            ["bash", str(static_tiers)], cwd=project, capture_output=True, text=True, env=_clean_aws_env(),
        )
        reward_file = tmp / "logs" / "verifier" / "reward.txt"
        assert reward_file.exists(), f"no reward.txt written; stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        reward = float(reward_file.read_text().strip())
        assert reward == 1.0, (
            f"expected reward 1.0 despite residual state naming a real-looking "
            f"REST API (proves the -refresh=false fix), got {reward!r}. "
            f"stdout:\n{proc.stdout[-4000:]}"
        )

        # (b) NEGATIVE CONTROL: revert the fix (strip -refresh=false back
        # out, simulating the pre-fix generated script) against the exact
        # same sandbox+state -- this must now FAIL, proving (a) wasn't a
        # vacuous pass (e.g. terraform silently ignoring the malformed
        # state regardless of the flag).
        reverted_text = fixed_text.replace(" -refresh=false", "")
        assert reverted_text != fixed_text, "the -refresh=false string substitution did not change anything"
        static_tiers.write_text(reverted_text)
        reward_file.unlink()

        proc2 = subprocess.run(
            ["bash", str(static_tiers)], cwd=project, capture_output=True, text=True, env=_clean_aws_env(),
        )
        assert reward_file.exists(), f"no reward.txt written on the reverted run; stdout:\n{proc2.stdout}"
        reward2 = float(reward_file.read_text().strip())
        assert reward2 == 0.0, (
            "negative control failed: reverting -refresh=false against the "
            "SAME residual state was expected to score 0.0 (a real offline "
            "network/credential failure during refresh) -- if this now also "
            "scores 1.0, the fixture no longer exercises the refresh code "
            f"path and this test is not proving anything. stdout:\n{proc2.stdout[-4000:]}"
        )


@requires_terraconstructs_toolchain
def test_terraconstructs_static_tiers_sh_has_refresh_false() -> None:
    """Structural + end-to-end-without-residual-state proof for the other
    TF-shaped arm -- see this module's own docstring for why the deep
    hand-crafted-state proof above is hcl_raw-only."""
    spec = load_spec(SPEC_PATH)
    task = task_dir(spec, "terraconstructs")
    static_tiers_text = (task / "tests" / "static_tiers.sh").read_text()
    assert "-refresh=false" in static_tiers_text, (
        "expected apigw-redeploy's generated terraconstructs static_tiers.sh "
        "tf-plan step to carry -refresh=false (B3 fix) -- see gen.py's "
        "build_static_tiers_sh, gated on spec.verifier.live_check.enabled"
    )

    with tempfile.TemporaryDirectory(prefix="apigw-redeploy-b3-tc-") as tmp_s:
        tmp = Path(tmp_s)
        project = tmp / "project"
        logs = tmp / "logs" / "verifier"
        logs.mkdir(parents=True)
        shutil.copytree(task / "environment" / ARM_WORKSPACE_SUBDIR["terraconstructs"], project, dirs_exist_ok=True)
        shutil.copytree(task / "tests", project / "tests", dirs_exist_ok=True)
        shutil.copytree(task / "solution", project / "solution", dirs_exist_ok=True)

        (project / "lib").mkdir(exist_ok=True)
        # Reuse the reference solution's own revision-2 stack (kept in sync
        # with the real solve.sh, unlike this file's hcl_raw fixture, since
        # this test doesn't need to inject state mid-flow -- it just needs
        # ANY structurally-correct final delivered file).
        solve_text = (task / "solution" / "solve.sh").read_text()
        m = re.search(r"write_rev2\(\) \{\n  cat > lib/scenario-stack\.ts <<'TS'\n(.*?)\nTS\n\}", solve_text, re.DOTALL)
        assert m, "could not extract write_rev2()'s heredoc body from solution/solve.sh"
        (project / "lib" / "scenario-stack.ts").write_text(m.group(1) + "\n")

        subprocess.run(
            ["npm", "ci", "--no-audit", "--no-fund"], cwd=project, check=True, capture_output=True, text=True,
        )

        static_tiers = project / "tests" / "static_tiers.sh"
        text = static_tiers.read_text()
        text = text.replace("/logs/verifier", str(logs))
        text = text.replace("/app/project", str(project))
        static_tiers.write_text(text)

        proc = subprocess.run(
            ["bash", str(static_tiers)], cwd=project, capture_output=True, text=True, env=_clean_aws_env(),
        )
        reward_file = logs / "reward.txt"
        assert reward_file.exists(), f"no reward.txt written; stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        reward = float(reward_file.read_text().strip())
        assert reward == 1.0, (
            f"expected reward 1.0 for the correct solution with -refresh=false "
            f"added (no residual state involved -- proves the fix doesn't "
            f"regress the ordinary path), got {reward!r}. stdout:\n{proc.stdout[-4000:]}"
        )
