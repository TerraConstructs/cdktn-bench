#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), Slice G (apigw-redeploy). hcl_raw only (this catch has no
# meaningful equivalent on awscdk/terraconstructs -- both L2 arms make the
# equivalent mistake structurally impossible, see those arms' own solve.sh
# headers).
#
# IDENTICAL to solution/solve.sh's revision 1 AND revision 2 EXCEPT: the
# aws_api_gateway_deployment resource has NO `triggers` block at all.
# `depends_on` is left CORRECT and grows exactly like the correct
# solution's does in revision 2 -- deliberately, to isolate this fixture to
# ONLY the missing-triggers catch (a tier-1 depends_on-coverage check, e.g.
# the deployment-depends-on-all-methods style check from apigw-openapi's
# own oracle, still finds every integration correctly listed and PASSES).
#
# THE POINT: every existing static tier (tier-0 existence/shape checks,
# route-count-correct, deployment-depends-on-all-methods) passes IDENTICALLY
# to the correct solution -- verified below, this file's own OFFLINE run
# reaches the exact same "3 methods, rest_api + deployment present" tier-0
# facts revision 2 as solution/solve.sh does. What is invisible to ANY
# static synth/plan diff (single- or two-plan) is the LIVE consequence,
# documented in docs/apigw-redeploy-mechanics.md §3/§6(c): Terraform only
# replaces a resource when one of ITS OWN configured arguments changes;
# `depends_on` is a graph-ordering meta-argument, not a diffable resource
# argument, and `rest_api_id` (the only real argument
# aws_api_gateway_deployment has left once `triggers` is gone) never
# changes between revisions. On a REAL second `terraform apply`:
#   `terraform plan` shows "0 to change" for aws_api_gateway_deployment.this
#   even though GET /status was just added elsewhere in the same apply --
#   the Stage keeps pointing at the OLD deployment ID. GET /status 404s
#   live while `terraform apply` exits 0 with no error and no warning.
# This is exactly the trap docs/apigw-redeploy-mechanics.md §5 names as
# "the classic aws_api_gateway_deployment footgun" for hand-written HCL,
# specialized to the redeploy-on-change (not first-deploy) failure mode.
#
# Same LIVE switch as solution/solve.sh (see that file's header): the
# default run stops at `terraform plan`, LIVE=1 really applies.
# LIVE mode here is expected to demonstrate the FAILURE (200/200/404 on
# hello/version/status after the second apply, not a script bug) --
# this file still exits non-zero on that outcome (a "did the trap fire"
# check), matching the discriminating-negative role this fixture plays
# per the task brief: it must PASS static tiers and FAIL live.
set -euo pipefail

LIVE="${LIVE:-0}"
PROJECT_DIR="$(pwd)"
mkdir -p lambda lambda-src

write_lambda_zips() {
  cat > lambda-src/hello.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: "hello" });
JS
  cat > lambda-src/version.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: "1.0.0" }) });
JS
  ( cd lambda-src && cp hello.js index.js && zip -q -X ../lambda/hello.zip index.js && rm index.js )
  ( cd lambda-src && cp version.js index.js && zip -q -X ../lambda/version.zip index.js && rm index.js )
}

# This script writes no provider.tf of its own -- same rule as
# solution/solve.sh. The SEEDED ./provider.tf is not agent-owned and
# carries a bare `provider "aws"` block that resolves ambient AWS
# credentials.

write_rev1() {
  cat > main.tf <<'TF'
resource "aws_iam_role" "lambda_exec" {
  name = "apigw-redeploy-lambda-exec"
  # Amendment 16's flagged gap -- see solution/solve.sh's identical comment.
  path = "/cdktn-bench-task/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "hello" {
  function_name    = "apigw-redeploy-hello"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/hello.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/hello.zip")
}

resource "aws_lambda_function" "version" {
  function_name    = "apigw-redeploy-version"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/version.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/version.zip")
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
  resource_id              = aws_api_gateway_resource.hello.id
  http_method              = aws_api_gateway_method.hello_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.hello.invoke_arn
}

resource "aws_lambda_permission" "hello" {
  statement_id  = "AllowAPIGatewayInvokeHello"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hello.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/hello"
}

resource "aws_api_gateway_resource" "version" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "version"
}

resource "aws_api_gateway_method" "version_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.version.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "version_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id              = aws_api_gateway_resource.version.id
  http_method              = aws_api_gateway_method.version_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.version.invoke_arn
}

resource "aws_lambda_permission" "version" {
  statement_id  = "AllowAPIGatewayInvokeVersion"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.version.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/version"
}

# BUG: no `triggers` block. `depends_on` is correct/complete on purpose --
# see this file's own header for why that alone does not save it.
resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.hello_get,
    aws_api_gateway_integration.version_get,
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

output "deployment_id" {
  value = aws_api_gateway_deployment.this.id
}
TF
}

write_rev2() {
  cat > main.tf <<'TF'
resource "aws_iam_role" "lambda_exec" {
  name = "apigw-redeploy-lambda-exec"
  # Amendment 16's flagged gap -- see solution/solve.sh's identical comment.
  path = "/cdktn-bench-task/"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "hello" {
  function_name    = "apigw-redeploy-hello"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/hello.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/hello.zip")
}

resource "aws_lambda_function" "version" {
  function_name    = "apigw-redeploy-version"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = "${path.module}/lambda/version.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda/version.zip")
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
  resource_id              = aws_api_gateway_resource.hello.id
  http_method              = aws_api_gateway_method.hello_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.hello.invoke_arn
}

resource "aws_lambda_permission" "hello" {
  statement_id  = "AllowAPIGatewayInvokeHello"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.hello.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/hello"
}

resource "aws_api_gateway_resource" "version" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "version"
}

resource "aws_api_gateway_method" "version_get" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.version.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "version_get" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id              = aws_api_gateway_resource.version.id
  http_method              = aws_api_gateway_method.version_get.http_method
  integration_http_method  = "POST"
  type                     = "AWS_PROXY"
  uri                      = aws_lambda_function.version.invoke_arn
}

resource "aws_lambda_permission" "version" {
  statement_id  = "AllowAPIGatewayInvokeVersion"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.version.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/GET/version"
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
    "application/json" = "{\"statusCode\": 200}"
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

# BUG (still): no `triggers` block. `depends_on` grows to include /status's
# integration -- still CORRECT, still does not save this from staleness.
resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.hello_get,
    aws_api_gateway_integration.version_get,
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

output "deployment_id" {
  value = aws_api_gateway_deployment.this.id
}
TF
}

assert_facts() {
  local plan="$1" expected_methods="$2"
  local methods
  methods="$(jq '[.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_method")] | length' "$plan")"
  [ "$methods" = "$expected_methods" ] || { echo "UNEXPECTED (this fixture should still pass tier-0): expected $expected_methods methods, got $methods in $plan" >&2; exit 1; }
  jq -e '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_rest_api")' "$plan" >/dev/null || { echo "UNEXPECTED: no rest_api in $plan" >&2; exit 1; }
  jq -e '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment")' "$plan" >/dev/null || { echo "UNEXPECTED: no deployment in $plan" >&2; exit 1; }
  echo "  OK (passes tier-0 like the correct solution): $expected_methods methods, rest_api + deployment present in $plan"
}

if [ "$LIVE" != "1" ]; then
  echo "== OFFLINE static-proof mode: confirm this negative PASSES every static tier, and has NO triggers signal to diff =="
  write_lambda_zips

  write_rev1
  terraform init -input=false >/dev/null
  terraform validate >/dev/null
  terraform plan -input=false -out=plan.tfplan >/dev/null
  terraform show -json plan.tfplan > plan.rev1.json
  assert_facts plan.rev1.json 2

  write_rev2
  terraform validate >/dev/null
  terraform plan -input=false -out=plan.tfplan >/dev/null
  terraform show -json plan.tfplan > plan.rev2.json
  assert_facts plan.rev2.json 3

  T1="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers' plan.rev1.json)"
  T2="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers' plan.rev2.json)"
  echo "  revision 1 triggers: $T1"
  echo "  revision 2 triggers: $T2"
  if [ "$T1" != "null" ] || [ "$T2" != "null" ]; then
    echo "UNEXPECTED: this fixture was supposed to have NO triggers block at all" >&2
    exit 1
  fi
  echo "  CONFIRMED: no triggers signal in either revision."

  # Let the ORACLE decide, the same convention every other scenario's
  # broken/*/solve.sh follows (e.g. apigw-openapi's own negatives) --
  # gates/oracle_falsifiability.py::_run_solve judges this run by
  # /logs/verifier/reward.txt itself (expects 0.0 here), not by this
  # script's own exit code. UNLIKE its triggers-incomplete-hash sibling,
  # this catch IS single-artifact statically catchable:
  # specs/apigw-redeploy.yaml's deployment-triggers-present tier-0 assert
  # checks the FINAL (revision-2) state's `triggers.redeployment`
  # existence directly, no live apply or two-plan diff needed to catch
  # THIS one (the diagnostic two-plan confirmation above is extra evidence
  # for a human reader, not what actually grades this fixture).
  #
  # Finding G4 fix (benchmark-integrity review, 2026-08-07): this used to
  # also read back /logs/verifier/reward.txt itself and assert on it here
  # -- dead code in the exact harness that validates this fixture
  # (gates/oracle_falsifiability.py::_run_solve patches the COPIED
  # tests/static_tiers.sh to write reward.txt into ITS OWN sandbox
  # `logs/verifier` dir, never to this hardcoded absolute path, so the
  # `cat` here always fell through to '?' and made this branch fail with
  # EXIT=1 in that exact harness -- reproduced directly). Dropped in favor
  # of just running static_tiers.sh and letting the gate itself judge
  # reward.txt, matching every other scenario's broken/*/solve.sh
  # convention.
  bash tests/static_tiers.sh
  exit 0
fi

echo "== LIVE mode: demonstrate the trap -- expect /status to stay non-200 across a full poll window after the second apply, despite apply exiting 0 =="
write_lambda_zips

# Cleanup on ANY exit path -- same finding-7 fix as solution/solve.sh.
cleanup() {
  echo "== cleanup: terraform destroy + residual log groups (finding 7) =="
  terraform destroy -input=false -auto-approve || true
  aws logs delete-log-group --log-group-name /aws/lambda/apigw-redeploy-hello >/dev/null 2>&1 || true
  aws logs delete-log-group --log-group-name /aws/lambda/apigw-redeploy-version >/dev/null 2>&1 || true
  aws logs delete-log-group --log-group-name /aws/apigateway/welcome >/dev/null 2>&1 || true
}
trap cleanup EXIT

write_rev1
terraform init -input=false
terraform apply -input=false -auto-approve
API_URL="$(terraform output -raw api_url)"
DEPLOYMENT_ID_BEFORE="$(terraform output -raw deployment_id)"
echo "revision 1 API URL: $API_URL (deployment id: $DEPLOYMENT_ID_BEFORE)"

check_200() {
  local path="$1"
  local code
  code="$(curl -s -o /tmp/resp.body -w '%{http_code}' "${API_URL}${path}")"
  echo "  GET ${path} -> $code $(cat /tmp/resp.body)"
  [ "$code" = "200" ] || { echo "UNEXPECTED: ${path} did not return 200 on the FIRST deploy" >&2; exit 1; }
}
check_200 "hello"
check_200 "version"

write_rev2
terraform apply -input=false -auto-approve
echo "  terraform apply (revision 2) exited 0 -- watch for '0 to change' on aws_api_gateway_deployment.this above"
API_URL="$(terraform output -raw api_url)"
DEPLOYMENT_ID_AFTER="$(terraform output -raw deployment_id)"
echo "revision 2: deployment id: $DEPLOYMENT_ID_AFTER"

# Finding G6 fix (benchmark-integrity review, 2026-08-07): the identical
# bare, un-polled check_200 "hello"/"version" pair used to also run here,
# immediately after the second apply -- the riskiest sample point for a
# spurious failure (same propagation window solution/solve.sh's own
# finding-6 comment documents). Dropped: this fixture's own trap check
# below (live_check.py --expect stale) does not depend on /hello or
# /version at all (see check_stale()'s own docstring -- it only asserts
# deployment_id_unchanged + /status), so nothing here was ever load-
# bearing for this fixture's negative outcome.

# Finding 2 fix (2026-08-06): the SAME shared checker solution/solve.sh
# calls with --expect ok, called here with --expect stale -- positively
# discriminating (deployment id unchanged AND /status stays non-200-with-
# the-modified-body across the FULL 180s poll window, never a single t=0
# sample that would also fire on a CORRECT solution still mid-propagation
# -- see tests/live_check.py's own header for the full rationale).
if python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect stale \
    --deployment-id-before "$DEPLOYMENT_ID_BEFORE" --deployment-id-after "$DEPLOYMENT_ID_AFTER"; then
  echo "CONFIRMED LIVE: GET /status stayed stale (deployment id unchanged: $DEPLOYMENT_ID_BEFORE) while 'terraform apply' exited 0."
else
  echo "TRAP DID NOT FIRE -- this fixture failed to demonstrate the stale-deployment catch" >&2
  exit 1
fi
