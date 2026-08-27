#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), Slice G
# (apigw-redeploy). Same iteration as the awscdk reference solution's own
# header comment describes (read it first) -- one REST API, GET /hello +
# GET /version at revision 1, GET /status (MOCK, fixed JSON body) added at
# revision 2, same stage serves both.
#
# terraconstructs' compute.RestApi/addResource/addMethod/LambdaIntegration/
# MockIntegration needs NO manual triggers/dependency work either --
# `Deployment.calculateTriggers()` (deployment.ts:145-166) hashes the
# entire synthesized aws_api_gateway_rest_api config plus every Method/
# Resource/Model's own `addToTriggers()` fragment, paired with automatic
# `node.addDependency()` calls -- the identical mechanism aws-cdk-lib uses,
# ported line-for-line (docs/apigw-redeploy-mechanics.md §1/§2). Verified
# directly (2026-08-06) against this exact file, twice-synthed +
# `terraform plan`-ed (no state, no apply -- see this file's own falsifiability
# check below for why that's sufficient):
#   revision 1 triggers.redeployment = "59008bcf13ba14e70dc16f411c33ac4c"
#     depends_on: 6 entries (2 resources + 2 methods + 2 integrations)
#   revision 2 triggers.redeployment = "970617cd40e1e877eaba5b4b4f1873d8"  (DIFFERENT)
#     depends_on: 10 entries (adds the /status resource/method/integration/
#     integration_response)
# Unlike hcl_raw's own hand-written hash (see that arm's solve.sh), this
# hash is computed in Node at synth time and embedded as a literal
# `constant_value` in the synthesized `cdk.tf.json` -- resolves to a
# concrete hex string in `terraform show -json` PLAN output with zero
# prior state, which is what lets this file's offline check below diff two
# independent plans directly.
#
# --- OFFLINE vs. LIVE switch -- see tasks/anchor/apigw-redeploy-awscdk/
# solution/solve.sh's own header for the full rationale; identical here,
# substituting `cdktn synth` + `terraform plan`/`apply` for `cdk synth`/
# `cdk deploy`. LIVE=1 runs a real deploy against ambient AWS credentials.
#
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule, SCHEMA.md §8.2 point 8).
set -euo pipefail

LIVE="${LIVE:-0}"
PROJECT_DIR="$(pwd)"

# STEP -- the MULTI-STEP form (DECISIONS.md Amendment 27,
# docs/prompt-decomposition-audit.md). Unset/empty (the default) runs the
# WHOLE scenario: this file is the reference solution for the FINAL step
# (steps/02-change-request), whose oracle is the full tier suite, and it is
# the shape every solution/broken/<catch>/ fixture is written against.
#
# STEP=01 stops after revision 1, then runs whatever tests/static_tiers.sh is
# staged -- which under gates/oracle_falsifiability.py's step branch is step
# 01's own (subset) oracle. steps/01-initial-deploy/solution/solve.sh is a
# thin wrapper that sets this, so revision 1 has exactly ONE definition on
# this arm; a duplicated heredoc in the step solution would drift from this
# one the first time either is touched.
STEP="${STEP:-}"
mkdir -p lib

write_rev1() {
  cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { TerraformOutput } from "cdktn";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { compute, iam } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const api = new compute.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deployOptions: { stageName: "prod" },
    });

    // Explicit, path-scoped execution role (Amendment 16's flagged gap):
    // QADeployApplicationRole's IamRoleLifecycleScoped/IamPassRoleScoped
    // statements only permit iam:CreateRole/PassRole under
    // arn:aws:iam::<account>:role/cdktn-bench-task/* -- letting
    // LambdaFunction's default L2 behavior auto-create an unnamed role at
    // IAM's default path (`/`) would AccessDeny under that role. Shared by
    // both functions, matching the other arms' single `lambda_exec` role.
    // `iam.Role` supports `path` here identically to aws-cdk-lib (verified
    // against terraconstructs@0.2.13's own role.d.ts). NOTE:
    // `ManagedPolicy.fromAwsManagedPolicyName` takes (scope, id, name) here,
    // NOT aws-cdk-lib's single-arg (name) shape -- verified against
    // terraconstructs@0.2.13's own managed-policy.d.ts.
    const execRole = new iam.Role(this, "LambdaExecRole", {
      path: "/cdktn-bench-task/",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          this,
          "LambdaBasicExecutionPolicy",
          "service-role/AWSLambdaBasicExecutionRole",
        ),
      ],
    });

    const helloFn = new compute.LambdaFunction(this, "HelloFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new compute.LambdaFunction(this, "VersionFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new compute.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new compute.LambdaIntegration(versionFn));

    new TerraformOutput(this, "ApiUrl", { value: api.url });
  }
}
TS
}

write_rev2() {
  cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { TerraformOutput } from "cdktn";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { compute, iam } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const api = new compute.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deployOptions: { stageName: "prod" },
    });

    // Explicit, path-scoped execution role (Amendment 16's flagged gap):
    // QADeployApplicationRole's IamRoleLifecycleScoped/IamPassRoleScoped
    // statements only permit iam:CreateRole/PassRole under
    // arn:aws:iam::<account>:role/cdktn-bench-task/* -- letting
    // LambdaFunction's default L2 behavior auto-create an unnamed role at
    // IAM's default path (`/`) would AccessDeny under that role. Shared by
    // both functions, matching the other arms' single `lambda_exec` role.
    // `iam.Role` supports `path` here identically to aws-cdk-lib (verified
    // against terraconstructs@0.2.13's own role.d.ts). NOTE:
    // `ManagedPolicy.fromAwsManagedPolicyName` takes (scope, id, name) here,
    // NOT aws-cdk-lib's single-arg (name) shape -- verified against
    // terraconstructs@0.2.13's own managed-policy.d.ts.
    const execRole = new iam.Role(this, "LambdaExecRole", {
      path: "/cdktn-bench-task/",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          this,
          "LambdaBasicExecutionPolicy",
          "service-role/AWSLambdaBasicExecutionRole",
        ),
      ],
    });

    const helloFn = new compute.LambdaFunction(this, "HelloFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new compute.LambdaFunction(this, "VersionFn", {
      runtime: compute.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new compute.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new compute.LambdaIntegration(versionFn));

    // day-2 API-CONFIG modification -- see the awscdk reference solution's
    // identical comment for why this (not a code edit) is the right shape.
    const status = api.root.addResource("status");
    status.addMethod(
      "GET",
      new compute.MockIntegration({
        requestTemplates: { "application/json": '{"statusCode": 200}' },
        passthroughBehavior: compute.PassthroughBehavior.NEVER,
        integrationResponses: [
          {
            statusCode: "200",
            responseTemplates: {
              "application/json": JSON.stringify({ status: "ok", routes: 3 }),
            },
          },
        ],
      }),
      { methodResponses: [{ statusCode: "200" }] },
    );

    new TerraformOutput(this, "ApiUrl", { value: api.url });
  }
}
TS
}

# Finding G2 fix (benchmark-integrity review, 2026-08-07): this used to
# hand-roll its own LIVE main.ts (write_main_ts_live(), unconditionally
# overwriting the non-agent-owned main.ts -- exactly the thing an agent is
# told not to do). Not needed anymore: the SEEDED ./main.ts
# (gen.py::terraconstructs_main_ts, already present in this workspace)
# carries a bare `providerConfig` that resolves ambient AWS credentials --
# this script never touches it, exactly what a real agent is told to do in
# this scenario's instruction.md.

synth_and_plan() {
  local outdir="$1"
  npx cdktn synth
  local stackdir="cdktf.out/stacks/hello-version-api"
  ( cd "$stackdir" && terraform init -input=false >/dev/null && terraform plan -input=false -out=plan.tfplan >/dev/null && terraform show -json plan.tfplan > "$PROJECT_DIR/$outdir.json" )
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
  echo "== OFFLINE static-proof mode (LIVE unset/0): synth+plan twice, diff triggers.redeployment =="
  write_rev1
  synth_and_plan plan.rev1
  assert_facts plan.rev1.json 2

  if [ "$STEP" = "01" ]; then
    echo "== STEP=01: stopping after revision 1 (steps/01-initial-deploy reference solution) =="
    if [ -f tests/static_tiers.sh ]; then
      echo "== tests/static_tiers.sh found -- running it against revision 1 =="
      bash tests/static_tiers.sh
    else
      echo "== NOTE: tests/static_tiers.sh not present -- the offline proof above is the full check =="
    fi
    exit 0
  fi

  write_rev2
  synth_and_plan plan.rev2
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

# Cleanup on ANY exit path (finding 7, 2026-08-06) -- same residual-log-
# group story as the awscdk/hcl_raw reference solutions' identical
# comments: `terraform destroy` does not remove what Lambda/API Gateway
# auto-create on first invocation.
#
# Finding G7 fix (benchmark-integrity review, 2026-08-07): the log-group
# sweep prefix used to be copy-pasted from awscdk's own cleanup()
# (`/aws/lambda/ScenarioStack-`) -- wrong on THIS arm, whose stack/grid id
# is the spec's `workspace_id` (see `new ScenarioStack(app,
# "hello-version-api", { gridUUID: "hello-version-api", ... })` in
# environment/app/main.ts), not "ScenarioStack". Every LambdaFunction's
# default physical name is
# `${gridUUID}-${uniqueResourceNamePrefix(...)}` (terraconstructs
# lib/aws/compute/function.js's own functionName default, confirmed
# directly against a local node_modules copy of terraconstructs 0.2.13),
# so its auto-created log group is `/aws/lambda/hello-version-api-...`,
# never matched by the old prefix -- confirmed as a real residue class, not
# a theoretical one.
#
# THE PREFIX FOLLOWS gridUUID, AND gridUUID IS NOW `workspace_id`
# (SCHEMA.md §0.1, 2026-08-20). It used to be the scenario `id`
# ("apigw-redeploy"), which is why the OLD `/aws/lambda/apigw-redeploy`
# prefix is still swept below alongside the new one: a real deploy made
# before that change leaves residue under the old name, and this sweep is
# the only thing that removes it. Both stale prefixes cost nothing when
# they match nothing.
cleanup() {
  echo "== cleanup: terraform destroy + residual log groups (finding 7) =="
  ( cd cdktf.out/stacks/hello-version-api && terraform destroy -input=false -auto-approve ) || true
  for prefix in /aws/lambda/hello-version-api /aws/lambda/apigw-redeploy /aws/lambda/ScenarioStack-; do
    aws logs describe-log-groups --log-group-name-prefix "$prefix" \
        --query 'logGroups[].logGroupName' --output text 2>/dev/null \
      | tr '\t' '\n' \
      | while read -r lg; do [ -n "$lg" ] && aws logs delete-log-group --log-group-name "$lg" >/dev/null 2>&1 || true; done
  done
  aws logs delete-log-group --log-group-name /aws/apigateway/welcome >/dev/null 2>&1 || true
}
trap cleanup EXIT

write_rev1
npx cdktn synth
( cd cdktf.out/stacks/hello-version-api && terraform init -input=false && terraform apply -input=false -auto-approve )
API_URL="$(cd cdktf.out/stacks/hello-version-api && terraform output -raw ApiUrl)"
echo "revision 1 API URL: $API_URL"

# Finding 1 fix: see the hcl_raw/awscdk reference solutions' identical
# comment -- the load-bearing poll (POLL_TIMEOUT_S=180) lives in
# tests/live_check.py; check_200 here stays a quick regression check
# right after the FIRST deploy only (finding G6 fix, 2026-08-07 -- see
# below).
check_200() {
  local path="$1"
  local code
  code="$(curl -s -o /tmp/resp.body -w '%{http_code}' "${API_URL}${path}")"
  echo "  GET ${path} -> $code $(cat /tmp/resp.body)"
  [ "$code" = "200" ] || { echo "LIVE CHECK FAILED: ${path} did not return 200" >&2; exit 1; }
}

check_200 "hello"
check_200 "version"

if [ "$STEP" = "01" ]; then
  echo "== STEP=01: revision 1 is deployed and serving; stopping before the change request =="
  # Step 01's own live_check.py (2-route contract) -- staged at tests/ by
  # whoever invoked this. The EXIT trap still tears the account down, which
  # is correct for this MANUAL proof shape: it proves "revision 1 deploys and
  # serves", it is not the trial (in a real trial the AGENT deploys and
  # nothing is destroyed until the post-trial reset).
  python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect ok
  exit 0
fi

write_rev2
npx cdktn synth
( cd cdktf.out/stacks/hello-version-api && terraform apply -input=false -auto-approve )
API_URL="$(cd cdktf.out/stacks/hello-version-api && terraform output -raw ApiUrl)"
echo "revision 2 API URL (should be identical -- same stage): $API_URL"

# Finding G6 fix (benchmark-integrity review, 2026-08-07): the identical
# bare, un-polled check_200 "hello"/"version" pair used to also run here,
# immediately after the second apply -- see the hcl_raw reference
# solution's identical finding-G6 comment for the full rationale.
# Dropped; live_check.py's check_ok() below already polls /hello and
# /version as part of its --expect ok contract.

# Finding 5 fix: same shared checker as the other two reference solutions.
python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect ok
