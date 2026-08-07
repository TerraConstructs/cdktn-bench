#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), Slice G
# (apigw-redeploy). Same iteration as the awscdk/terraconstructs reference
# solutions' own header comments describe (read either first) -- one REST
# API, GET /hello + GET /version at revision 1, GET /status (MOCK, fixed
# JSON body) added at revision 2, same stage serves both.
#
# UNLIKE the two L2 arms, hand-written Terraform HCL has no automatic
# redeploy machinery -- this is the whole point of the scenario
# (docs/apigw-redeploy-mechanics.md §5, "What a raw-HCL operator must
# hand-write to match this"). The aws_api_gateway_deployment resource
# below hand-implements it correctly:
#   - `triggers.redeployment` = sha1(jsonencode([...])) over the COMPLETE
#     set of plan-time-STATIC fields for every route (path_part/http_method/
#     authorization/integration type/integration_http_method/templates) --
#     deliberately NEVER a resource's own `.id`/`.arn` (those are
#     provider-computed and plan-time-unknown for a brand-new resource in
#     the same plan -- §5's "plan-time-unknown values" pitfall). This is
#     what lets the hash resolve to a concrete hex string in
#     `terraform show -json` PLAN output with zero prior state, so this
#     file's offline falsifiability check (below) can diff two independent
#     `terraform plan` runs directly, no apply needed.
#   - `depends_on` lists every method's integration (+ the /status
#     integration_response), covering the classic
#     deployment-missing-integration-dependency footgun too.
#   - `lifecycle { create_before_destroy = true }` avoids a stage-serving
#     gap on replacement.
# Verified directly (2026-08-06) against this exact file, twice-planned:
#   revision 1 triggers.redeployment = 0afc8ac589182f2e874b63d4221074863f34e9d2
#   revision 2 triggers.redeployment = 885365e13ea6e4274af5b066e97a8369778d7065  (DIFFERENT)
# See solution/broken/{stale-deployment-no-triggers,triggers-incomplete-hash}/
# for the two negatives this correct shape is contrasted against -- both
# PASS every static tier identically to this file; only a live apply tells
# them apart (see each fixture's own solve.sh header).
#
# --- OFFLINE vs. LIVE switch -- see the awscdk reference solution's own
# header for the full rationale; identical here (`terraform plan`/`apply`
# in place of `cdk synth`/`cdk deploy`). LIVE=1 exports
# TF_VAR_cdktn_bench_live=1 (finding G2 fix, 2026-08-07) so the SEEDED,
# non-agent-owned ./provider.tf switches itself from its offline dummy-
# credential fixture to real ambient AWS credentials -- this script never
# writes or edits provider.tf, exactly what a real agent solving this
# scenario is bound to as well (see this scenario's instruction.md).
#
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule, SCHEMA.md §8.2 point 8).
set -euo pipefail

LIVE="${LIVE:-0}"
PROJECT_DIR="$(pwd)"
mkdir -p lambda lambda-src

write_lambda_zips() {
  # hcl_raw has no Code.fromInline() equivalent -- aws_lambda_function
  # always needs a real archive. Built here (not seeded) so this solve.sh
  # is self-contained for BOTH offline plan (any bytes suffice for
  # filebase64sha256) and LIVE apply (needs a REAL, working zip).
  cat > lambda-src/hello.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: "hello" });
JS
  cat > lambda-src/version.js <<'JS'
exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: "1.0.0" }) });
JS
  ( cd lambda-src && cp hello.js index.js && zip -q -X ../lambda/hello.zip index.js && rm index.js )
  ( cd lambda-src && cp version.js index.js && zip -q -X ../lambda/version.zip index.js && rm index.js )
}

# Finding G2 fix (benchmark-integrity review, 2026-08-07): this used to
# hand-roll its OWN provider.tf (write_provider_offline() for the OFFLINE
# path, write_provider_live() for LIVE -- the latter unconditionally
# overwriting the non-agent-owned provider.tf, exactly the thing an agent
# is told not to do). Neither is needed anymore: the SEEDED
# ./provider.tf (arms/hcl-raw/environment/workspace/provider.tf, already
# present in this workspace) is now live-aware on its own via
# `var.cdktn_bench_live` -- see that file's own header comment. The
# OFFLINE path below needs no setup (its default IS the dummy-credential
# fixture); the LIVE path just exports TF_VAR_cdktn_bench_live=1 before
# calling terraform, exactly what a real agent is told to do in this
# scenario's instruction.md, and never touches provider.tf.

write_rev1() {
  cat > main.tf <<'TF'
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

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.hello.path_part,
      aws_api_gateway_method.hello_get.http_method,
      aws_api_gateway_method.hello_get.authorization,
      aws_api_gateway_integration.hello_get.type,
      aws_api_gateway_integration.hello_get.integration_http_method,
      aws_api_gateway_resource.version.path_part,
      aws_api_gateway_method.version_get.http_method,
      aws_api_gateway_method.version_get.authorization,
      aws_api_gateway_integration.version_get.type,
      aws_api_gateway_integration.version_get.integration_http_method,
    ]))
  }

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
TF
}

write_rev2() {
  cat > main.tf <<'TF'
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

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.hello.path_part,
      aws_api_gateway_method.hello_get.http_method,
      aws_api_gateway_method.hello_get.authorization,
      aws_api_gateway_integration.hello_get.type,
      aws_api_gateway_integration.hello_get.integration_http_method,
      aws_api_gateway_resource.version.path_part,
      aws_api_gateway_method.version_get.http_method,
      aws_api_gateway_method.version_get.authorization,
      aws_api_gateway_integration.version_get.type,
      aws_api_gateway_integration.version_get.integration_http_method,
      aws_api_gateway_resource.status.path_part,
      aws_api_gateway_method.status_get.http_method,
      aws_api_gateway_method.status_get.authorization,
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
TF
}

assert_facts() {
  local plan="$1" expected_methods="$2"
  local methods
  methods="$(jq '[.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_method")] | length' "$plan")"
  [ "$methods" = "$expected_methods" ] || { echo "FALSIFIED: expected $expected_methods methods, got $methods in $plan" >&2; exit 1; }
  jq -e '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_rest_api")' "$plan" >/dev/null || { echo "FALSIFIED: no rest_api in $plan" >&2; exit 1; }
  jq -e '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment")' "$plan" >/dev/null || { echo "FALSIFIED: no deployment in $plan" >&2; exit 1; }
  echo "  OK: $expected_methods methods, rest_api + deployment present in $plan"
}

assert_hash_changed() {
  local plan1="$1" plan2="$2"
  local h1 h2
  h1="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers.redeployment' "$plan1")"
  h2="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers.redeployment' "$plan2")"
  echo "  revision 1 triggers.redeployment: $h1"
  echo "  revision 2 triggers.redeployment: $h2"
  [ -n "$h1" ] && [ "$h1" != "null" ] || { echo "FALSIFIED: revision 1 has no resolved triggers.redeployment hash" >&2; exit 1; }
  [ "$h1" != "$h2" ] || { echo "FALSIFIED: triggers.redeployment did NOT change between revisions -- no new deployment would be created" >&2; exit 1; }
  echo "  OK: hash changed -- terraform will replace the deployment on redeploy"
}

if [ "$LIVE" != "1" ]; then
  echo "== OFFLINE static-proof mode (LIVE unset/0): plan twice (no apply, no state), diff triggers.redeployment =="
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
  jq -e '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_integration") | select(.values.type=="MOCK")' plan.rev2.json >/dev/null \
    || { echo "FALSIFIED: no MOCK integration in revision 2" >&2; exit 1; }

  assert_hash_changed plan.rev1.json plan.rev2.json

  if [ -f tests/static_tiers.sh ]; then
    echo "== tests/static_tiers.sh found -- running it too =="
    bash tests/static_tiers.sh
  else
    echo "== NOTE: tests/static_tiers.sh not present yet (generator/spec work pending) -- offline proof above is the full check for now =="
  fi
  exit 0
fi

echo "== LIVE mode: real deploy -> curl -> modify -> re-deploy -> curl =="
echo "Account/region guardrail: this must be running with creds scoped to 886312446417 / us-east-1 only."

# Cleanup runs on ANY exit path (pass, live_check failure, or a mid-script
# error) -- CONTEXT's own rule: always delete live resources created,
# leave the account as found. Finding 7 fix (2026-08-06): `terraform
# destroy` alone does NOT remove the CloudWatch Logs log groups Lambda/API
# Gateway auto-create on first invocation (/aws/lambda/apigw-redeploy-hello,
# /aws/lambda/apigw-redeploy-version, /aws/apigateway/welcome) -- confirmed
# residual after every prior LIVE proof run in this review. Deleted
# explicitly here; `|| true` throughout since a log group may not exist
# yet (e.g. a failure before either function was ever invoked).
cleanup() {
  echo "== cleanup: terraform destroy + residual log groups (finding 7) =="
  terraform destroy -input=false -auto-approve || true
  aws logs delete-log-group --log-group-name /aws/lambda/apigw-redeploy-hello >/dev/null 2>&1 || true
  aws logs delete-log-group --log-group-name /aws/lambda/apigw-redeploy-version >/dev/null 2>&1 || true
  aws logs delete-log-group --log-group-name /aws/apigateway/welcome >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Finding G2 fix: real credentials, no provider.tf edit -- see this
# script's write_rev1() docstring-comment above for the full rationale.
export TF_VAR_cdktn_bench_live=1

write_lambda_zips

write_rev1
terraform init -input=false
terraform apply -input=false -auto-approve
API_URL="$(terraform output -raw api_url)"
echo "revision 1 API URL: $API_URL"

# Finding 1 fix: bounded POLL (tests/live_check.py), not a single
# immediate curl -- API Gateway stage-propagation latency after a fresh
# deploy needs real margin (measured up to 60s on other arms; hcl-raw
# itself measured 30s). check_200 below stays a quick, cheap regression
# check for /hello and /version right after the FIRST deploy only
# (proxy integrations, unaffected by the MOCK-route propagation lag a
# control test isolated -- so an immediate sample here is sound). Finding
# 6 fix (2026-08-07): the identical pair used to also run immediately
# after the SECOND deploy, on the same un-polled single curl -- exactly
# the riskiest sample point (see docs/apigw-redeploy-mechanics.md's own
# propagation-window note) -- dropped; live_check.py's check_ok() below
# already polls /hello and /version (REGRESSION_POLL_TIMEOUT_S) as part
# of its own --expect ok contract, so that regression coverage still
# exists, just bounded instead of a single sample.
check_200() {
  local path="$1"
  local code
  code="$(curl -s -o /tmp/resp.body -w '%{http_code}' "${API_URL}${path}")"
  echo "  GET ${path} -> $code $(cat /tmp/resp.body)"
  [ "$code" = "200" ] || { echo "LIVE CHECK FAILED: ${path} did not return 200" >&2; exit 1; }
}

check_200 "hello"
check_200 "version"

write_rev2
terraform apply -input=false -auto-approve
API_URL="$(terraform output -raw api_url)"
echo "revision 2 API URL (should be identical -- same stage): $API_URL"

# Finding 5 fix: the SAME shared checker (tests/live_check.py) the
# broken/*/solve.sh fixtures below call with --expect stale, called here
# with --expect ok -- one implementation, not two ad hoc ones. Finding 1's
# fix lives inside it (POLL_TIMEOUT_S=180, bounded retry, never a single
# immediate curl). Finding 3's fix is also there: only behavioral facts
# are asserted (exact /status body + /hello + /version regression-free),
# no deployment-count/stage-pointer assertion. Finding 6 fix: this is now
# the ONLY /hello and /version check after the second deploy (see
# check_200's own comment above for why the bare immediate pair was
# dropped here).
python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect ok
