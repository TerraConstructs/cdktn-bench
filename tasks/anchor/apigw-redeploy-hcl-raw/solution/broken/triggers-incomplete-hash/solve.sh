#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), Slice G (apigw-redeploy). hcl_raw only. The SUBTLE, realistic
# sibling of ../stale-deployment-no-triggers/ (read that fixture's own
# header first -- same overall shape, different bug).
#
# Revision 1 is byte-identical to solution/solve.sh's own revision 1 (at
# revision 1 there is nothing incomplete yet -- the bug only manifests once
# /status is added). Revision 2 adds GET /status (MOCK integration) exactly
# like the correct solution, and `depends_on` is updated CORRECTLY to
# include the new integration -- but the `triggers.redeployment` hash's
# INPUT LIST is left FROZEN at exactly what it was in revision 1
# (hello/version fields only). This is "the operator forgot to extend the
# hash when adding a route" -- the single most realistic version of this
# footgun, because the block still exists, still looks legitimate, and
# still resolves to a real hex value; a reviewer skimming the diff sees a
# `triggers = { redeployment = sha1(...) }` block was already there and
# assumes it's covered.
#
# THE POINT: every existing static tier passes IDENTICALLY to the correct
# solution -- `triggers` exists (unlike ../stale-deployment-no-triggers/),
# `depends_on` is complete, route count is 3, MOCK integration is wired.
# The ONLY way to see this is broken statically is the differential check
# this scenario's tier-1 (or a live_check) must add: diff
# `triggers.redeployment` between the revision-1 and revision-2 plans. For
# the correct solution it changes (solution/solve.sh's own header cites the
# two hex values). For THIS fixture it does NOT -- verified below, both
# revisions resolve to the exact same hash -- because none of the hashed
# literals (hello's/version's own path_part/http_method/authorization/type/
# integration_http_method) changed when /status was added; /status simply
# never appears in the hash's input list at all. On a REAL second
# `terraform apply`, Terraform computes the SAME `triggers.redeployment`
# value both times -> "0 to change" for aws_api_gateway_deployment.this ->
# GET /status 404s live despite `terraform apply` exiting 0 -- same
# live-only failure mode as ../stale-deployment-no-triggers/, reached by a
# more subtle route.
#
# Same OFFLINE/LIVE switch as solution/solve.sh. LIVE mode here, like the
# sibling fixture, is expected to demonstrate the FAILURE and exits
# non-zero if the trap does NOT fire.
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

# Finding G2 fix (benchmark-integrity review, 2026-08-07): no longer
# hand-rolls its own provider.tf -- see solution/solve.sh's identical
# comment. The SEEDED ./provider.tf is live-aware via
# `var.cdktn_bench_live` on its own now.

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

output "deployment_id" {
  value = aws_api_gateway_deployment.this.id
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

# BUG: `triggers` block is FROZEN at revision 1's input list -- /hello and
# /version fields only. It was never extended to cover /status. `depends_on`
# IS updated correctly (still isolates this fixture to ONLY the hash-
# completeness catch).
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
  echo "== OFFLINE static-proof mode: confirm this negative PASSES every static tier, and its triggers hash is UNCHANGED across revisions (the bug) =="
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
    || { echo "UNEXPECTED: no MOCK integration in revision 2" >&2; exit 1; }

  H1="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers.redeployment' plan.rev1.json)"
  H2="$(jq -r '.planned_values.root_module.resources[] | select(.type=="aws_api_gateway_deployment") | .values.triggers.redeployment' plan.rev2.json)"
  echo "  revision 1 triggers.redeployment: $H1"
  echo "  revision 2 triggers.redeployment: $H2"
  if [ "$H1" != "$H2" ]; then
    echo "UNEXPECTED: this fixture's hash was supposed to stay frozen (unchanged) across revisions" >&2
    exit 1
  fi
  # Finding 4/5 fix (2026-08-06): this catch's predicted_tier_caught is
  # "live" (specs/apigw-redeploy.yaml) -- invisible to every static tier
  # by construction (the whole point of this fixture: `triggers` exists,
  # `depends_on` is complete, route count/MOCK-integration facts all match
  # a correct solution -- only a cross-revision hash diff, which no
  # single-artifact static tier can express, tells them apart). Print the
  # shared marker gates/oracle_falsifiability.py's "live" branch greps
  # for, MECHANICALLY earned by the two-plan diff just above (not merely
  # asserted in a comment) -- this is what proves the offline gate that
  # this catch is real without ever touching AWS.
  echo "CDKTN_BENCH_LIVE_ONLY_CONFIRMED: hash UNCHANGED across revisions despite the route set changing -- the subtle catch this fixture demonstrates (docs/apigw-redeploy-mechanics.md §5's 'missing resources in the hash/depends_on list' pitfall, applied to the hash side)."

  # Finding 5 fix: STILL end with the oracle, like every other fixture
  # (gates/oracle_falsifiability.py's "live" branch requires reward==1.0
  # here -- this catch is EXPECTED to pass every static tier identically
  # to a correct solution, that invisibility IS the catch).
  #
  # Finding G4 fix (benchmark-integrity review, 2026-08-07): this used to
  # also read back /logs/verifier/reward.txt itself and assert on it here
  # -- dead code in the exact harness that validates this fixture (see
  # the sibling stale-deployment-no-triggers fixture's identical finding-
  # G4 comment for the full mechanism). Dropped in favor of just running
  # static_tiers.sh and letting the gate itself judge reward.txt, matching
  # every other scenario's broken/*/solve.sh convention.
  bash tests/static_tiers.sh
  exit 0
fi

echo "== LIVE mode: demonstrate the trap -- expect /status to stay non-200 across a full poll window after the second apply, despite apply exiting 0 =="
# Finding G2 fix: real credentials, no provider.tf edit -- see
# solution/solve.sh's identical comment.
export TF_VAR_cdktn_bench_live=1
write_lambda_zips

# Cleanup on ANY exit path -- same finding-7 fix as the sibling fixture.
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
# immediately after the second apply -- see the sibling fixture's
# identical finding-G6 comment. Dropped: check_stale() below does not
# depend on /hello or /version.

# Finding 2 fix: same shared, positively-discriminating checker as the
# sibling fixture (deployment id unchanged AND /status stays non-200 for
# the full poll window, never a single t=0 sample).
if python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect stale \
    --deployment-id-before "$DEPLOYMENT_ID_BEFORE" --deployment-id-after "$DEPLOYMENT_ID_AFTER"; then
  echo "CONFIRMED LIVE: GET /status stayed stale (deployment id unchanged: $DEPLOYMENT_ID_BEFORE) while 'terraform apply' exited 0."
else
  echo "TRAP DID NOT FIRE -- this fixture failed to demonstrate the incomplete-hash catch" >&2
  exit 1
fi
