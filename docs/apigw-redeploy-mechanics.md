# API Gateway deployment dependency + redeploy-on-change: exact mechanics

Source: [terraconstructs/base](https://github.com/terraconstructs/base) `src/aws/compute/{deployment,restapi,method,resource,model,integration,integrations/{lambda,aws,stepfunctions}}.ts`
(terraconstructs base library, ported from [aws/aws-cdk](https://github.com/aws/aws-cdk) `packages/aws-cdk-lib/aws-apigateway`).

## 0. TL;DR

`Deployment` (`src/aws/compute/deployment.ts`) reimplements AWS CDK's `Deployment`/
`LatestDeploymentResource` on `aws_api_gateway_deployment`. CFN gives CDK "replace the resource
when its logical ID changes" for free; Terraform gives neither an implicit dependency edge from
deployment to methods/integrations nor a content-addressed resource identity. terraconstructs
manually reproduces both:

1. **Ordering** — explicit `node.addDependency()` calls, lowered by CDKTF to `depends_on`.
2. **Redeploy-on-change** — CDK salts the Deployment's **CFN logical ID** with an MD5 hash of
   accumulated model fragments (a changed logical ID forces CFN to replace the resource,
   create-before-delete). terraconstructs instead salts a `triggers` map with the *same* hash,
   paired with `lifecycle { create_before_destroy = true }` so a changed hash forces a TF `-/+`
   replace before the old deployment is torn down.

Both trees compute the **literal same hash algorithm** (`md5(JSON.stringify(...))` over the same
accumulated components) — terraconstructs' `md5hash` (`src/private/md5.ts:1-12`) is a byte-for-byte
port of CDK's `core/lib/private/md5.ts`. They differ only in *where* the hash lands (`triggers`
value vs. CFN logical-ID suffix), not in what feeds it.

## 1. Checksum: inputs, landing spot, determinism

**Landing spot.** `Deployment` builds the L1 `apiGatewayDeployment.ApiGatewayDeployment`
(`deployment.ts:93-105`), then overrides its `triggers` attribute with a lazily-produced value:
`addOverride("triggers", Lazy.anyValue({ produce: () => this.calculateTriggers() }))`
(`deployment.ts:108-113`) — deferred so every `addToTriggers()` caller has registered by the time
it runs. `calculateTriggers()` (`deployment.ts:145-166`) collapses everything to one key:
`return { redeployment: checksum }` (line 166). An earlier design emitting per-component
`trigger-N` keys or an inline `Fn.sha1(Fn.jsonencode(...))` TF expression is commented out
(`deployment.ts:168-181`) — abandoned for "missing attribute separator" / nested-token resolver
errors, in favor of a concrete Node-computed MD5 hex string.

**Inputs.** `calculateTriggers()` prepends the entire synthesized `aws_api_gateway_rest_api`
config whenever the API is a concrete `RestApi`/`SpecRestApi` (not an imported one):

```ts
// deployment.ts:148-155
if (this.api instanceof RestApi || this.api instanceof SpecRestApi) {
  const apiInternal = this.api.node.defaultChild as apiGatewayRestApi.ApiGatewayRestApi;
  triggers.push(apiInternal.toTerraform().resource.aws_api_gateway_rest_api);
}
```

This mirrors CDK's `hash.push(this.stack.resolve(cfnRestApiCF))`
(`aws-cdk-lib/aws-apigateway/lib/deployment.ts:200-204`): the whole RestApi resource, including
`body` for `SpecRestApi` (`restapi.ts:792`), is hashed — an edited OpenAPI document is
automatically covered with zero extra wiring. Every other model construct pushes its own fragment
via `addToTriggers()`, each paired with a `node.addDependency()` for ordering (§2):

| Construct | Trigger payload | Site |
|---|---|---|
| `Method` | `{ method: { ...methodProps, integrationToken: bindResult?.deploymentToken } }` — full `ApiGatewayMethodConfig` (resourceId, httpMethod, authorization, authorizerId, apiKeyRequired, operationName, requestParameters, requestModels, requestValidatorId, authorizationScopes) | `method.ts:312-323` |
| `Resource` | `{ resource: resourceProps }` (restApiId, parentId, pathPart) | `resource.ts:501-506` |
| `Model` | `{ model: apiGatewayModelConfig }` (name, restApiId, contentType, description, schema) | `model.ts:205-212` |
| manual | anything, via `deployment.addToTriggers(data)` | `deployment.ts:195-202` |

**The Integration resource's own config (URI, requestTemplates, integrationResponses, etc.) is
never pushed into the trigger array directly.** The only channel is
`IntegrationConfig.deploymentToken` (`integration.ts:184-191`), which `Method` copies into its own
fragment as `integrationToken` (`method.ts:321`). Base `Integration.bind()`
(`integration.ts:251-293`) never sets it. `LambdaIntegration.bind()`
(`integrations/lambda.ts:65-107`) sets `deploymentToken = JSON.stringify({ functionName })`
**only if** `functionName` is a resolved, non-Token literal (line 100 `Token.isUnresolved` check)
— i.e. only when the user supplied an explicit `functionName`. `StepFunctionsIntegration` does the
analogous thing (`integrations/stepfunctions.ts:186-207`); `AwsIntegration` never sets it
(`integrations/aws.ts:117-121`). Both Lambda/StepFunctions checks are 1:1 ports of
`aws-cdk-lib/aws-apigateway/lib/integrations/lambda.ts:123-137`.

**Benchmark-relevant consequence**: changing a Lambda's *code* alone (asset hash), without
touching `functionName` or any Method-level property, does **not** change the trigger hash in
either terraconstructs or upstream CDK — inherited, identical behavior in both trees, not a
terraconstructs bug. A "modify a Lambda and redeploy" scenario that only edits inline code and
uses an auto-generated (tokenized) function name will **not** trigger a new deployment under this
mechanism; it needs to also touch something hashed (method `requestParameters`, path/resource
shape, a `Model` schema, the OpenAPI `body`, or an explicit `addToTriggers` call) to be a valid
positive fixture.

**Determinism.**

```ts
// deployment.ts:159-164
const checksum = md5hash(
  triggers.map((x) => this.stack.resolve(x)).map((c) => JSON.stringify(c)).join(""),
);
```

`stack.resolve(x)` resolves CDKTF tokens to their Terraform interpolation strings (e.g.
`"${aws_lambda_function.foo.arn}"`) before stringifying — the hash captures the reference
*expression*, not a runtime value, mirroring CDK's own `stack.resolve` in `calculateLogicalId`
(`aws-cdk-lib/.../deployment.ts:211`). There is **no explicit sorting** anywhere in
`calculateTriggers()`; determinism relies on (a) JS's guaranteed insertion-order preservation for
string keys under `JSON.stringify`, and (b) `triggerComponents` being populated in construct-tree
instantiation order — deterministic only if the user's app itself builds routes deterministically
(e.g. not iterating an unordered structure). Nothing here canonicalizes/sorts payloads before
hashing — a real fragility if user code's iteration order varies. `addToTriggers()` also throws if
called after the tree locks (`deployment.ts:196-200`), mirroring CDK's `addToLogicalId` lock check
(`aws-cdk-lib/.../deployment.ts:190-192`).

## 2. Explicit `depends_on` edges

`aws_api_gateway_deployment` has no implicit dependency from `rest_api_id` to the methods behind
it. Every contributor is wired via `node.addDependency()` (→ `depends_on`):

| Edge | Site |
|---|---|
| Deployment → Method | `method.ts:316` (from within `Method`'s ctor, once `api.latestDeployment` exists) |
| Deployment → Method (fan-out, either construction order) | `deployment.ts:211-220` `_addMethodDependency`, invoked from `restapi.ts:1051-1052` (`_attachMethod`) and `restapi.ts:1062-1063` (`_attachDeployment`) |
| Deployment → Resource | `resource.ts:503` |
| Deployment → Model | `model.ts:210` |
| Deployment → Integration + IntegrationResponse | `method.ts:638-641`, `657-660`, inside `Method.toTerraform()` (synth-time, not ctor-time — the Integration L1 resource is lazily created there too, `method.ts:631-637`) |
| Stage → Deployment | **implicit**: `deployment_id` is a direct TF attribute reference (`deployment.ts:126-129`); comment at `134-135` notes this is intentional |

Dependencies target the **underlying L1 TF resource** (`method.node.defaultChild as
apiGatewayMethod.ApiGatewayMethod`), not the L2 construct node — deliberate, per comments at
`deployment.ts:212-216` (mirrored at `aws-cdk-lib/.../deployment.ts:149-154`): depending on the L2
node would drag in child `LambdaPermission` resources and create a cycle
(Deployment → Permission → Function → ... → Deployment).

## 3. Lifecycle handling / stale-deployment avoidance

```ts
// deployment.ts:99-104
lifecycle: {
  createBeforeDestroy: props.lifecycle?.createBeforeDestroy ?? true, // default to true
  ...props.lifecycle,
},
```

`create_before_destroy = true` by default — this is what turns "triggers changed" into an actual
new deployment created *before* the old one is destroyed (without it, TF's default
destroy-then-create ordering leaves a window with no valid deployment behind the Stage). No
`prevent_destroy`/retain-deployments knob is wired up yet — stubbed and commented
(`deployment.ts:28-38`, `115-120`; corresponding test is `test.skip`, §4). `Stage` carries no
special lifecycle block; it relies purely on the `deployment_id` reference always pointing at
whichever single `ApiGatewayDeployment` address currently satisfies the trigger hash (Terraform
models this as *replacement* of one resource address, unlike CFN where a logical-ID-salted
resource is a genuinely distinct stack resource each hash).

## 4. Tests validating this (the oracle model)

`test/aws/compute/deployment.test.ts` (ported from `aws-cdk-lib/aws-apigateway/test/deployment.test.ts`):

- **`"minimal setup"`** (lines 38-95): one `toMatchObject` asserting `depends_on: [method,
  integration]`, `lifecycle: { create_before_destroy: true }`, and a pinned MD5 hex literal for
  `triggers.redeployment` (`"c1c96c1d4f89a28bb8c25e1149499450"`) — a literal-hash snapshot is
  itself a regression guard on the algorithm/input-set/key-order.
- **`describe("force redeployment (using triggers)")`** (176-274), three cases with three
  distinct pinned hashes: baseline (no explicit triggers, 177-203); after `addToTriggers({foo:
  "123"})` (205-232, new hash `"691b6e..."`); after adding both a plain value and a
  `Lazy.stringValue` token trigger (234-273, new hash `"acb4bd..."`) — proves token resolution
  participates in and changes the hash deterministically.
- **`"integration change invalidates deployment"`** (304-359): two structurally-identical APIs in
  two stacks/apps with two different `LambdaFunction`s, asserting `deployment1Triggers !==
  deployment2Triggers`. Note: since both functions use auto-generated names, `deploymentToken` is
  `undefined` for both — what actually differs is the two RestApi resources' own rendered config
  (different stack/logical names), not the Lambda integration per se (see §1 caveat).
- **`"deployment resource depends on all restapi methods defined"`** (361-393): adds
  methods/resources *after* `Deployment`/`Stage` already exist, asserts the final `depends_on`
  contains all three methods and all three integrations — direct oracle model for "every route
  integration is a dependency," the mechanic the existing v1 `apigw-openapi` negative fixture
  (`deployment-missing-integration-dependency`) catches when absent.
- `test/aws/compute/restapi.test.ts:47-140` (`"minimal setup"`) duplicates the same
  triggers/`depends_on`/`lifecycle` shape through the `RestApi` L2 entry point, own pinned hash
  (`"d33a4984..."`, line 121) — a second, independent oracle fixture.

All of these are synth-time only (no `terraform apply`); none applies twice and diffs live
deployment IDs.

## 5. What a raw-HCL operator must hand-write to match this

```hcl
resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.widgets.id,
      aws_api_gateway_method.widgets_get.id,
      aws_api_gateway_integration.widgets_get.id,
      aws_api_gateway_method.widgets_get.request_parameters,
      # ... one entry per method/integration/resource/model, kept in sync by hand
    ]))
  }
  lifecycle { create_before_destroy = true }
  depends_on = [aws_api_gateway_method.widgets_get, aws_api_gateway_integration.widgets_get]
}
```

Pitfalls the L2 mechanics sidestep by construction:

- **Missing resources in the hash/`depends_on` list.** Nothing forces exhaustiveness as routes are
  added — exactly what the L2's automatic `addToTriggers`/`node.addDependency` self-registration
  (§1, §2) eliminates. In raw HCL, a forgotten new method leaves `terraform plan` showing a clean,
  unchanged deployment.
- **Non-canonical maps inside `jsonencode`.** `jsonencode` sorts keys alphabetically — more
  deterministic than the L2's insertion-order `JSON.stringify` *if* every value is already
  concrete at plan time; if a fed-in `for`/map expression's iteration order isn't guaranteed, the
  hash can jitter across plans with no real config change.
- **Plan-time-unknown values in `triggers` → perpetual diffs.** Any not-yet-known value inside
  `sha1(jsonencode([...]))` (e.g. a same-apply resource's computed/versioned ARN) makes
  `triggers.redeployment` "known after apply" on every plan, so `aws_api_gateway_deployment` shows
  a forced-replace diff on *every* `apply` even with no semantic change. The L2's token→reference-
  expression resolution (§1) is structurally immune to this (always a known value at plan time),
  at the cost of being insensitive to a same-address resource's runtime content unless that content
  was itself resolved into the hashed object.
- **Forgetting `create_before_destroy`.** Produces a real availability gap on replacement even
  with otherwise-correct trigger/depends_on hygiene.

## 6. Verdict: statically-assertable facts per arm, and what needs a live loop

### (a) Terraform plan JSON — hcl-raw and terraconstructs

1. `resource_changes[] | select(.type == "aws_api_gateway_deployment")` has a non-null, single-key
   `{redeployment: <hex>}` `triggers` map (terraconstructs) or operator-defined equivalent
   (hcl-raw); absent/null triggers is a certain stale-serving config.
2. Diffing two synths (revision N vs. N+1, e.g. changed `request_parameters` or OpenAPI `body`):
   `triggers.redeployment` **must differ** — computable from two `terraform show -json` (or two
   synthesized `main.tf.json`) outputs, no apply needed, since the hash is a pure function of
   static config.
3. `.change.after.lifecycle.create_before_destroy == true` on the deployment resource.
4. The deployment's `depends_on` (synthesized config or plan `configuration.root_module`) includes
   every `aws_api_gateway_method.*`/`aws_api_gateway_integration.*` address defined elsewhere —
   the existing v1 `deployment-missing-integration-dependency` check, unchanged.
5. With prior applied state available (a `.tfstate`, not necessarily a live account): a re-plan's
   `resource_changes[].change.actions == ["create","delete"]` for the deployment exactly when the
   hash changed, `[]` otherwise — static-with-a-baseline, not pure single-plan static.

### (b) Synthesized CFN — awscdk

1. The Deployment's logical ID is **salted**: `overrideLogicalId(Token.asString(this
   .hashComponents.derive(comps => this.calculateLogicalId(comps))))`
   (`aws-cdk-lib/aws-apigateway/lib/deployment.ts:180`); `calculateLogicalId` (lines 197-215) is
   `originalLogicalId + md5hash(...)`, i.e. the logical ID itself is `<baseId><32-hex-md5>` —
   greppable with `^.*Deployment[0-9a-f]{32}$` in the synthesized template.
2. Because the salt is the resource's own template key, "did redeploy trigger" is a set-difference
   over `Resources` keys between two synths — no hashing/parsing needed by the grader.
3. `Resources["<Deployment>"].DependsOn` lists every `AWS::ApiGateway::Method` logical ID
   (`aws-cdk-lib/.../deployment.ts:149-156`) — same structural check as (a)(4).
4. No `DeletionPolicy`/`UpdateReplacePolicy: Retain` unless `retainDeployments: true` — CFN needs
   no `create_before_destroy` analogue since a logical-ID change *is* a replacement by definition.

### (c) Facts only verifiable behaviorally (apply → modify → re-apply → curl)

- The **runtime deployment ID** actually changed (`aws apigateway get-stage`/`get-deployments`) —
  static diffs prove intent, not that AWS accepted the new deployment (a dependency-cycle or
  API-Gateway-side validation error can still fail apply despite a correct-looking triggers diff).
- The **live stage endpoint** actually serves updated behavior after the second apply, not stale
  cached behavior — the actual user-visible failure mode this whole mechanism exists to prevent;
  only observable by invoking the deployed API.
- An **unchanged** hash genuinely produces a no-op apply (`0 to change` for the deployment
  resource) on real previously-applied state — guards against a hash that looks stable across two
  static synths but isn't once provider-computed values are involved.
- Availability during the replace window (does `create_before_destroy` avoid a live 5xx gap) — a
  timing property with no static analogue.
