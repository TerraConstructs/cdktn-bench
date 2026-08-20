#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), Slice G
# (apigw-redeploy). Implements the day-2 redeploy-on-change iteration this
# scenario tests: (1) author + deploy a REST API with GET /hello, GET
# /version (both Lambda-proxy-backed), (2) [LIVE only] confirm it serves,
# (3) apply the prescribed API-CONFIG modification -- add GET /status, a
# MOCK integration returning a FIXED JSON body (deliberately NOT a Lambda-
# code change: see docs/apigw-redeploy-mechanics.md's "Benchmark-relevant
# consequence" note -- a pure code edit never moves any arm's redeploy-
# trigger hash, so it could never exercise this scenario's mechanism), (4)
# re-deploy, (5) [LIVE only] confirm the SAME stage now serves /status too,
# without having broken /hello or /version.
#
# Plain aws-cdk-lib L2 (RestApi/addResource/addMethod/LambdaIntegration/
# MockIntegration) needs NO manual triggers/dependency work -- CDK salts
# the synthesized Deployment's own CFN logical ID with an MD5 hash of the
# accumulated RestApi/Method/Resource/Model config (deployment.ts:197-215
# in aws-cdk-lib/aws-apigateway); a changed logical ID *is* a CFN replace.
# Verified directly (2026-08-06) against this exact file, twice-synthed:
#   revision 1 (`/hello /version` only):
#     RedeployApiDeployment217F5DB8<32-hex>  ends ..."691826aea5"
#   revision 2 (adds `/status`):
#     RedeployApiDeployment217F5DB8<32-hex>  ends ..."9702a"      (DIFFERENT)
#   DependsOn (revision 2): 6 entries -- the 3 Resource + 3 Method logical
#   ids for hello/version/status, all present with zero manual wiring.
#
# --- OFFLINE vs. LIVE switch --------------------------------------------
# Default (LIVE unset or not "1"): pure synth/plan, no AWS credentials or
# network needed. Writes revision 1, builds+synths into cdk.out.rev1/,
# asserts the tier-0-style structural facts; writes revision 2 (a full
# superset rewrite -- CDK apps are declared whole every run, there is no
# "patch" concept), builds+synths into cdk.out.rev2/, asserts route count
# 3, the MOCK integration exists, AND -- the actual falsifiability check
# this scenario exists for -- that the Deployment's salted logical ID
# CHANGED between the two synths (docs/apigw-redeploy-mechanics.md §6(b)).
# This is what `make falsifiability`-style offline proof runs.
#
# LIVE=1: performs the REAL two-deploy iteration against account
# 886312446417 (see this repo's CONTEXT / DECISIONS.md -- the only account
# this may ever touch, us-east-1 only). Requires CDKToolkit already
# bootstrapped (scenarios/anchor/deploy/deploy.sh does this once at env
# setup, not per trial) and real AWS credentials staged in the environment
# (aws-vault exec --no-session tcons-mgmt -- ... at the operator layer, or
# whatever QADeployApplicationRole-equivalent creds the trial container
# stages -- see docs/slice-g-recon.md §1's open QADeployApplicationRole
# item). Deploys revision 1, curls /hello and /version expecting 200,
# deploys revision 2, curls /status expecting the fixed JSON body AND
# re-curls /hello + /version to prove the redeploy didn't regress the
# existing routes. Exits non-zero on any live check failure. ALWAYS clean
# up (`npx cdk destroy --force`) after a LIVE run -- see this repo's
# CONTEXT: leave the account as found.
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
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const api = new apigateway.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deployOptions: { stageName: "prod" },
    });

    // Explicit, path-scoped execution role (Amendment 16's flagged gap):
    // QADeployApplicationRole's IamRoleLifecycleScoped/IamPassRoleScoped
    // statements only permit iam:CreateRole/PassRole under
    // arn:aws:iam::<account>:role/cdktn-bench-task/* -- letting Lambda's
    // default L2 behavior auto-create an unnamed role at IAM's default
    // path (`/`) would AccessDeny under that role. Shared by both
    // functions, matching the other arms' single `lambda_exec` role.
    const execRole = new iam.Role(this, "LambdaExecRole", {
      path: "/cdktn-bench-task/",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });

    const helloFn = new lambda.Function(this, "HelloFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new lambda.Function(this, "VersionFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new apigateway.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new apigateway.LambdaIntegration(versionFn));

    new cdk.CfnOutput(this, "ApiUrl", { value: api.url });
  }
}
TS
}

write_rev2() {
  cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const api = new apigateway.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deployOptions: { stageName: "prod" },
    });

    // Explicit, path-scoped execution role (Amendment 16's flagged gap):
    // QADeployApplicationRole's IamRoleLifecycleScoped/IamPassRoleScoped
    // statements only permit iam:CreateRole/PassRole under
    // arn:aws:iam::<account>:role/cdktn-bench-task/* -- letting Lambda's
    // default L2 behavior auto-create an unnamed role at IAM's default
    // path (`/`) would AccessDeny under that role. Shared by both
    // functions, matching the other arms' single `lambda_exec` role.
    const execRole = new iam.Role(this, "LambdaExecRole", {
      path: "/cdktn-bench-task/",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });

    const helloFn = new lambda.Function(this, "HelloFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new lambda.Function(this, "VersionFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new apigateway.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new apigateway.LambdaIntegration(versionFn));

    // day-2 API-CONFIG modification: add /status, a MOCK integration with
    // a fixed JSON body. No manual trigger/dependency work needed -- see
    // this file's own header comment.
    const status = api.root.addResource("status");
    status.addMethod(
      "GET",
      new apigateway.MockIntegration({
        requestTemplates: { "application/json": '{"statusCode": 200}' },
        passthroughBehavior: apigateway.PassthroughBehavior.NEVER,
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

    new cdk.CfnOutput(this, "ApiUrl", { value: api.url });
  }
}
TS
}

assert_deployment_id_changed() {
  local dir1="$1" dir2="$2"
  local id1 id2
  # Filter by resource TYPE, not by logical-id name pattern -- the Stage
  # resource's own logical id also happens to start with the same prefix
  # ("RedeployApiDeploymentStageprod...") and would otherwise be picked up
  # too (caught during this file's own offline dry run).
  id1="$(jq -r '.Resources | to_entries[] | select(.value.Type=="AWS::ApiGateway::Deployment") | .key' "$dir1/ScenarioStack.template.json")"
  id2="$(jq -r '.Resources | to_entries[] | select(.value.Type=="AWS::ApiGateway::Deployment") | .key' "$dir2/ScenarioStack.template.json")"
  echo "  revision 1 Deployment logical id: $id1"
  echo "  revision 2 Deployment logical id: $id2"
  if [ -z "$id1" ] || [ -z "$id2" ]; then
    echo "FALSIFIED: could not find a Deployment logical id in one of the synths" >&2
    exit 1
  fi
  if [ "$id1" = "$id2" ]; then
    echo "FALSIFIED: Deployment logical id did NOT change between revisions -- no new deployment would be created" >&2
    exit 1
  fi
  echo "  OK: logical id changed -- CDK will replace the Deployment on redeploy"
}

assert_facts() {
  local artifact="$1" expected_methods="$2"
  local methods
  methods="$(jq '[.Resources[] | select(.Type=="AWS::ApiGateway::Method")] | length' "$artifact")"
  [ "$methods" = "$expected_methods" ] || { echo "FALSIFIED: expected $expected_methods methods, got $methods in $artifact" >&2; exit 1; }
  jq -e '.Resources[] | select(.Type=="AWS::ApiGateway::RestApi")' "$artifact" >/dev/null || { echo "FALSIFIED: no RestApi in $artifact" >&2; exit 1; }
  jq -e '.Resources[] | select(.Type=="AWS::ApiGateway::Deployment")' "$artifact" >/dev/null || { echo "FALSIFIED: no Deployment in $artifact" >&2; exit 1; }
  echo "  OK: $expected_methods methods, RestApi + Deployment present in $artifact"
}

if [ "$LIVE" != "1" ]; then
  echo "== OFFLINE static-proof mode (LIVE unset/0): synth twice, diff the salted Deployment id =="

  write_rev1
  npm run build
  npx cdk synth --no-lookups --quiet -o cdk.out.rev1
  assert_facts "cdk.out.rev1/ScenarioStack.template.json" 2

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
  npm run build
  npx cdk synth --no-lookups --quiet -o cdk.out.rev2
  assert_facts "cdk.out.rev2/ScenarioStack.template.json" 3
  jq -e '[.Resources[] | select(.Type=="AWS::ApiGateway::Method")][] | select(.Properties.Integration.Type=="MOCK")' \
    cdk.out.rev2/ScenarioStack.template.json >/dev/null \
    || { echo "FALSIFIED: no MOCK integration in revision 2" >&2; exit 1; }

  assert_deployment_id_changed cdk.out.rev1 cdk.out.rev2

  # Best-effort forward compat: if the generator has since scaffolded a
  # real tests/static_tiers.sh for this scenario, also run it against the
  # final (revision 2) state -- mirrors every other scenario's solve.sh
  # convention (SCHEMA.md §8.2 point 8) once that file exists.
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

# Cleanup on ANY exit path (finding 7, 2026-08-06): `cdk destroy` does NOT
# remove the CloudWatch Logs log groups Lambda auto-creates on first
# invocation (/aws/lambda/ScenarioStack-HelloFn*, .../-VersionFn*) or the
# one API Gateway itself auto-creates (/aws/apigateway/welcome) --
# confirmed residual after every prior LIVE proof run in this review.
# `--query` + a loop rather than a fixed name: CDK's auto-generated
# function names carry an unpredictable hash suffix, unlike hcl_raw's
# fixed `function_name`. `|| true` throughout: nothing here may fail the
# cleanup pass just because a resource never got created before an
# earlier step failed.
cleanup() {
  echo "== cleanup: cdk destroy + residual log groups (finding 7) =="
  npx cdk destroy --force || true
  aws logs describe-log-groups --log-group-name-prefix /aws/lambda/ScenarioStack- \
      --query 'logGroups[].logGroupName' --output text 2>/dev/null \
    | tr '\t' '\n' \
    | while read -r lg; do [ -n "$lg" ] && aws logs delete-log-group --log-group-name "$lg" >/dev/null 2>&1 || true; done
  aws logs delete-log-group --log-group-name /aws/apigateway/welcome >/dev/null 2>&1 || true
}
trap cleanup EXIT

write_rev1
npm run build
npx cdk deploy --require-approval never --outputs-file "$PROJECT_DIR/outputs.rev1.json"
API_URL="$(jq -r '.ScenarioStack.ApiUrl' "$PROJECT_DIR/outputs.rev1.json")"
echo "revision 1 API URL: $API_URL"

# Finding 1 fix: see the hcl_raw reference solution's identical comment --
# the load-bearing poll (POLL_TIMEOUT_S=180) lives in tests/live_check.py,
# shared with the negatives; check_200 here stays a quick regression check
# for /hello and /version, right after the FIRST deploy only (finding G6
# fix, 2026-08-07 -- see below).
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
npm run build
npx cdk deploy --require-approval never --outputs-file "$PROJECT_DIR/outputs.rev2.json"
API_URL="$(jq -r '.ScenarioStack.ApiUrl' "$PROJECT_DIR/outputs.rev2.json")"
echo "revision 2 API URL (should be identical -- same stage): $API_URL"

# Finding G6 fix (benchmark-integrity review, 2026-08-07): the identical
# bare, un-polled check_200 "hello"/"version" pair used to also run here,
# immediately after the second deploy -- the riskiest sample point for a
# spurious failure (measured 403s up to 60s post-deploy in the original
# review). Dropped; live_check.py's check_ok() below already polls
# /hello and /version (REGRESSION_POLL_TIMEOUT_S) as part of its own
# --expect ok contract, so this regression coverage is bounded now
# instead of resting on a single un-polled sample.

# Finding 5 fix: same shared checker as hcl_raw's reference solution (see
# that file's identical comment) -- one implementation, not an ad hoc
# single curl. Finding 3's fix (behavioral-only assertions, no deployment-
# count/stage-pointer check) lives there too.
python3 "$PROJECT_DIR/tests/live_check.py" --api-url "$API_URL" --expect ok
